#!/usr/bin/env python3
"""
Create a SUPERADMIN user if not exists.
Usage: python scripts/init_superadmin.py <username> <password>
       or set INIT_SUPERADMIN_USERNAME / INIT_SUPERADMIN_PASSWORD env vars
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from config import settings
    username = sys.argv[1] if len(sys.argv) > 1 else settings.INIT_SUPERADMIN_USERNAME
    password = sys.argv[2] if len(sys.argv) > 2 else settings.INIT_SUPERADMIN_PASSWORD

    if not username or not password:
        print("Usage: python scripts/init_superadmin.py <username> <password>")
        sys.exit(1)

    # Ensure tables exist
    from database import create_db_and_tables, SessionLocal
    create_db_and_tables()

    from sqlalchemy import text
    from auth import hash_password
    from datetime import datetime

    session = SessionLocal()
    try:
        existing = session.execute(
            text("SELECT id FROM uzytkownicy WHERE username=:u AND rola='SUPERADMIN'"),
            {"u": username},
        ).mappings().first()

        if existing:
            print(f"Superadmin '{username}' already exists (id={existing['id']}). Skipping.")
        else:
            h = hash_password(password)
            row = session.execute(
                text("""INSERT INTO uzytkownicy (username, rola, hash_hasla, aktywny, wymagaj_zmiany_hasla, nieudane_logowania, data_utworzenia)
                        VALUES (:u, 'SUPERADMIN', :h, 1, 0, 0, :dt) RETURNING id"""),
                {"u": username, "h": h, "dt": datetime.utcnow()},
            ).mappings().first()
            session.commit()
            print(f"Superadmin '{username}' created with id={row['id']}.")
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
