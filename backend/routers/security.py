"""
Router: Security events — superadmin/admin only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session, select, col

from database import get_session
from models import SecurityEvent, SecuritySeverity, User
from services.permissions import require_admin

router = APIRouter()


class ResolveRequest(BaseModel):
    note: Optional[str] = None


@router.get("/")
def list_events(
    resolved: Optional[bool] = None,
    severity: Optional[SecuritySeverity] = None,
    limit: int = Query(200, le=1000),
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(SecurityEvent)
    if resolved is True:
        stmt = stmt.where(col(SecurityEvent.resolved_at).is_not(None))
    elif resolved is False:
        stmt = stmt.where(col(SecurityEvent.resolved_at).is_(None))
    if severity:
        stmt = stmt.where(SecurityEvent.severity == severity)
    stmt = stmt.order_by(col(SecurityEvent.created_at).desc()).limit(limit)
    rows = session.exec(stmt).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "event_type": r.event_type,
            "severity": r.severity,
            "source": r.source,
            "summary": r.summary,
            "details": r.details,
            "user_id": r.user_id,
            "ip": r.ip,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "resolved_by_user_id": r.resolved_by_user_id,
            "resolution_note": r.resolution_note,
        }
        for r in rows
    ]


@router.get("/summary")
def summary(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from sqlalchemy import func
    open_total = session.exec(
        select(func.count()).select_from(SecurityEvent)
        .where(col(SecurityEvent.resolved_at).is_(None))
    ).one()
    by_sev = {}
    for sev in SecuritySeverity:
        n = session.exec(
            select(func.count()).select_from(SecurityEvent)
            .where(col(SecurityEvent.resolved_at).is_(None))
            .where(SecurityEvent.severity == sev)
        ).one()
        by_sev[sev.value] = n
    return {"open_total": open_total, "open_by_severity": by_sev}


@router.post("/{event_id}/resolve")
def resolve(
    event_id: int,
    data: ResolveRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    ev = session.get(SecurityEvent, event_id)
    if not ev:
        raise HTTPException(404, "Zdarzenie nie istnieje")
    if ev.resolved_at:
        return {"ok": True, "already": True}
    ev.resolved_at = datetime.utcnow()
    ev.resolved_by_user_id = current_user.id
    ev.resolution_note = (data.note or "")[:1000] or None
    session.add(ev); session.commit()
    return {"ok": True}


class SecurityDeleteRequest(BaseModel):
    password: str
    mode: str = "resolved"          # all | resolved | before
    before: Optional[datetime] = None


@router.post("/delete")
def delete_events(
    data: SecurityDeleteRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Usuwanie zdarzeń bezpieczeństwa przez administratora (wymaga hasła).
    Tryby: resolved — tylko rozwiązane; before — starsze niż data; all — wszystkie.
    Operacja trafia do audit logu."""
    from sqlalchemy import delete, func
    from services.auth_service import verify_user_password
    from services.audit import record_event, request_meta

    if not verify_user_password(session, current_user, data.password):
        raise HTTPException(403, "Nieprawidłowe hasło — zdarzenia nie zostały usunięte")
    stmt = delete(SecurityEvent)
    if data.mode == "resolved":
        stmt = stmt.where(col(SecurityEvent.resolved_at).is_not(None))
    elif data.mode == "before":
        if not data.before:
            raise HTTPException(400, "Podaj datę — usunięte zostaną zdarzenia starsze niż ona")
        stmt = stmt.where(SecurityEvent.created_at < data.before)
    elif data.mode != "all":
        raise HTTPException(400, "Nieznany tryb usuwania")
    deleted = int(session.exec(stmt).rowcount or 0)
    session.commit()
    meta = request_meta(request)
    record_event(session, action="security.purged", user_id=current_user.id,
                 username=current_user.username, ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"mode": data.mode, "deleted": deleted,
                          "before": data.before.isoformat() if data.before else None})
    remaining = session.exec(select(func.count()).select_from(SecurityEvent)).one()
    return {"deleted": deleted, "remaining": int(remaining)}
