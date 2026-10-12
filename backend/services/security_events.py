"""
Security events — tracked until resolved.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlmodel import Session

from models import SecurityEvent, SecuritySeverity

_log = logging.getLogger("szup.security")


def emit(
    session: Session,
    *,
    event_type: str,
    summary: str,
    severity: SecuritySeverity = SecuritySeverity.medium,
    source: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    user_id: Optional[int] = None,
    ip: Optional[str] = None,
    commit: bool = True,
) -> None:
    try:
        ev = SecurityEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            summary=summary[:512],
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
            user_id=user_id,
            ip=ip,
        )
        session.add(ev)
        if commit:
            session.commit()
    except Exception as exc:
        _log.warning("SecurityEvent emit failed (%s): %s", event_type, exc)


def emit_standalone(**kwargs) -> None:
    from database import engine as db_engine
    try:
        with Session(db_engine) as s:
            emit(s, commit=True, **kwargs)
    except Exception as exc:
        _log.warning("SecurityEvent standalone emit failed: %s", exc)
