"""
Router: Audit log viewer + CSV export — superadmin/admin only.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, col

from database import get_session
from models import AuditLog, User
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
