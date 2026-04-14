from __future__ import annotations
import json
from typing import Any, Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from auth import verify_access_token
from database import get_session
from models import Uzytkownik


class CurrentUser:
    def __init__(self, payload: dict):
        self.userId: int = int(payload.get("userId") or payload.get("sub", 0))
        self.username: str = payload.get("username", "")
        self.email: Optional[str] = payload.get("email")
        self.rola: str = payload.get("rola", "")
        self.tenantId: Optional[int] = payload.get("tenantId")


async def get_current_user(request: Request) -> CurrentUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Brak autoryzacji.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise credentials_exception
    token = auth_header[7:]
    try:
        payload = verify_access_token(token)
    except JWTError:
        raise credentials_exception
    return CurrentUser(payload)


def require_roles(*roles: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.rola not in roles:
            raise HTTPException(status_code=403, detail="Brak uprawnień.")
        return current_user
    return checker


def write_audit(
    session: Session,
    *,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    rola: Optional[str] = None,
    akcja: str,
    tabela_docelowa: Optional[str] = None,
    rekord_id: Optional[int] = None,
    stare_dane: Optional[Any] = None,
    nowe_dane: Optional[Any] = None,
    ip_adres: Optional[str] = None,
    user_agent: Optional[str] = None,
):
    from models import AuditLog
    from datetime import datetime
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        username=username,
        rola=rola,
        akcja=akcja,
        tabela_docelowa=tabela_docelowa,
        rekord_id=rekord_id,
        stare_dane=json.dumps(stare_dane, default=str) if stare_dane is not None else None,
        nowe_dane=json.dumps(nowe_dane, default=str) if nowe_dane is not None else None,
        ip_adres=ip_adres,
        user_agent=user_agent,
        timestamp=datetime.utcnow(),
    )
    session.add(log)
    try:
        session.commit()
    except Exception:
        session.rollback()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
