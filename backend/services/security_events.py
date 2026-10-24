"""
Security events — tracked until resolved.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlmodel import Session

from models import SecurityEvent, SecuritySeverity

_log = logging.getLogger("szup.security")


# ---------------------------------------------------------------------------
# Polskie teksty zdarzeń (3.11): nazwy ról i działań, odmiana liczebników,
# daty w czasie lokalnym — opisy zdarzeń czyta człowiek, nie parser.
# ---------------------------------------------------------------------------

# Te same nazwy co we froncie (frontend/src/labels.js, ROLE_META).
ROLE_LABELS = {
    "superadmin": "superadmin",
    "admin": "administrator",
    "it_staff": "IT",
    "manager": "kierownik",
    "hr": "kadry",
    "viewer": "przeglądający",
}

# Działania w strukturze (`routers.units._audit_post_change`).
POST_ACTION_LABELS = {
    "unit.manager_changed": "dyrektor jednostki",
    "department.manager_changed": "kierownik komórki",
    "department.deputy_added": "zastępca kierownika komórki",
    "department.deputy_removed": "zastępca kierownika komórki (usunięty)",
}


def role_labels(roles) -> list[str]:
    """Polskie nazwy ról (nieznane — bez zmian)."""
    return [ROLE_LABELS.get(r, r) for r in roles]


def plural(n: int, one: str, few: str, many: str) -> str:
    """Odmiana rzeczownika po liczebniku: 1 wpis, 2–4 wpisy, 5 wpisów
    (12–14 → many, 22–24 → few)."""
    n = abs(int(n))
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def local_date(value) -> str:
    """Data (naiwny UTC albo ze strefą) jako DD.MM.RRRR w czasie polskim."""
    from datetime import datetime, timezone
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:10]
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        value = value.astimezone(ZoneInfo("Europe/Warsaw"))
    except Exception:  # noqa: BLE001 — brak bazy stref (tzdata)
        pass
    return value.strftime("%d.%m.%Y")


def emit(
    session: Session,
    *,
    event_type: str,
    summary: str,
    severity: SecuritySeverity = SecuritySeverity.medium,
    source: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    user_id: Optional[int] = None,
    ip: Optional[str] = None,
    commit: bool = True,
) -> None:
    try:
        ev = SecurityEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            summary=summary[:512],
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
            user_id=user_id,
            ip=ip,
        )
        session.add(ev)
        if commit:
            session.commit()
    except Exception as exc:
        _log.warning("SecurityEvent emit failed (%s): %s", event_type, exc)



