"""
Oświadczenia wnioskującego — utrwalanie i kod referencyjny.

Kod referencyjny to czytelny identyfikator złożenia oświadczenia:

    login-RRRRMMDD-GGMMSS-XXXXXXXX

gdzie:
  - login    — username osoby składającej oświadczenie (wnioskodawca),
  - RRRRMMDD  — data systemowa zatwierdzenia wniosku,
  - GGMMSS    — godzina systemowa zatwierdzenia wniosku,
  - XXXXXXXX  — 8-znakowy losowy ciąg alfanumeryczny (A–Z, 0–9).

Segmenty rozdziela myślnik; wewnątrz daty/godziny nie ma separatorów, żeby
myślnik jednoznacznie oddzielał segmenty. Losowy ogon zapewnia unikalność
nawet przy wielu oświadczeniach tej samej osoby w tej samej sekundzie.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from models import PermissionDeclaration

# Bez znaków mylących w druku (0/O, 1/I) — czytelniejsze przy przepisywaniu.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LOGIN_RE = re.compile(r"[^A-Za-z0-9]+")


def _rand_tail(n: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def make_reference_code(login: str, approved_at: datetime) -> str:
    """Zbuduj kod referencyjny dla podanego loginu i momentu zatwierdzenia."""
    safe_login = _LOGIN_RE.sub("", login or "") or "user"
    stamp = approved_at.strftime("%Y%m%d-%H%M%S")
    return f"{safe_login}-{stamp}-{_rand_tail()}"


def unique_reference_code(session: Session, login: str, approved_at: datetime) -> str:
    """Kod referencyjny gwarantowany jako niezajęty w bazie (retry na kolizji)."""
    for _ in range(10):
        code = make_reference_code(login, approved_at)
        exists = session.exec(
            select(PermissionDeclaration.id)
            .where(PermissionDeclaration.reference_code == code)
        ).first()
        if not exists:
            return code
    # Skrajnie nieprawdopodobne — dłuższy ogon jako ostateczność.
    return f"{make_reference_code(login, approved_at)}-{_rand_tail(4)}"


def build_items_snapshot(session: Session, request) -> str:
    """Zamrożony obraz nadawanych pozycji (nazwy systemów/uprawnień + zakres),
    żeby rejestr i audyt czytały je nawet po zmianach w rejestrze oprogramowania.
    """
    from models import PermissionSystem, RequestItem, SystemPermission

    rows = session.exec(
        select(RequestItem).where(RequestItem.request_id == request.id)
    ).all()
    out = []
    for it in rows:
        if (getattr(it, "kind", "grant") or "grant") != "grant":
            continue
        sysrow = session.get(PermissionSystem, it.system_id)
        perm = session.get(SystemPermission, it.permission_id)
        vals = {}
        raw = getattr(it, "custom_values", None)
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    vals = {str(k): str(v) for k, v in loaded.items()}
            except (json.JSONDecodeError, TypeError):
                vals = {}
        out.append({
            "system_name": sysrow.name if sysrow else None,
            "permission_name": perm.permission_name if perm else None,
            "custom_values": vals,
        })
    return json.dumps(out, ensure_ascii=False)


# Granice pól oświadczenia: nazwisko jak w kartotece, data złożenia oświadczenia
# nie z przyszłości i nie starsza niż kilka lat (literówka w roku).
DECLARED_NAME_MAX = 200
DECLARED_DATE_MAX_AGE_DAYS = 3650


# Adnotacja oświadczenia złożonego przez superadmina w trybie rezerwy.
EMERGENCY_NOTE = ("[Działając awaryjnie jako superadmin — w strukturze nie ma osoby "
                  "uprawnionej do wykonania tego kroku]")


def is_emergency_text(text: Optional[str]) -> bool:
    """Czy zamrożona treść oświadczenia ma adnotację trybu awaryjnego."""
    return bool(text) and text.startswith(EMERGENCY_NOTE)


def validate_declaration(declared_by_name: Optional[str],
                         declared_date: Optional[str]) -> tuple[str, str]:
    """Sprawdź dane oświadczenia wnioskującego. Zwraca (imię i nazwisko,
    data RRRR-MM-DD) po oczyszczeniu albo rzuca ValueError z polskim
    komunikatem (router zamienia go na 400).

    - imię i nazwisko: niepuste, najwyżej 200 znaków, bez znaków sterujących,
    - data: poprawna data RRRR-MM-DD, nie z przyszłości (dzień zapasu na
      strefę czasową) i nie starsza niż 10 lat."""
    from datetime import date, timedelta
    name = (declared_by_name or "").strip()
    if not name:
        raise ValueError("Wpisz imię i nazwisko osoby składającej oświadczenie.")
    if len(name) > DECLARED_NAME_MAX:
        raise ValueError(f"Imię i nazwisko w oświadczeniu może mieć najwyżej "
                         f"{DECLARED_NAME_MAX} znaków.")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Imię i nazwisko w oświadczeniu zawiera niedozwolone znaki.")
    raw = (declared_date or "").strip()
    try:
        when = date.fromisoformat(raw)
        if len(raw) != 10:
            raise ValueError
    except ValueError:
        raise ValueError("Data oświadczenia musi być poprawną datą w formacie RRRR-MM-DD.")
    today = date.today()
    # Jeden dzień zapasu na różnicę stref czasowych przeglądarki i serwera.
    if when > today + timedelta(days=1):
        raise ValueError("Data oświadczenia nie może być z przyszłości.")
    if when < today - timedelta(days=DECLARED_DATE_MAX_AGE_DAYS):
        raise ValueError("Data oświadczenia jest zbyt odległa — sprawdź rok.")
    return name, when.isoformat()


def create_declaration(
    session: Session,
    request,
    declared_by,
    declared_by_name: str,
    declared_date: str,
    declaration_text: str,
    approved_at: Optional[datetime] = None,
    emergency: bool = False,
) -> PermissionDeclaration:
    """Utwórz i zapisz oświadczenie dla wniosku. Zwraca rekord (z kodem).
    Dane oświadczenia są walidowane (`validate_declaration` — ValueError).

    `emergency=True` — oświadczenie składa superadmin działający jako rezerwa
    (brak osoby uprawnionej w strukturze): zamrożona treść dostaje adnotację
    `EMERGENCY_NOTE` (decyzja właściciela 3.11)."""
    declared_by_name, declared_date = validate_declaration(declared_by_name, declared_date)
    if emergency:
        declaration_text = f"{EMERGENCY_NOTE}\n\n{declaration_text or ''}".rstrip()
    when = approved_at or datetime.utcnow()
    code = unique_reference_code(session, declared_by.username, when)
    dec = PermissionDeclaration(
        request_id=request.id,
        worker_user_id=getattr(request, "worker_user_id", None),
        worker_name=request.worker_name,
        unit_id=getattr(request, "unit_id", None),
        department_id=getattr(request, "department_id", None),
        declared_by_user_id=declared_by.id,
        declared_by_login=declared_by.username,
        declared_by_name=declared_by_name.strip(),
        declared_date=(declared_date or "").strip(),
        approved_at=when,
        reference_code=code,
        declaration_text=declaration_text,
        items_snapshot=build_items_snapshot(session, request),
    )
    session.add(dec)
    session.flush()
    return dec
