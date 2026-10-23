"""
Wnioski o zmianę nazwiska — lekki, samodzielny obieg (pracownik → IT).

W odróżnieniu od wniosków o uprawnienia: pracownik zgłasza SAM DLA SIEBIE,
bez akceptacji kierownika i bez pozycji uprawnień. Trafia wprost do IT, które
realizuje: zmienia `full_name`, a login (`username`) może — ale nie musi —
zmienić. Zmiana loginu unieważnia dotychczasowe sesje (`tokens_valid_from`)
i wymusza ponowne logowanie.

Rozdział obowiązków: rozpatruje wyłącznie pracownik IT (rola it_staff — sama
rola admin / superadmin nie wystarcza, bo administrator nie działa operacyjnie),
nikt nie rozpatruje własnego wniosku, a loginu konta z rolą admin / superadmin
w tym obiegu się nie zmienia (tylko nazwisko).

Konto AD: nowy login musi w AD należeć do TEGO SAMEGO obiektu (objectGUID albo
DN zapisany przy imporcie) — inaczej IT mogłoby przypiąć konto do cudzej
tożsamości domenowej (H4/F7). Gdy AD nie da się zapytać, zmiana loginu jest
odrzucana; samą zmianę nazwiska można zrealizować.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, col, select

from database import get_session
from models import AuthType, NameChangeRequest, SecuritySeverity, User, has_role
from services.auth_service import get_current_user, invalidate_tokens_now
from services.permissions import require_it_operator, require_it_staff

router = APIRouter()
_log = logging.getLogger("szup.name_changes")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
# Imię i nazwisko z wniosku (N2): krótkie, jedna linia.
FULL_NAME_MAX = 100
_LINE_BREAK_RE = re.compile(r"[\r\n\u2028\u2029]")
COMMENT_MAX = 1000


# ---------------------------------------------------------------------------
# Schematy
# ---------------------------------------------------------------------------

class NameChangeCreate(BaseModel):
    requested_full_name: str


class NameChangeResolve(BaseModel):
    action: str                        # "apply" | "reject"
    comment: Optional[str] = None
    # Opcjonalna zmiana loginu — IT decyduje. Puste = login bez zmian.
    new_username: Optional[str] = None


def _serialize(session: Session, r: NameChangeRequest) -> dict:
    u = session.get(User, r.user_id)
    resolver = session.get(User, r.resolved_by_user_id) if r.resolved_by_user_id else None
    return {
        "id": r.id,
        "user_id": r.user_id,
        "username": u.username if u else r.old_username,
        "current_full_name": r.current_full_name,
        "requested_full_name": r.requested_full_name,
        "status": r.status,
        "created_at": r.created_at,
        "resolved_at": r.resolved_at,
        "resolved_by_name": (resolver.full_name or resolver.username) if resolver else None,
        "it_comment": r.it_comment,
        "username_changed": r.username_changed,
        "old_username": r.old_username,
        "new_username": r.new_username,
    }


# ---------------------------------------------------------------------------
# Pracownik — zgłoszenie i podgląd własnych
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_name_change(
    data: NameChangeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Pracownik zgłasza zmianę nazwiska SAM DLA SIEBIE."""
    new_name = (data.requested_full_name or "").strip()
    if len(new_name) < 3:
        raise HTTPException(400, "Podaj nowe imię i nazwisko (min. 3 znaki).")
    if len(new_name) > FULL_NAME_MAX:
        raise HTTPException(400, f"Imię i nazwisko może mieć najwyżej {FULL_NAME_MAX} znaków.")
    if _LINE_BREAK_RE.search(new_name):
        raise HTTPException(400, "Imię i nazwisko musi mieścić się w jednej linii.")
    from services.auth_service import clean_text_field
    new_name = clean_text_field(new_name, "imię i nazwisko", max_len=FULL_NAME_MAX)
    if new_name == (current_user.full_name or "").strip():
        raise HTTPException(400, "Nowe nazwisko jest takie samo jak obecne.")

    # Jeden aktywny (nierozpatrzony) wniosek na osobę — bez zalewania kolejki IT.
    existing = session.exec(
        select(NameChangeRequest)
        .where(NameChangeRequest.user_id == current_user.id)
        .where(NameChangeRequest.status == "pending")
    ).first()
    if existing:
        raise HTTPException(
            400, "Masz już oczekujący wniosek o zmianę nazwiska — poczekaj na jego rozpatrzenie.")

    r = NameChangeRequest(
        user_id=current_user.id,
        current_full_name=current_user.full_name,
        requested_full_name=new_name,
    )
    session.add(r)
    # Powiadomienie helpdesku — w tle i dopiero po udanym commicie (nie blokuje
    # żądania na SMTP; przy nieudanym zapisie wiadomość nie wychodzi).
    try:
        from services.after_commit import defer
        from services.email_alerts import notify_name_change_requested
        defer(session, notify_name_change_requested,
              full_name=current_user.full_name or current_user.username,
              new_name=new_name,
              from_name=current_user.full_name or current_user.username,
              from_email=current_user.email)
    except Exception:
        _log.exception("Nie udało się zlecić powiadomienia helpdesku o wniosku "
                       "o zmianę nazwiska (user_id=%s)", current_user.id)
    session.commit(); session.refresh(r)

    # Ślad audytowy (best-effort).
    try:
        from services.audit import record_event, request_meta
        meta = request_meta(request)
        record_event(session, action="name_change.requested",
                     user_id=current_user.id, username=current_user.username,
                     target_type="name_change", target_id=r.id,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"requested_full_name": new_name})
    except Exception:
        _log.exception("Nie udało się zapisać audytu name_change.requested (wniosek %s)", r.id)

    return _serialize(session, r)


