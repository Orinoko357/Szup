"""
Router: Security events — superadmin/admin only.

Przegląd: admin i superadmin. Zamykanie: zdarzenia high/critical wyłącznie
superadmin; admin zamyka low/medium, z wyjątkiem dotyczących jego konta.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select, col

from database import get_session
from models import SecurityEvent, SecuritySeverity, User, has_role
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


# Zdarzenia o wysokiej wadze (nadanie roli admin, zmiana LDAP, reset do
# ustawień fabrycznych…) zamyka wyłącznie superadmin — administrator mógłby
# inaczej sam „wyciszyć” ślad własnego nadużycia uprawnień.
SUPERADMIN_ONLY_SEVERITIES = {SecuritySeverity.high, SecuritySeverity.critical}


def _target_user_id(ev: SecurityEvent) -> Optional[int]:
    """`details.target_user_id` zdarzenia (konto, którego zdarzenie dotyczy)."""
    details = ev.details
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return None
    if not isinstance(details, dict):
        return None
    try:
        raw = details.get("target_user_id")
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _guard_resolve(ev: SecurityEvent, current_user: User) -> None:
    """Kto może zamknąć zdarzenie. Superadmin — każde; admin — tylko low/medium
    i nie te, które dotyczą jego własnego konta."""
    if has_role(current_user, "superadmin"):
        return
    severity = getattr(ev.severity, "value", ev.severity)
    if severity in {s.value for s in SUPERADMIN_ONLY_SEVERITIES}:
        raise HTTPException(403,
            "Zdarzenie o wadze wysokiej lub krytycznej może zamknąć tylko superadmin")
    # Zdarzenie dotyczące samego admina (np. jego nieudane logowania, zmiany
    # wprowadzone przez niego albo nadanie mu roli) zamyka ktoś inny — inaczej
    # mógłby zacierać ślady.
    if current_user.id in (ev.user_id, _target_user_id(ev)):
        raise HTTPException(403,
            "Nie możesz zamknąć zdarzenia, które dotyczy Twojego konta — "
            "zrobi to inny administrator lub superadmin")


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
    _guard_resolve(ev, current_user)
    ev.resolved_at = datetime.utcnow()
    ev.resolved_by_user_id = current_user.id
    ev.resolution_note = (data.note or "")[:1000] or None
    session.add(ev); session.commit()
    return {"ok": True}
