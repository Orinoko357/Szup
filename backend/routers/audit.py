"""
Router: Audit log viewer + CSV export — superadmin/admin only.
Czyszczenie dziennika (POST /purge) — wyłącznie superadmin, z hasłem i powodem.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select, col

from database import get_session
from models import AuditLog, User
from services.csv_utils import csv_safe_row
from services.permissions import require_admin, require_superadmin

router = APIRouter()


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Filtr daty → naiwny UTC, bo tak zapisujemy `AuditLog.timestamp`.

    Frontend wysyła ISO ze strefą (np. `2026-10-22T08:00:00Z` albo `+02:00`);
    taką datę przeliczamy na UTC i zdejmujemy strefę, inaczej porównanie
    z kolumną bez strefy byłoby przesunięte. Daty bez strefy traktujemy
    jak dotąd — jako UTC.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/")
def list_audit(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    since, until = _naive_utc(since), _naive_utc(until)
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
    since, until = _naive_utc(since), _naive_utc(until)
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
        # Login, ścieżka i szczegóły mogą pochodzić od atakującego (np. nieudane
        # logowanie z loginem „=HYPERLINK(...)”) — neutralizujemy formuły.
        writer.writerow(csv_safe_row([
            r.timestamp.isoformat(), r.username or "", r.user_id or "",
            r.action, r.method or "", r.path or "", r.status_code or "",
            r.ip or "", r.details or "",
        ]))
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


class PurgeRequest(BaseModel):
    password: str                    # potwierdzenie hasłem wykonującego
    reason: str                      # wymagany, 10–1000 znaków
    before: Optional[str] = None     # data ISO (RRRR-MM-DD, północ czasu polskiego);
                                     # najpóźniej dziś minus 24 miesiące
    # Zgodność wstecz: jedyny tryb to "before" (trybu "all" nie ma od 3.10).
    mode: Optional[str] = "before"


@router.post("/purge")
def purge_audit(
    data: PurgeRequest,
    request: Request,
    current_user: User = Depends(require_superadmin),
    session: Session = Depends(get_session),
):
    """Czyszczenie dziennika zdarzeń — WYŁĄCZNIE superadmin (konto awaryjne).

    Wymaga hasła i powodu. Usuwa wyłącznie wpisy starsze niż `before`, przy
    czym `before` nie może być późniejsze niż dziś minus 24 miesiące
    (retencja; inaczej 400). Ślady czyszczeń i resetu fabrycznego zostają.
    Operacja jest atomowa: zdjęcie i założenie triggerów append-only, DELETE
    oraz ślad (wpis `audit.purged` + zdarzenie krytyczne) w jednej transakcji.
    """
    from services.audit import run_log_purge
    return run_log_purge(session, request, current_user, log="audit",
                         password=data.password, reason=data.reason,
                         mode=data.mode, before=data.before)
