"""
Wnioski o zmianę nazwiska — lekki, samodzielny obieg (pracownik → IT).

W odróżnieniu od wniosków o uprawnienia: pracownik zgłasza SAM DLA SIEBIE,
bez akceptacji kierownika i bez pozycji uprawnień. Trafia wprost do IT, które
realizuje: zmienia `full_name`, a login (`username`) może — ale nie musi —
zmienić. Zmiana loginu wymusza ponowne logowanie (JWT identyfikuje po loginie).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, col, select

from database import get_session
from models import NameChangeRequest, User
from services.auth_service import get_current_user
from services.permissions import require_it_staff

router = APIRouter()

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


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
        pass
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
        pass

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


@router.post("/{req_id}/resolve")
def resolve_name_change(
    req_id: int,
    data: NameChangeResolve,
    request: Request,
    current_user: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    """IT realizuje wniosek: zmienia nazwisko (i ewentualnie login) albo odrzuca."""
    r = session.get(NameChangeRequest, req_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    if r.status != "pending":
        raise HTTPException(400, "Ten wniosek został już rozpatrzony.")

    user = session.get(User, r.user_id)
    if not user:
        raise HTTPException(400, "Konto pracownika nie istnieje.")

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
            taken = session.exec(
                select(User).where(User.username == new_login)
                .where(User.id != user.id)).first()
            if taken:
                raise HTTPException(400, f'Login „{new_login}" jest już zajęty.')
            r.old_username = user.username
            r.new_username = new_login
            r.username_changed = True
            user.username = new_login
            # JWT identyfikuje użytkownika po loginie (`sub`), więc stare tokeny
            # przestają działać automatycznie — lookup po starym loginie zawodzi
            # (401 → ponowne logowanie). NIE ruszamy `tokens_valid_from`: aplikacja
            # celowo cofa `iat` o zapas na skew zegara, więc ustawienie go „na
            # teraz" unieważniłoby też świeżo wydane tokeny po nowym loginie.
        session.add(user)
        r.status = "done"
    else:
        raise HTTPException(400, "Nieznana akcja (apply/reject).")

    r.resolved_at = datetime.utcnow()
    r.resolved_by_user_id = current_user.id
    r.it_comment = (data.comment or "").strip() or None
    session.add(r); session.commit(); session.refresh(r)

    try:
        from services.audit import record_event, request_meta
        meta = request_meta(request)
        record_event(session, action=f"name_change.{r.status}",
                     user_id=current_user.id, username=current_user.username,
                     target_type="name_change", target_id=r.id,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"worker_user_id": r.user_id,
                              "new_full_name": r.requested_full_name,
                              "username_changed": r.username_changed,
                              "new_username": r.new_username})
    except Exception:
        pass

    return _serialize(session, r)
