from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlmodel import SQLModel
from config import settings


def _get_db_path() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        if not os.path.isabs(rel):
            base = Path(__file__).parent
            abs_path = base / rel
        else:
            abs_path = Path(rel)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{abs_path}"
    return url


DATABASE_URL = _get_db_path()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    with SessionLocal() as session:
        yield session


def create_db_and_tables():
    import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def _run_migrations():
    """Add columns/tables introduced after initial schema creation."""
    from sqlalchemy import text
    with SessionLocal() as session:
        migrations = [
            "ALTER TABLE pracownicy ADD COLUMN jednostka_id INTEGER REFERENCES jednostki_org(id)",
            "ALTER TABLE pracownicy ADD COLUMN imie TEXT",
            "ALTER TABLE pracownicy ADD COLUMN nazwisko TEXT",
            "ALTER TABLE pracownicy ADD COLUMN email TEXT",
        ]
        for sql in migrations:
            try:
                session.execute(text(sql))
                session.commit()
            except Exception:
                session.rollback()  # column already exists — ignore
