#!/usr/bin/env python3
"""Awaryjne włączenie / wyłączenie trybu testowego SZUP.

Tryb testowy pozwala zalogować się SAMYM LOGINEM (bez hasła) i pomija blokadę
konta — użyj, gdy zablokowałeś sobie dostęp i nie możesz wejść w Ustawienia.

Skrypt zapisuje flagę `test_mode` bezpośrednio w bazie SQLite (nie wymaga
zalogowania ani zależności — tylko biblioteka standardowa). Backend czyta tę
flagę przy każdym logowaniu, więc NIE trzeba restartować usługi — wystarczy
odświeżyć stronę logowania.

UWAGA (hardening): sama flaga w bazie NIE otwiera już logowania bez hasła.
Backend wymaga DODATKOWO zmiennej środowiskowej po stronie procesu API:

    SZUP_ALLOW_TEST_MODE=1

Bez niej passwordless-login jest twardo zablokowany (zabezpieczenie produkcji
przed przypadkowo/złośliwie zostawioną flagą). Konta superadmin/admin NIGDY
nie logują się bez hasła — nawet w trybie testowym.

Po odzyskaniu dostępu WYŁĄCZ tryb testowy (to security event!):
    python enable_test_mode.py --off
albo w aplikacji: Ustawienia -> Tryb testowy.

Ścieżka bazy (kolejność wyboru):
    1. argument  --db <ścieżka>
    2. zmienna   $SZUP_DB_URL   (jeśli sqlite:///...)
    3. zmienna   $SZUP_DATA_DIR/szup.db
    4. domyślnie /opt/szup/data/szup.db  (typowo na serwerze)

Przykłady:
    python enable_test_mode.py                       # włącz (ścieżka z env / domyślna)
    python enable_test_mode.py --db /opt/szup/data/szup.db
    python enable_test_mode.py --unlock              # włącz + odblokuj wszystkie konta
    python enable_test_mode.py --off                 # wyłącz
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys


def resolve_db(explicit: str | None) -> str:
    if explicit:
        return explicit
    url = os.getenv("SZUP_DB_URL")
    if url and url.startswith("sqlite"):
        # sqlite:////opt/szup/data/szup.db  -> /opt/szup/data/szup.db
        # sqlite:///C:/tmp/szup.db          -> C:/tmp/szup.db
        return url.split("sqlite:///", 1)[-1]
    data_dir = os.getenv("SZUP_DATA_DIR", "/opt/szup/data")
    return os.path.join(data_dir, "szup.db")


def main() -> int:
    ap = argparse.ArgumentParser(description="Włącz/wyłącz tryb testowy SZUP (awaryjne odblokowanie).")
    ap.add_argument("--db", help="ścieżka do pliku szup.db")
    ap.add_argument("--off", action="store_true", help="wyłącz tryb testowy")
    ap.add_argument("--unlock", action="store_true",
                    help="dodatkowo odblokuj WSZYSTKIE konta (failed_login_count=0, locked_until=NULL)")
    args = ap.parse_args()

    db = resolve_db(args.db)
    if not os.path.exists(db):
        print(f"BŁĄD: nie znaleziono bazy: {db}", file=sys.stderr)
        print("Podaj ścieżkę jawnie:  python enable_test_mode.py --db /sciezka/do/szup.db", file=sys.stderr)
        return 1

    val = 0 if args.off else 1
    con = sqlite3.connect(db)
    try:
        cur = con.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='appsettings'")
        if not cur.fetchone():
            print("BŁĄD: w bazie nie ma tabeli 'appsettings'.", file=sys.stderr)
            print("Czy to na pewno baza SZUP i czy aplikacja choć raz się uruchomiła?", file=sys.stderr)
            return 2

        row = cur.execute("SELECT id FROM appsettings LIMIT 1").fetchone()
        if row:
            cur.execute("UPDATE appsettings SET test_mode=? WHERE id=?", (val, row[0]))
        else:
            cur.execute("INSERT INTO appsettings (test_mode) VALUES (?)", (val,))

        unlocked = 0
        if args.unlock:
            cur.execute("UPDATE \"user\" SET failed_login_count=0, locked_until=NULL")
            unlocked = cur.rowcount

        con.commit()

        print(f"OK: flaga trybu testowego {'WŁĄCZONA' if val else 'wyłączona'} w bazie  (baza: {db})")
        if args.unlock:
            print(f"OK: odblokowano {unlocked} kont (failed_login_count=0, locked_until=NULL)")

        if val:
            # Wymóg dwuskładnikowy (hardening): flaga w bazie ORAZ zmienna
            # środowiskowa SZUP_ALLOW_TEST_MODE na procesie backendu.
            env_ok = os.getenv("SZUP_ALLOW_TEST_MODE", "").strip().lower() in (
                "1", "true", "yes", "on")

            # Konta uprzywilejowane (superadmin/admin) NIE mogą logować się bez
            # hasła — nie wypisujemy ich jako „użyj tego loginu”.
            rows = cur.execute(
                'SELECT username, roles FROM "user" WHERE is_active=1 ORDER BY username'
            ).fetchall()
            usable = []
            for uname, roles_json in rows:
                roles = roles_json or ""
                if '"superadmin"' in roles or '"admin"' in roles:
                    continue
                usable.append(uname)

            print()
            if env_ok:
                print("Tryb testowy jest REALNIE AKTYWNY (flaga + SZUP_ALLOW_TEST_MODE) [OK]")
                print("Odswiez strone logowania - restart uslugi NIE jest potrzebny.")
            else:
                print("UWAGA: sama flaga NIE wystarcza. Brakuje zmiennej srodowiskowej")
                print("       SZUP_ALLOW_TEST_MODE na procesie backendu - logowanie bez")
                print("       hasla pozostaje ZABLOKOWANE.")
                print()
                print("  - lokalnie:  SZUP_ALLOW_TEST_MODE=1  przed startem uvicorn")
                print("  - systemd:   sudo systemctl edit szup  ->  [Service]")
                print("               Environment=SZUP_ALLOW_TEST_MODE=1")
                print("               sudo systemctl daemon-reload && sudo systemctl restart szup")

            if usable:
                print("\nLoginy, którymi zalogujesz się bez hasła (konta operacyjne):")
                for u in usable:
                    print(f"  - {u}")
            else:
                print("\nUWAGA: brak aktywnych kont operacyjnych (tylko admin/superadmin).")
                print("Te konta NIE logują się w trybie testowym — potrzebujesz konta")
                print("operacyjnego (manager / it_staff / pracownik komórki kadrowej)")
                print("albo zaloguj się superadminem HASŁEM.")

            print("\nPo odzyskaniu dostepu WYLACZ tryb testowy:")
            print("  python enable_test_mode.py --off        (lub Ustawienia -> Tryb testowy)")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
