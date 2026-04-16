from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.NODE_ENV != "production" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SZUP backend (Python/FastAPI)")

    # Create data directory and init DB
    from database import create_db_and_tables
    create_db_and_tables()

    # Init superadmin from env vars if not exists
    try:
        from scripts.init_superadmin import main as init_sa
    except ImportError:
        pass
    try:
        _maybe_init_superadmin()
    except Exception as e:
        logger.warning(f"Superadmin init skipped: {e}")

    # Ensure default numeracja config
    try:
        _ensure_default_config()
    except Exception as e:
        logger.warning(f"Default config init skipped: {e}")

    # Start scheduler
    if settings.SCHEDULER_ENABLED:
        from services.scheduler_service import start as start_scheduler
        start_scheduler()

    yield

    # Shutdown
    try:
        from services.scheduler_service import stop as stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    logger.info("SZUP backend stopped.")


def _maybe_init_superadmin():
    from database import SessionLocal
    from sqlalchemy import text
    from auth import hash_password
    from datetime import datetime

    username = settings.INIT_SUPERADMIN_USERNAME
    password = settings.INIT_SUPERADMIN_PASSWORD
    if not username or not password:
        return

    session = SessionLocal()
    try:
        existing = session.execute(
            text("SELECT id FROM uzytkownicy WHERE username=:u AND rola='SUPERADMIN'"),
            {"u": username},
        ).mappings().first()
        if not existing:
            h = hash_password(password)
            session.execute(
                text("INSERT INTO uzytkownicy (username,rola,hash_hasla,aktywny,wymagaj_zmiany_hasla,nieudane_logowania,data_utworzenia) VALUES (:u,'SUPERADMIN',:h,1,0,0,:dt)"),
                {"u": username, "h": h, "dt": datetime.utcnow()},
            )
            session.commit()
            logger.info(f"Superadmin '{username}' created.")
    finally:
        session.close()


def _ensure_default_config():
    from database import SessionLocal
    from sqlalchemy import text

    session = SessionLocal()
    try:
        existing = session.execute(text("SELECT id FROM konfiguracja_numeracji WHERE id=1")).mappings().first()
        if not existing:
            session.execute(
                text("INSERT INTO konfiguracja_numeracji (id,format_szablonu,prefix,szerokosc_sekwencji,reset_co,ostatni_numer) VALUES (1,'{PREFIX}.{SEQ}.{ROK}','ZUP',4,'ROK',0)")
            )

        defaults = [
            ("app.name", "SZUP", "Nazwa aplikacji"),
            ("app.version", "2.0.0", "Wersja aplikacji"),
            ("login.attempts_limit", "5", "Maksymalna liczba nieudanych logowań"),
            ("login.lockout_minutes", "15", "Czas blokady konta w minutach"),
            ("nis2.enabled", "true", "Czy NIS2 compliance jest aktywna"),
            ("notifications.email_enabled", "false", "Czy powiadomienia email są aktywne"),
        ]
        for klucz, wartosc, opis in defaults:
            ex = session.execute(text("SELECT klucz FROM konfiguracja_platformy WHERE klucz=:k"), {"k": klucz}).mappings().first()
            if not ex:
                session.execute(
                    text("INSERT INTO konfiguracja_platformy (klucz,wartosc,opis) VALUES (:k,:v,:o)"),
                    {"k": klucz, "v": wartosc, "o": opis},
                )
        session.commit()
    finally:
        session.close()


app = FastAPI(
    title="SZUP API",
    description="NIS2 Compliance Permissions Management System",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Błąd serwera."},
    )


# Health check
@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


# Import and register routers
from routes.auth import router as auth_router
from routes.tenants import router as tenants_router
from routes.struktura_org import router as struktura_org_router
from routes.komorki import router as komorki_router
from routes.ldap_domeny import router as ldap_router
from routes.systemy_it import router as systemy_it_router
from routes.uzytkownicy import router as uzytkownicy_router
from routes.pracownicy import router as pracownicy_router
from routes.workflow import router as workflow_router
from routes.wnioski import router as wnioski_router
from routes.uprawnienia import router as uprawnienia_router
from routes.przeglady import router as przeglady_router
from routes.rejestry import router as rejestry_router
from routes.incydenty import router as incydenty_router
from routes.powiadomienia import router as powiadomienia_router
from routes.konfiguracja import router as konfiguracja_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(tenants_router, prefix="/api/tenants", tags=["tenants"])
app.include_router(struktura_org_router, prefix="/api/struktura-org", tags=["struktura-org"])
app.include_router(komorki_router, prefix="/api/komorki", tags=["komorki"])
app.include_router(ldap_router, prefix="/api/ldap-domeny", tags=["ldap-domeny"])
app.include_router(systemy_it_router, prefix="/api/systemy-it", tags=["systemy-it"])
app.include_router(uzytkownicy_router, prefix="/api/uzytkownicy", tags=["uzytkownicy"])
app.include_router(pracownicy_router, prefix="/api/pracownicy", tags=["pracownicy"])
app.include_router(workflow_router, prefix="/api/workflow", tags=["workflow"])
app.include_router(wnioski_router, prefix="/api/wnioski", tags=["wnioski"])
app.include_router(uprawnienia_router, prefix="/api/uprawnienia", tags=["uprawnienia"])
app.include_router(przeglady_router, prefix="/api/przeglady", tags=["przeglady"])
app.include_router(rejestry_router, prefix="/api/rejestry", tags=["rejestry"])
app.include_router(incydenty_router, prefix="/api/incydenty", tags=["incydenty"])
app.include_router(powiadomienia_router, prefix="/api/powiadomienia", tags=["powiadomienia"])
app.include_router(konfiguracja_router, prefix="/api/konfiguracja", tags=["konfiguracja"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.NODE_ENV != "production",
        workers=1,
    )
