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


# Jedyne zaufane proxy: Apache na tym samym hoście (backend słucha na 127.0.0.1).
_TRUSTED_PROXIES = {"127.0.0.1", "::1"}


def client_ip(request) -> Optional[str]:
    """Adres IP klienta — wspólny dla audytu, middleware i limitu logowań.

    X-Forwarded-For uwzględniamy WYŁĄCZNIE, gdy połączenie przyszło od zaufanego
    proxy (localhost). Apache DOPISUJE prawdziwy adres klienta NA KOŃCU nagłówka,
    więc bierzemy OSTATNI element — wcześniejsze może podać sam klient
    (podszycie pod inny adres, obejście limitu prób logowania).

    Klient może też wysłać WŁASNY, osobny nagłówek X-Forwarded-For — wtedy
    żądanie ma ich kilka, a `headers.get()` zwróciłby tylko pierwszy (podany
    przez klienta). Dlatego łączymy wszystkie wystąpienia w kolejności
    otrzymania i dopiero z całości bierzemy ostatni element.
    """
    if request is None:
        return None
    peer = request.client.host if getattr(request, "client", None) else None
    if peer in _TRUSTED_PROXIES:
        headers = request.headers
        if hasattr(headers, "getlist"):
            values = headers.getlist("x-forwarded-for")
        else:
            one = headers.get("x-forwarded-for")
            values = [one] if one else []
        xff = ",".join(v for v in values if v)
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return peer


def request_meta(request: Request) -> dict[str, Optional[str]]:
    if request is None:
        return {"ip": None, "user_agent": None}
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}
