"""
Ręczne / zaplanowane wygenerowanie nocnej migawki uprawnień.

Użycie:
    python -m tools.snapshot            # migawka na dziś (idempotentnie)
    python -m tools.snapshot --force    # nadpisz dzisiejszą migawkę
    python -m tools.snapshot --date 2026-07-20 --force

Przeznaczone do cron / systemd timer jako niezależny od procesu backendu
mechanizm (obok wbudowanego harmonogramu — patrz services/scheduler.py).
Przykład systemd timer (OnCalendar=*-*-* 23:50):

    # /etc/systemd/system/szup-snapshot.service
    [Service]
    Type=oneshot
    WorkingDirectory=/opt/szup/backend
    Environment=SZUP_DATA_DIR=/opt/szup/data
    ExecStart=/opt/szup/venv/bin/python -m tools.snapshot

    # /etc/systemd/system/szup-snapshot.timer
    [Timer]
    OnCalendar=*-*-* 23:50
    Persistent=true
    [Install]
    WantedBy=timers.target
"""
from __future__ import annotations

import argparse
import sys

from sqlmodel import Session

from database import engine, init_db
from services.snapshots import create_snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description="Nocna migawka uprawnień SZUP")
    ap.add_argument("--date", help="Data migawki RRRR-MM-DD (domyślnie dziś)")
    ap.add_argument("--force", action="store_true",
                    help="Nadpisz istniejącą migawkę tego dnia")
    args = ap.parse_args()

    init_db()
    with Session(engine) as session:
        snap = create_snapshot(
            session, generated_by="cron", for_date=args.date, force=args.force)
    print(f"Migawka {snap.snapshot_date}: {snap.person_count} osób, "
          f"{snap.permission_count} pozycji, sha256={snap.content_sha256[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
