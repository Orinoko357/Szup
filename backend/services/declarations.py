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


def create_declaration(
    session: Session,
    request,
    declared_by,
    declared_by_name: str,
    declared_date: str,
    declaration_text: str,
    approved_at: Optional[datetime] = None,
) -> PermissionDeclaration:
    """Utwórz i zapisz oświadczenie dla wniosku. Zwraca rekord (z kodem)."""
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