@router.get("/mine")
def my_name_changes(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        select(NameChangeRequest)
        .where(NameChangeRequest.user_id == current_user.id)
        .order_by(col(NameChangeRequest.created_at).desc())
    ).all()
    return [_serialize(session, r) for r in rows]


# ---------------------------------------------------------------------------
# IT — kolejka i realizacja
# ---------------------------------------------------------------------------

# Podgląd kolejki: IT, a także admin / superadmin (odczyt). Rozpatruje tylko IT.
@router.get("")
def list_name_changes(
    status: Optional[str] = None,
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    stmt = select(NameChangeRequest)
    if status and status != "all":
        stmt = stmt.where(NameChangeRequest.status == status)
    stmt = stmt.order_by(col(NameChangeRequest.created_at).desc())
    return [_serialize(session, r) for r in session.exec(stmt).all()]


def _login_taken(session: Session, login: str, user_id: int) -> bool:
    """Czy login jest zajęty przez INNE konto — bez względu na wielkość liter
    i realm (tak samo, jak szuka konta logowanie AD/SSO: `find_user_by_login`).
    Inaczej „NACZWF” obok „naczWF” dałoby dwa konta pod jednym loginem AD."""
    from sqlalchemy import func
    from services.ldap_service import normalize_login
    norm = normalize_login(login)
    return session.exec(
        select(User.id).where(func.lower(User.username) == norm)
        .where(User.id != user_id)).first() is not None


def _verify_ad_login(session: Session, user: User, new_login: str) -> dict:
    """Sprawdza w AD (konto usługowe), że `new_login` należy do tego samego
    obiektu co konto SZUP: zgodny objectGUID (zapisany przy imporcie) albo DN
    (`user.ldap_dn`). Zwraca dane dopasowania do zdarzenia; inaczej 403.

    Brak konfiguracji AD, brak zapisanej tożsamości albo błąd połączenia
    → odmowa zmiany loginu (zmianę nazwiska można zrealizować bez niej)."""
    from models import LdapSettings
    from services import ldap_service
    hint = " Zrealizuj wniosek bez zmiany loginu albo spróbuj ponownie później."
    cfg = session.exec(select(LdapSettings)).first()
    if not cfg or not cfg.enabled or not cfg.host:
        raise HTTPException(403, "Nie można zweryfikować nowego loginu w AD (logowanie "
                                 "przez AD jest wyłączone)." + hint)
    stored_guid = (getattr(user, "ldap_guid", None) or "").strip().lower() or None
    stored_dn = ldap_service.normalize_dn(user.ldap_dn or "") or None
    if not stored_guid and not stored_dn:
        raise HTTPException(403, "Konto nie ma zapisanej tożsamości z AD (DN / objectGUID) — "
                                 "najpierw zsynchronizuj je importem użytkowników z AD."
                                 + hint)
    status_, info = ldap_service.lookup_user(cfg, new_login)
    if status_ == "error":
        _log.warning("Weryfikacja loginu %s w AD nieudana: %s", new_login, info)
        raise HTTPException(403, "Nie udało się sprawdzić nowego loginu w AD "
                                 "(brak połączenia z serwerem)." + hint)
    if status_ == "not_found":
        raise HTTPException(400, f"Login „{new_login}” nie istnieje w AD — najpierw zmień "
                                 "login w AD, potem zrealizuj wniosek.")
    if status_ == "disabled":
        raise HTTPException(403, f"Konto „{new_login}” jest wyłączone w AD.")
    found_guid = (info.get("guid") or "").strip().lower() or None
    found_dn = ldap_service.normalize_dn(info.get("dn") or "") or None
    if stored_guid and found_guid:
        matched = "guid" if found_guid == stored_guid else None
    else:
        matched = "dn" if stored_dn and found_dn == stored_dn else None
    if not matched:
        raise HTTPException(403, f"Login „{new_login}” należy w AD do innej osoby (innego "
                                 "obiektu) niż to konto — zmiana loginu odrzucona.")
    return {"ad_verified_by": matched, "ad_dn": info.get("dn")}


def _notify_worker(session: Session, user: User, r: NameChangeRequest) -> None:
    """E-mail do pracownika o rozpatrzeniu wniosku (po commicie, w tle)."""
    to = (user.email or "").strip()
    if not to:
        return
    from services.after_commit import defer
    from services.email_alerts import _send
    if r.status == "done":
        subject = "SZUP: zmiana nazwiska zrealizowana"
        lines = [f"Twój wniosek o zmianę nazwiska na „{r.requested_full_name}” "
                 "został zrealizowany."]
        if r.username_changed:
            lines.append(f"Zmieniono też login: {r.old_username} → {r.new_username}. "
                         "Zaloguj się ponownie, używając nowego loginu.")
    else:
        subject = "SZUP: wniosek o zmianę nazwiska odrzucony"
        lines = [f"Twój wniosek o zmianę nazwiska na „{r.requested_full_name}” "
                 "został odrzucony."]
    if r.it_comment:
        lines.append(f"Uwagi IT: {r.it_comment}")
    defer(session, _send, to_address=to, subject=subject, body="\n\n".join(lines))


@router.post("/{req_id}/resolve")
def resolve_name_change(
    req_id: int,
    data: NameChangeResolve,
    request: Request,
    current_user: User = Depends(require_it_operator),
    session: Session = Depends(get_session),
):
    """IT realizuje wniosek: zmienia nazwisko (i ewentualnie login) albo odrzuca."""
    r = session.get(NameChangeRequest, req_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    if r.status != "pending":
        raise HTTPException(400, "Ten wniosek został już rozpatrzony.")
    if r.user_id == current_user.id:
        raise HTTPException(403, "Nie możesz rozpatrzyć własnego wniosku — "
                                 "zrobi to inna osoba z IT.")

    user = session.get(User, r.user_id)
    if not user:
        raise HTTPException(400, "Konto pracownika nie istnieje.")

    comment = (data.comment or "").strip()
    if len(comment) > COMMENT_MAX:
        raise HTTPException(400, f"Uwagi mogą mieć najwyżej {COMMENT_MAX} znaków.")

    login_change = None
    ad_check: dict = {}
    if data.action == "reject":
        r.status = "rejected"
    elif data.action == "apply":
        # 1) Zmiana nazwiska (zawsze przy realizacji).
        user.full_name = r.requested_full_name
        # 2) Opcjonalna zmiana loginu.
        new_login = (data.new_username or "").strip()
        if new_login and new_login != user.username:
            if not _USERNAME_RE.match(new_login):
                raise HTTPException(
                    400, "Login może zawierać litery, cyfry oraz . _ - (3–64 znaki).")
            if has_role(user, "admin", "superadmin"):
                raise HTTPException(
                    403, "Loginu konta z rolą administratora nie zmienia się w tym "
                         "obiegu — zrealizuj wniosek bez zmiany loginu.")
            if user.auth_type == AuthType.ldap:
                # Konto AD: login musi być loginem domenowym w postaci, w jakiej
                # zapisuje go logowanie AD/SSO (małe litery, bez realmu).
                from services.ldap_service import normalize_login, is_valid_login
                new_login = normalize_login(new_login)
                if not is_valid_login(new_login):
                    raise HTTPException(400, "Nieprawidłowy login konta AD.")
            if _login_taken(session, new_login, user.id):
                raise HTTPException(400, f'Login „{new_login}" jest już zajęty.')
            if new_login != user.username and user.auth_type == AuthType.ldap:
                ad_check = _verify_ad_login(session, user, new_login)
            if new_login != user.username:
                login_change = (user.username, new_login)
                r.old_username = user.username
                r.new_username = new_login
                r.username_changed = True
                user.username = new_login
                # Dotychczasowe sesje tracą ważność (token wskazuje konto po `uid`,
                # ale zawiera też stary login) — pracownik loguje się ponownie.
                invalidate_tokens_now(user)
        session.add(user)
        r.status = "done"
    else:
        raise HTTPException(400, "Nieznana akcja (apply/reject).")

    r.resolved_at = datetime.utcnow()
    r.resolved_by_user_id = current_user.id
    r.it_comment = comment or None
    session.add(r)
    try:
        _notify_worker(session, user, r)
    except Exception:
        _log.exception("Nie udało się zlecić powiadomienia pracownika o rozpatrzeniu "
                       "wniosku o zmianę nazwiska %s", r.id)
    session.commit(); session.refresh(r)

    from services.audit import request_meta
    meta = request_meta(request)
    try:
        from services.audit import record_event
        record_event(session, action=f"name_change.{r.status}",
                     user_id=current_user.id, username=current_user.username,
                     target_type="name_change", target_id=r.id,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"worker_user_id": r.user_id,
                              "new_full_name": r.requested_full_name,
                              "username_changed": r.username_changed,
                              "new_username": r.new_username})
    except Exception:
        _log.exception("Nie udało się zapisać audytu name_change.%s (wniosek %s)",
                       r.status, r.id)

    if login_change:
        # Zmiana loginu zmienia tożsamość, pod którą konto loguje się (także
        # przez AD/SSO) — zdarzenie wysokie, zamyka je superadmin.
        from services.security_events import emit as emit_security_event
        emit_security_event(
            session, event_type="user.login_changed", source="name_changes",
            severity=SecuritySeverity.high,
            summary=(f"Zmieniono login konta {login_change[0]} → {login_change[1]} "
                     f"przez {current_user.username}"),
            details={"target_user_id": user.id, "old_username": login_change[0],
                     "new_username": login_change[1], "name_change_id": r.id,
                     **ad_check},
            user_id=current_user.id, ip=meta["ip"],
        )

    return _serialize(session, r)
