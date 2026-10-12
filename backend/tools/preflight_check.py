#!/usr/bin/env python3
"""Pre-flight przed wdrożeniem na ISTNIEJĄCĄ bazę SZUP.

Od tej wersji SZUP egzekwuje klucze obce (PRAGMA foreign_keys=ON). Jeśli w
bazie zostały osierocone rekordy z czasów, gdy FK NIE było egzekwowane
(np. wniosek wskazujący usuniętego użytkownika albo wydział bez istniejącej
jednostki), przyszłe operacje na tych rekordach mogą się nie powieść.

Ten skrypt NIE modyfikuje bazy — tylko raportuje. Uruchom go na kopii lub na
produkcyjnej bazie (odczyt) PRZED restartem usługi na nowym kodzie.

Kody wyjścia:
    0 — brak naruszeń, można wdrażać
    1 — wykryto osierocone rekordy (szczegóły wypisane) — najpierw posprzątaj
    2 — błąd (nie znaleziono bazy itp.)

Ścieżka bazy (kolejność wyboru):
    1. argument  --db <ścieżka>
    2. zmienna   $SZUP_DB_URL   (jeśli sqlite:///...)
    3. zmienna   $SZUP_DATA_DIR/szup.db
    4. domyślnie /opt/szup/data/szup.db

Przykłady:
    python tools/preflight_check.py --db /opt/szup/data/szup.db
    python tools/preflight_check.py           # ścieżka z env / domyślna
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys


def _resolve_db(cli_db: str | None) -> str | None:
    if cli_db:
        return cli_db
    url = os.getenv("SZUP_DB_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    data_dir = os.getenv("SZUP_DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "szup.db")
    return "/opt/szup/data/szup.db"


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-flight FK check dla SZUP")
    ap.add_argument("--db", help="ścieżka do pliku szup.db")
    args = ap.parse_args()

    db_path = _resolve_db(args.db)
    if not db_path or not os.path.exists(db_path):
        print(f"[BŁĄD] Nie znaleziono bazy: {db_path}", file=sys.stderr)
        print("Podaj ścieżkę jawnie:  python tools/preflight_check.py --db /sciezka/szup.db",
              file=sys.stderr)
        return 2

    print(f"Sprawdzam bazę: {db_path}")
    # Otwieramy w trybie tylko-do-odczytu (nie ruszamy danych).
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # foreign_key_check zwraca po jednym wierszu na KAŻDE naruszenie:
        #   (tabela_z_naruszeniem, rowid, tabela_wskazywana, indeks_FK)
        rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()

    if not rows:
        print("[OK] Brak osieroconych rekordów — baza gotowa do wdrożenia z FK=ON.")
        return 0

    # Grupujemy po (tabela → tabela wskazywana) dla czytelności.
    from collections import Counter
    summary: Counter = Counter()
    for tbl, rowid, ref, _fkid in rows:
        summary[(tbl, ref)] += 1

    print(f"[UWAGA] Wykryto {len(rows)} osieroconych powiązań:")
    for (tbl, ref), n in sorted(summary.items()):
        print(f"   • {tbl}: {n} rekord(ów) wskazuje na nieistniejący wpis w '{ref}'")

    print()
    print("Przykładowe rowid (do ręcznego przejrzenia/naprawy):")
    shown = 0
    for tbl, rowid, ref, _fkid in rows:
        print(f"   {tbl}.rowid={rowid}  ->  brak w {ref}")
        shown += 1
        if shown >= 20:
            print(f"   … i {len(rows) - shown} więcej")
            break

    print()
    print("Co dalej: przejrzyj powyższe rekordy. Zwykle wystarczy uzupełnić brakujące")
    print("powiązanie (np. przywrócić/wskazać kierownika wydziału) albo usunąć martwy")
    print("rekord. Po posprzątaniu uruchom skrypt ponownie — powinien zwrócić [OK].")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
