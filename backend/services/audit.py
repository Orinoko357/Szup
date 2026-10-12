"""
Audit logging — append-only, 24-month retention (NIS2/KSC).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlmodel import Session

from models import AuditLog

_log = logging.getLogger("szup.audit")


def record_event(
    session: Session,
    *,
    action: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> None:
    try:
        entry = AuditLog(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            method=method,
            path=path,
            status_code=status_code,
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
        )
        session.add(entry)
        if commit:
            session.commit()
    except Exception as exc:
        _log.warning("Failed to write AuditLog (action=%s): %s", action, exc)


def record_event_standalone(**kwargs) -> None:
    from database import engine as db_engine
    try:
        with Session(db_engine) as s:
            record_event(s, commit=True, **kwargs)
    except Exception as exc:
        _log.warning("Audit standalone write failed: %s", exc)


def request_meta(request: Request) -> dict[str, Optional[str]]:
    if request is None:
        return {"ip": None, "user_agent": None}
    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else None)
    return {"ip": ip, "user_agent": request.headers.get("user-agent")}
