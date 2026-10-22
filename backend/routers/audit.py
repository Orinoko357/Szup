"""
Router: Audit log viewer + CSV export — superadmin/admin only.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select, col

from database import get_session
from models import AuditLog, User
from services.auth_service import get_current_user
from services.permissions import require_admin

router = APIRouter()


@router.get("/")
def list_audit(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(500, le=5000),
    offset: int = 0,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(AuditLog)
    if since:
        stmt = stmt.where(AuditLog.timestamp >= since)
    if until:
        stmt = stmt.where(AuditLog.timestamp <= until)
    if username:
        stmt = stmt.where(AuditLog.username == username)
    if action:
        stmt = stmt.where(col(AuditLog.action).like(f"{action}%"))
    stmt = stmt.order_by(col(AuditLog.timestamp).desc()).limit(limit).offset(offset)
    rows = session.exec(stmt).all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "username": r.username,
            "user_id": r.user_id,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "method": r.method,
            "path": r.path,
            "status_code": r.status_code,
            "ip": r.ip,
            "details": r.details,
        }
        for r in rows
    ]


@router.get("/export.csv")
def export_audit_csv(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if since is None:
        since = datetime.utcnow() - timedelta(days=90)
    stmt = select(AuditLog).where(AuditLog.timestamp >= since)
    if until:
        stmt = stmt.where(AuditLog.timestamp <= until)
    stmt = stmt.order_by(col(AuditLog.timestamp).asc())
    rows = session.exec(stmt).all()

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["timestamp","username","user_id","action",
                     "method","path","status_code","ip","details"])
    for r in rows:
        writer.writerow([
            r.timestamp.isoformat(), r.username or "", r.user_id or "",
            r.action, r.method or "", r.path or "", r.status_code or "",
            r.ip or "", r.details or "",
        ])
    buf.seek(0)
    fname = f"szup-audit-{since.date()}_{(until or datetime.utcnow()).date()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/stats")
def audit_stats(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from sqlalchemy import func
    total  = session.exec(select(func.count()).select_from(AuditLog)).one()
    oldest = session.exec(select(func.min(AuditLog.timestamp))).one()
    newest = session.exec(select(func.max(AuditLog.timestamp))).one()
    return {
        "total_entries": total,
        "oldest": oldest.isoformat() if oldest else None,
        "newest": newest.isoformat() if newest else None,
    }


class AuditDeleteRequest(BaseModel):
    password: str
    mode: str = "filter"            # all | before | filter
    before: Optional[datetime] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    username: Optional[str] = None
    action: Optional[str] = None


@router.post("/delete")
def delete_audit(
    data: AuditDeleteRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Usuwanie wpisów audit logu przez administratora (decyzja właściciela
    systemu — świadomie odstępuje od „append-only” wymaganego przez NIS2/KSC).
    Wymaga hasła. Tryby: all — wszystko; before — starsze niż data;
    filter — pasujące do filtra (jak na liście). Ślad samej operacji jest
    zapisywany PO czyszczeniu jako nowy wpis (kto, kiedy, ile, jaki zakres)."""
    from sqlalchemy import delete, func, text
    from services.auth_service import verify_user_password
    from services.audit import record_event, request_meta
    from database import _install_auditlog_triggers

    if not verify_user_password(session, current_user, data.password):
        raise HTTPException(403, "Nieprawidłowe hasło — wpisy nie zostały usunięte")

    stmt = delete(AuditLog)
    conds = []
    if data.mode == "all":
        pass
    elif data.mode == "before":
        if not data.before:
            raise HTTPException(400, "Podaj datę — usunięte zostaną wpisy starsze niż ona")
        conds.append(AuditLog.timestamp < data.before)
    elif data.mode == "filter":
        if data.since:
            conds.append(AuditLog.timestamp >= data.since)
        if data.until:
            conds.append(AuditLog.timestamp <= data.until)
        if data.username:
            conds.append(AuditLog.username == data.username)
        if data.action:
            conds.append(col(AuditLog.action).like(f"{data.action}%"))
        if not conds:
            raise HTTPException(400, "Filtr jest pusty — wybierz tryb „Wszystkie”, jeśli chcesz usunąć cały log")
    else:
        raise HTTPException(400, "Nieznany tryb usuwania")
    for c in conds:
        stmt = stmt.where(c)

    # Triggery „append-only” zdejmujemy tylko na czas tej transakcji.
    for trg in ("auditlog_no_update", "auditlog_no_delete"):
        session.exec(text(f'DROP TRIGGER IF EXISTS "{trg}"'))
    try:
        res = session.exec(stmt)
        deleted = int(res.rowcount or 0)
        session.commit()
    finally:
        _install_auditlog_triggers()

    meta = request_meta(request)
    record_event(session, action="audit.purged", user_id=current_user.id,
                 username=current_user.username, ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"mode": data.mode, "deleted": deleted,
                          "before": data.before.isoformat() if data.before else None,
                          "username": data.username, "action": data.action})
    remaining = session.exec(select(func.count()).select_from(AuditLog)).one()
    return {"deleted": deleted, "remaining": int(remaining)}
