#!/usr/bin/env python3
"""
Initialize the database: create all tables and insert default configuration.
Usage: python scripts/init_db.py
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import create_db_and_tables, SessionLocal
from sqlalchemy import text


def init():
    print("Creating tables...")
    create_db_and_tables()
    print("Tables created.")

    session = SessionLocal()
    try:
        # Insert default konfiguracja_numeracji if not exists
        existing = session.execute(text("SELECT id FROM konfiguracja_numeracji WHERE id=1")).mappings().first()
        if not existing:
            session.execute(
                text("INSERT INTO konfiguracja_numeracji (id, format_szablonu, prefix, szerokosc_sekwencji, reset_co, ostatni_numer) VALUES (1, '{PREFIX}.{SEQ}.{ROK}', 'ZUP', 4, 'ROK', 0)")
            )
            print("Inserted default konfiguracja_numeracji.")

        # Insert default konfiguracja_platformy entries
        defaults = [
            ("app.name", "SZUP", "Nazwa aplikacji"),
            ("app.version", "2.0.0", "Wersja aplikacji"),
            ("login.attempts_limit", "5", "Maksymalna liczba nieudanych logowań"),
            ("login.lockout_minutes", "15", "Czas blokady konta w minutach"),
            ("nis2.enabled", "true", "Czy NIS2 compliance jest aktywna"),
            ("notifications.email_enabled", "false", "Czy powiadomienia email są aktywne"),
        ]
        for klucz, wartosc, opis in defaults:
            existing_kp = session.execute(
                text("SELECT klucz FROM konfiguracja_platformy WHERE klucz=:k"),
                {"k": klucz},
            ).mappings().first()
            if not existing_kp:
                session.execute(
                    text("INSERT INTO konfiguracja_platformy (klucz, wartosc, opis) VALUES (:k, :v, :o)"),
                    {"k": klucz, "v": wartosc, "o": opis},
                )
        session.commit()
        print("Default configuration inserted.")
    except Exception as e:
        session.rollback()
        print(f"Error during init: {e}")
        raise
    finally:
        session.close()

    print("Database initialization complete.")


if __name__ == "__main__":
    init()
