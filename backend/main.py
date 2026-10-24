"""
SZUP — System Zarządzania Uprawnieniami IT.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.logging_setup import configure_logging
configure_logging()

from database import init_db
from routers import auth, users, audit, security as security_router, settings, requests, units, systems
from routers import workflow_templates, request_types, vendors, registry, snapshots, name_changes
from services.auth_service import get_current_user

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SZUP API starting")
    init_db()

    # Czyść wygasłe revoked tokeny
    try:
        from sqlmodel import Session, delete
        from models import RevokedToken
        from database import engine
        from datetime import datetime
        with Session(engine) as s:
            s.exec(delete(RevokedToken).where(RevokedToken.expires_at < datetime.utcnow()))
            s.commit()
    except Exception as e:
        logger.warning("RevokedToken purge failed: %s", e)

    # Harmonogram nocnych migawek uprawnień (23:50). Idempotentny; można
    # wyłączyć SZUP_SNAPSHOTS=0 (np. gdy używa się systemd timera z tools.snapshot).
    try:
        from services import scheduler
        scheduler.start()
    except Exception as e:
        logger.warning("Snapshot scheduler start failed: %s", e)

    yield
    try:
        from services import scheduler
        scheduler.stop()
    except Exception:
        logger.warning("Zatrzymanie harmonogramu migawek nie powiodło się", exc_info=True)
    logger.info("SZUP API stopped")


_PROD = os.getenv("SZUP_PROD", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="SZUP",
    version="3.11.0",
    description="System Zarządzania Uprawnieniami IT",
    lifespan=lifespan,
    docs_url=None if _PROD else "/docs",
    redoc_url=None if _PROD else "/redoc",
    openapi_url=None if _PROD else "/openapi.json",
)

allowed_origins = os.getenv(
    "SZUP_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


@app.exception_handler(IntegrityError)
async def _integrity_error_handler(request: Request, exc: IntegrityError):
    # M1 — z egzekwowanymi kluczami obcymi każde nieobsłużone naruszenie
    # integralności (np. próba usunięcia zasobu powiązanego z wnioskiem)
    # zwracamy jako czyste 409 zamiast surowego 500.
    logger.warning("IntegrityError na %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "Operacja narusza integralność danych — element jest "
                           "powiązany z innymi rekordami (np. wnioskami)."},
    )


@app.exception_handler(OverflowError)
async def _overflow_error_handler(request: Request, exc: OverflowError):
    # N10 / N-1 — identyfikator spoza zakresu INTEGER bazy (np. 2^63) w ścieżce,
    # zapytaniu albo treści żądania: sqlite3 rzuca OverflowError. To błąd danych
    # wejściowych (400), nie błąd serwera (500).
    logger.info("OverflowError na %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=400,
        content={"detail": "Nieprawidłowy identyfikator — liczba poza dopuszczalnym zakresem."},
    )


from services.audit_middleware import AuditMiddleware
app.add_middleware(AuditMiddleware)

from services.correlation_middleware import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)

from services.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

_protected = [Depends(get_current_user)]

app.include_router(auth.router,             prefix="/api/auth",     tags=["auth"])
app.include_router(requests.router,         prefix="/api/requests", tags=["requests"],  dependencies=_protected)
app.include_router(units.router,            prefix="/api/units",    tags=["units"],     dependencies=_protected)
app.include_router(systems.router,          prefix="/api/systems",  tags=["systems"],   dependencies=_protected)
app.include_router(vendors.router,          prefix="/api/vendors",  tags=["vendors"],   dependencies=_protected)
app.include_router(registry.router,         prefix="/api/registry", tags=["registry"],  dependencies=_protected)
app.include_router(snapshots.router,        prefix="/api/snapshots", tags=["snapshots"], dependencies=_protected)
app.include_router(name_changes.router,     prefix="/api/name-changes", tags=["name-changes"], dependencies=_protected)
app.include_router(settings.router,         prefix="/api/settings", tags=["settings"],  dependencies=_protected)
app.include_router(users.router,            prefix="/api/users",    tags=["users"],     dependencies=_protected)
app.include_router(audit.router,            prefix="/api/audit",    tags=["audit"],     dependencies=_protected)
app.include_router(security_router.router,  prefix="/api/security", tags=["security"],  dependencies=_protected)

# --- Workflow engine (konfigurowalny obieg wniosków) ---
app.include_router(workflow_templates.router, prefix="/api/workflow-templates", tags=["workflow"], dependencies=_protected)
app.include_router(request_types.router,      prefix="/api/request-types",      tags=["workflow"], dependencies=_protected)


@app.get("/api/health")
def health():
    from datetime import datetime
    return {"status": "ok", "version": app.version, "time_utc": datetime.utcnow().isoformat() + "Z"}
