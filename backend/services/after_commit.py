"""Powiadomienia wysyłane dopiero PO udanym commicie transakcji.

Silnik obiegu zleca e-maile w trakcie akcji (przed `session.commit()`). Gdyby
commit się nie udał (np. wyścig → IntegrityError → 409 i rollback), adresat
dostałby wiadomość o przejściu, które nie zostało zapisane. `defer()` odkłada
zadanie w `session.info`; po commicie startujemy je w wątkach w tle, a rollback
czyści kolejkę.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import event
from sqlalchemy.orm import Session as _OrmSession

_log = logging.getLogger("szup.after_commit")
_KEY = "after_commit_jobs"


def defer(session, fn, **kwargs) -> None:
    """Uruchom `fn(**kwargs)` w tle po udanym commicie sesji (bez sesji — od razu)."""
    if session is None or getattr(session, "info", None) is None:
        threading.Thread(target=fn, daemon=True, kwargs=kwargs).start()
        return
    session.info.setdefault(_KEY, []).append((fn, kwargs))


@event.listens_for(_OrmSession, "after_commit")
def _run_jobs(session) -> None:
    jobs = session.info.pop(_KEY, [])
    for fn, kwargs in jobs:
        try:
            threading.Thread(target=fn, daemon=True, kwargs=kwargs).start()
        except Exception as exc:   # pragma: no cover — start wątku praktycznie nie zawodzi
            _log.warning("Nie udało się uruchomić powiadomienia: %s", exc)


# after_soft_rollback — odpala przy KAŻDYM session.rollback() (także gdy
# transakcja nie zdążyła się rozpocząć), w przeciwieństwie do after_rollback.
@event.listens_for(_OrmSession, "after_soft_rollback")
def _drop_jobs(session, previous_transaction) -> None:
    session.info.pop(_KEY, None)
