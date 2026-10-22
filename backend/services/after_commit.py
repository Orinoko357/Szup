"""Powiadomienia wysyłane dopiero PO udanym commicie transakcji.

Silnik obiegu zleca e-maile w trakcie akcji (przed `session.commit()`). Gdyby
commit się nie udał (np. wyścig → IntegrityError → 409 i rollback), adresat
dostałby wiadomość o przejściu, które nie zostało zapisane. `defer()` odkłada
zadanie w `session.info`; po commicie uruchamiamy je w puli wątków w tle,
a rollback czyści kolejkę.

Pula jest ograniczona (`_MAX_WORKERS`) — przy masowych operacjach (np. import,
dużo wniosków naraz) nie odpalamy setek wątków SMTP jednocześnie, tylko
kolejkujemy zadania. Każde zadanie jest opakowane w try/except z
`logging.exception`, więc awaria wysyłki jest widoczna w logach, a nie ginie
po cichu w wątku.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event
from sqlalchemy.orm import Session as _OrmSession

_log = logging.getLogger("szup.after_commit")
_KEY = "after_commit_jobs"
_MAX_WORKERS = 4

_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="szup-notify")


def _safe_run(fn, kwargs: dict) -> None:
    """Uruchom zadanie; wyjątek tylko logujemy (z pełnym śladem)."""
    try:
        fn(**kwargs)
    except Exception:
        _log.exception("Zadanie po commicie (%s) zakończyło się błędem",
                       getattr(fn, "__name__", fn))


def _submit(fn, kwargs: dict) -> None:
    try:
        _executor.submit(_safe_run, fn, kwargs)
    except Exception:   # pragma: no cover — np. pula zamknięta przy wyłączaniu procesu
        _log.exception("Nie udało się zlecić zadania po commicie (%s)",
                       getattr(fn, "__name__", fn))


def defer(session, fn, **kwargs) -> None:
    """Uruchom `fn(**kwargs)` w tle po udanym commicie sesji (bez sesji — od razu)."""
    if session is None or getattr(session, "info", None) is None:
        _submit(fn, kwargs)
        return
    # Rollback sesji BEZ rozpoczętej transakcji nie wywołuje żadnego zdarzenia,
    # więc kolejka nie zostałaby wyczyszczona i odpaliłaby przy kolejnym
    # commicie. Rozpoczynamy transakcję jawnie (autobegin i tak by to zrobił).
    try:
        if not session.in_transaction():
            session.begin()
    except Exception:   # pragma: no cover — np. obiekt sesji innego typu
        pass
    session.info.setdefault(_KEY, []).append((fn, kwargs))


def pending_jobs(session) -> list:
    """Zadania czekające na commit (lista modyfikowalna — patrz `discard_jobs`)."""
    info = getattr(session, "info", None)
    if info is None:
        return []
    return info.setdefault(_KEY, [])


def discard_jobs(session, predicate) -> int:
    """Usuń z kolejki zadania, dla których `predicate(fn, kwargs)` zwraca True.

    Przydatne, gdy w tej samej transakcji krok zlecił powiadomienie, a potem
    obieg od razu poszedł dalej (np. automatyczny wybór uprawnień przez
    składającego) — wiadomość o kroku, który już się wykonał, nie ma sensu.
    Zwraca liczbę usuniętych zadań."""
    jobs = pending_jobs(session)
    keep = [(fn, kw) for fn, kw in jobs if not predicate(fn, kw)]
    removed = len(jobs) - len(keep)
    jobs[:] = keep
    return removed


@event.listens_for(_OrmSession, "after_commit")
def _run_jobs(session) -> None:
    jobs = session.info.pop(_KEY, [])
    for fn, kwargs in jobs:
        _submit(fn, kwargs)


# after_soft_rollback — odpala przy session.rollback() rozpoczętej transakcji
# (także zanim pobrano połączenie), w przeciwieństwie do after_rollback.
# Rollback bez transakcji nie odpala nic — dlatego `defer` ją rozpoczyna.
@event.listens_for(_OrmSession, "after_soft_rollback")
def _drop_jobs(session, previous_transaction) -> None:
    session.info.pop(_KEY, None)
