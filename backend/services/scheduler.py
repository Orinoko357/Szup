"""
Prosty harmonogram w procesie — nocna migawka uprawnień (domyślnie 23:50 lokalnie).

Świadomie bez zewnętrznych zależności (APScheduler/Celery): jeden wątek w tle
liczy czas do najbliższej pory i budzi się, żeby wykonać migawkę. Uruchamiany
z `main.py` (lifespan). Idempotencja po stronie `create_snapshot` (jedna migawka
na dzień), więc restart backendu w środku dnia niczego nie dubluje.

Porę (godzina:minuta) oraz włącznik czyta z bazy (`AppSettings`), więc superadmin
zmienia je w Ustawieniach BEZ restartu — endpoint woła `reconfigure()`, a wątek
przelicza najbliższy termin. Zmienna środowiskowa `SZUP_SNAPSHOTS=0` to twardy
wyłącznik nadrzędny (wtedy wątek w ogóle nie startuje).

Alternatywa produkcyjna (odporność na awarię procesu): systemd timer / cron
wołający `python -m tools.snapshot` — patrz `tools/snapshot.py`. Oba mechanizmy
mogą działać równolegle (idempotencja).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

_log = logging.getLogger("szup.scheduler")

DEFAULT_HOUR = 23
DEFAULT_MINUTE = 50

_stop = threading.Event()
_wake = threading.Event()          # ustawiany przy zmianie konfiguracji / stopie
_thread: "threading.Thread | None" = None


def _read_schedule() -> tuple[bool, int, int]:
    """(enabled, hour, minute) z AppSettings; wartości domyślne, gdy brak/niepełne."""
    try:
        from sqlmodel import Session, select
        from database import engine
        from models import AppSettings
        with Session(engine) as s:
            cfg = s.exec(select(AppSettings)).first()
        if not cfg:
            return True, DEFAULT_HOUR, DEFAULT_MINUTE
        hour = cfg.snapshot_hour if cfg.snapshot_hour is not None else DEFAULT_HOUR
        minute = cfg.snapshot_minute if cfg.snapshot_minute is not None else DEFAULT_MINUTE
        hour = min(23, max(0, int(hour)))
        minute = min(59, max(0, int(minute)))
        enabled = bool(cfg.snapshot_enabled) if cfg.snapshot_enabled is not None else True
        return enabled, hour, minute
    except Exception:
        return True, DEFAULT_HOUR, DEFAULT_MINUTE


def _seconds_until_next_run(now: datetime, hour: int, minute: int) -> float:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_once() -> None:
    from sqlmodel import Session
    from database import engine
    from services.snapshots import create_snapshot
    try:
        with Session(engine) as session:
            create_snapshot(session, generated_by="system")
    except Exception:
        _log.exception("Nocna migawka uprawnień nie powiodła się")


def _loop() -> None:
    _log.info("Harmonogram migawek: start")
    while not _stop.is_set():
        enabled, hour, minute = _read_schedule()
        _wake.clear()

        if not enabled:
            # Wyłączony w Ustawieniach — czekaj na zmianę konfiguracji lub stop.
            _wake.wait()
            continue

        delay = _seconds_until_next_run(datetime.now(), hour, minute)
        # Czekamy do terminu; obudzenie (`_wake`) = zmiana konfiguracji → przelicz.
        woken = _wake.wait(delay)
        if _stop.is_set():
            break
        if not woken:
            _run_once()   # minął zaplanowany czas


def start() -> None:
    """Wystartuj wątek harmonogramu (no-op, gdy wyłączony env-em lub już działa)."""
    global _thread
    if os.getenv("SZUP_SNAPSHOTS", "1") == "0":
        _log.info("Harmonogram migawek wyłączony (SZUP_SNAPSHOTS=0)")
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear(); _wake.clear()
    _thread = threading.Thread(target=_loop, name="szup-snapshots", daemon=True)
    _thread.start()


def reconfigure() -> None:
    """Wybudź wątek, żeby wczytał nowy harmonogram z bazy (bez restartu)."""
    _wake.set()


def stop() -> None:
    _stop.set()
    _wake.set()
