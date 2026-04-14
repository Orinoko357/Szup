from __future__ import annotations
import logging
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def generate_numer(session: Session) -> str:
    """
    Generate next request number using SQLite exclusive lock pattern.
    Must be called within a transaction.
    """
    row = session.execute(
        text("SELECT * FROM konfiguracja_numeracji WHERE id=1")
    ).mappings().first()

    if not row:
        raise ValueError("Brak konfiguracji numeracji")

    cfg = dict(row)
    today = date.today()
    current_year = today.year
    current_month = today.month

    last_reset_str = cfg.get("ostatni_reset")
    if last_reset_str:
        try:
            if isinstance(last_reset_str, str):
                last_reset = date.fromisoformat(last_reset_str[:10])
            else:
                last_reset = last_reset_str
        except Exception:
            last_reset = date.min
    else:
        last_reset = date.min

    next_num = (cfg.get("ostatni_numer") or 0) + 1
    new_reset = last_reset_str

    if cfg.get("reset_co") == "ROK" and last_reset.year < current_year:
        next_num = 1
        new_reset = today.isoformat()
    elif cfg.get("reset_co") == "MIESIAC":
        if last_reset.year < current_year or (last_reset.year == current_year and last_reset.month < current_month):
            next_num = 1
            new_reset = today.isoformat()

    width = cfg.get("szerokosc_sekwencji") or 4
    seq = str(next_num).zfill(width)
    year = str(current_year)
    month = str(current_month).zfill(2)

    fmt = cfg.get("format_szablonu") or "{PREFIX}.{SEQ}.{ROK}"
    numer = fmt.replace("{PREFIX}", cfg.get("prefix") or "ZUP")
    numer = re.sub(r"\{SEQ:\d+\}", seq, numer)
    numer = numer.replace("{SEQ}", seq)
    numer = numer.replace("{SEQ_TENANT}", seq)
    numer = numer.replace("{ROK}", year).replace("{YEAR}", year)
    numer = numer.replace("{MONTH}", month)

    session.execute(
        text("UPDATE konfiguracja_numeracji SET ostatni_numer=:n, ostatni_reset=:r WHERE id=1"),
        {"n": next_num, "r": new_reset or today.isoformat()},
    )

    logger.info(f"Generated numer: {numer}")
    return numer
