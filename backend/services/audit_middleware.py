"""
ASGI middleware — auto-log mutating requests to audit log.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_log = logging.getLogger("szup.audit.mw")

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PATH_PREFIXES = (
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/logout",
)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        try:
            if request.method not in _MUTATING:
                return response
            path = request.url.path
            if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
                return response
            if not path.startswith("/api/"):
                return response

            username = None
            user_id  = None
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(None, 1)[1].strip()
                try:
                    from services.auth_service import _jwt_secret, ALGORITHM
                    from jose import jwt
                    payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM],
                                         options={"verify_exp": False})
                    username = payload.get("sub")
                except Exception:
                    pass
                if username:
                    try:
                        from database import engine as db_engine
                        from sqlmodel import Session, select
                        from models import User
                        with Session(db_engine) as s:
                            u = s.exec(select(User).where(User.username == username)).first()
                            if u:
                                user_id = u.id
                    except Exception:
                        pass

            xff = request.headers.get("x-forwarded-for")
            ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else None)
            action = f"api.{request.method.lower()}.{path[len('/api/'):]}"

            from services.audit import record_event_standalone
            record_event_standalone(
                action=action,
                user_id=user_id,
                username=username,
                method=request.method,
                path=path,
                status_code=response.status_code,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
            )
        except Exception as exc:
            _log.warning("AuditMiddleware failed: %s", exc)
        return response
