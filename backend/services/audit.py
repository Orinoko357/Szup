"""
Audit logging — append-only, 24-month retention (NIS2/KSC).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlmodel import Session

from models import AuditLog

_log = logging.getLogger("szup.audit")


def record_event(
    session: Session,
    *,
    action: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> None:
    try:
        entry = AuditLog(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            method=method,
            path=path,
            status_code=status_code,
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
        )
        session.add(entry)
        if commit:
            session.commit()
    except Exception as exc:
        _log.warning("Failed to write AuditLog (action=%s): %s", action, exc)


def record_event_standalone(**kwargs) -> None:
    from database import engine as db_engine
    try:
        with Session(db_engine) as s:
            record_event(s, commit=True, **kwargs)
    except Exception as exc:
        _log.warning("Audit standalone write failed: %s", exc)


# Jedyne zaufane proxy: Apache na tym samym hoście (backend słucha na 127.0.0.1).
_TRUSTED_PROXIES = {"127.0.0.1", "::1"}


def client_ip(request) -> Optional[str]:
    """Adres IP klienta — wspólny dla audytu, middleware i limitu logowań.

    X-Forwarded-For uwzględniamy WYŁĄCZNIE, gdy połączenie przyszło od zaufanego
    proxy (localhost). Apache DOPISUJE prawdziwy adres klienta NA KOŃCU nagłówka,
    więc bierzemy OSTATNI element — wcześniejsze może podać sam klient
    (podszycie pod inny adres, obejście limitu prób logowania).

    Klient może też wysłać WŁASNY, osobny nagłówek X-Forwarded-For — wtedy
    żądanie ma ich kilka, a `headers.get()` zwróciłby tylko pierwszy (podany
    przez klienta). Dlatego łączymy wszystkie wystąpienia w kolejności
    otrzymania i dopiero z całości bierzemy ostatni element.
    """
    if request is None:
        return None
    peer = request.client.host if getattr(request, "client", None) else None
    if peer in _TRUSTED_PROXIES:
        headers = request.headers
        if hasattr(headers, "getlist"):
            values = headers.getlist("x-forwarded-for")
        else:
            one = headers.get("x-forwarded-for")
            values = [one] if one else []
        xff = ",".join(v for v in values if v)
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return peer


def request_meta(request: Request) -> dict[str, Optional[str]]:
    if request is None:
        return {"ip": None, "user_agent": None}
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}


# ---------------------------------------------------------------------------
# Potwierdzenie hasłem operacji superadmina (czyszczenie dzienników, usuwanie
# komórek) — ten sam wzorzec co reset fabryczny w routers/settings.py.
# ---------------------------------------------------------------------------

# Limit nieudanych potwierdzeń — per konto, w pamięci procesu (jeden worker
# uvicorn). Chroni przed zgadywaniem hasła z przejętej sesji superadmina;
# restart usługi zeruje licznik.
CONFIRM_MAX_FAILURES = 5
CONFIRM_WINDOW_MINUTES = 15
_confirm_failures: dict[int, list[datetime]] = {}


def _recent_confirm_failures(user_id: int) -> list[datetime]:
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=CONFIRM_WINDOW_MINUTES)
    hits = [t for t in _confirm_failures.get(user_id, []) if t > cutoff]
    if hits:
        _confirm_failures[user_id] = hits
    else:
        _confirm_failures.pop(user_id, None)
    return hits


def confirm_password(session: Session, user, password: str, *,
                     operation: str, ip: Optional[str] = None) -> None:
    """Weryfikuje hasło wykonującego (lokalne albo bind do AD) przed operacją
    nieodwracalną. Po CONFIRM_MAX_FAILURES nieudanych próbach w oknie
    CONFIRM_WINDOW_MINUTES minut → 429. Nieudana próba = zdarzenie
    bezpieczeństwa (high; critical przy blokadzie). Rzuca HTTPException."""
    from fastapi import HTTPException
    from sqlmodel import select
    from models import AuthType, LdapSettings, SecuritySeverity
    from services.auth_service import verify_password
    from services.security_events import emit as emit_security_event

    if len(_recent_confirm_failures(user.id)) >= CONFIRM_MAX_FAILURES:
        raise HTTPException(429,
            "Zbyt wiele nieudanych prób potwierdzenia hasłem. "
            f"Spróbuj ponownie za {CONFIRM_WINDOW_MINUTES} minut.")

    ok = False
    if password:
        if user.auth_type == AuthType.ldap:
            from services.ldap_service import authenticate_ldap
            cfg = session.exec(select(LdapSettings)).first()
            if cfg and cfg.enabled:
                try:
                    ok = bool(authenticate_ldap(cfg, user.username, password))
                except Exception:
                    ok = False
        else:
            ok = bool(user.password_hash) and verify_password(password, user.password_hash)
    if ok:
        _confirm_failures.pop(user.id, None)
        return

    failures = _confirm_failures.setdefault(user.id, [])
    failures.append(datetime.utcnow())
    blocked = len(failures) >= CONFIRM_MAX_FAILURES
    emit_security_event(
        session, event_type="superadmin.confirm_denied", source="audit",
        severity=SecuritySeverity.critical if blocked else SecuritySeverity.high,
        summary=(f"Nieudane potwierdzenie hasłem ({operation}) przez {user.username}"
                 + (f" — próby zablokowane na {CONFIRM_WINDOW_MINUTES} minut"
                    if blocked else "")),
        details={"operation": operation, "failures_in_window": len(failures)},
        user_id=user.id, ip=ip,
    )
    raise HTTPException(403, "Nieprawidłowe hasło — operacja przerwana")


# ---------------------------------------------------------------------------
# Czyszczenie dzienników (audit log, zdarzenia bezpieczeństwa) — superadmin
# ---------------------------------------------------------------------------

# Ślady czyszczenia nie podlegają usunięciu — żadne czyszczenie ich nie obejmie.
PURGE_TRACE_ACTIONS = ("audit.purged", "security.purged")


class PurgeError(RuntimeError):
    """Czyszczenie wycofane — w bazie nic się nie zmieniło."""


def table_triggers(conn, table: str) -> dict[str, str]:
    """{nazwa: SQL} triggerów założonych na tabeli `table` (połączenie DBAPI)."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (table,)).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def purge_log_table(table: str, *, time_column: str, key_column: str,
                    protected: tuple[str, ...], cutoff: Optional[datetime]) -> int:
    """Usuwa wpisy z tabeli dziennika — atomowo, na JEDNYM połączeniu.

    W jednej transakcji (BEGIN IMMEDIATE): zdjęcie triggerów append-only,
    DELETE (z pominięciem wpisów, których `key_column` jest w `protected`,
    i — gdy `cutoff` — tylko starszych niż `cutoff`), ponowne założenie
    triggerów, COMMIT. DDL w SQLite podlega transakcji, więc błąd na
    dowolnym etapie wycofuje WSZYSTKO, łącznie ze zdjęciem triggerów; mimo to
    po wycofaniu dodatkowo odtwarzamy ochronę auditlog. Zwraca liczbę
    usuniętych wierszy; przy błędzie rzuca PurgeError.
    """
    from database import engine as db_engine, _install_auditlog_triggers

    where = [f'COALESCE("{key_column}", \'\') NOT IN ({", ".join("?" for _ in protected)})']
    params: list[Any] = list(protected)
    if cutoff is not None:
        where.append(f'"{time_column}" < ?')
        params.append(cutoff.strftime("%Y-%m-%d %H:%M:%S.%f"))
    sql = f'DELETE FROM "{table}" WHERE ' + " AND ".join(where)

    raw = db_engine.raw_connection()
    dbapi = raw.driver_connection
    prev_isolation = dbapi.isolation_level
    triggers: dict[str, str] = {}
    try:
        # Ręczne sterowanie transakcją: moduł sqlite3 nie otworzy (ani nie
        # zatwierdzi) niczego za nas pomiędzy DDL a DML.
        dbapi.isolation_level = None
        cur = dbapi.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            triggers = table_triggers(cur, table)
            for name in triggers:
                cur.execute(f'DROP TRIGGER IF EXISTS "{name}"')
            cur.execute(sql, params)
            deleted = cur.rowcount if cur.rowcount is not None else 0
            for name, trg_sql in triggers.items():
                cur.execute(trg_sql)
            missing = set(triggers) - set(table_triggers(cur, table))
            if missing:
                raise PurgeError(f"triggery nie zostały odtworzone: {sorted(missing)}")
            cur.execute("COMMIT")
            return int(deleted)
        except Exception as exc:
            try:
                cur.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            _log.error("Czyszczenie %s wycofane: %s", table, exc)
            raise PurgeError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        dbapi.isolation_level = prev_isolation
        raw.close()
        if table == "auditlog":
            # Asekuracja: ochrona dziennika ma istnieć niezależnie od wyniku.
            try:
                _install_auditlog_triggers()
            except Exception as exc:  # noqa: BLE001
                _log.error("Nie odtworzono triggerów auditlog po czyszczeniu: %s", exc)


def missing_log_triggers(table: str) -> list[str]:
    """Triggery append-only, których brakuje na tabeli dziennika (pusta = OK)."""
    from database import engine as db_engine, AUDITLOG_TRIGGERS
    expected = set(AUDITLOG_TRIGGERS) if table == "auditlog" else set()
    if not expected:
        return []
    raw = db_engine.raw_connection()
    try:
        present = set(table_triggers(raw.driver_connection, table))
    finally:
        raw.close()
    return sorted(expected - present)


PURGE_MODES = ("before", "all")
PURGE_REASON_MIN = 10

# Dziennik → (tabela, kolumna czasu, kolumna klucza, akcja śladu, nazwa do komunikatów)
_PURGE_TARGETS = {
    "audit":    ("auditlog", "timestamp", "action", "audit.purged", "dziennika zdarzeń"),
    "security": ("securityevent", "created_at", "event_type", "security.purged",
                 "zdarzeń bezpieczeństwa"),
}


def parse_purge_cutoff(mode: str, before: Optional[str]) -> Optional[datetime]:
    """Walidacja trybu czyszczenia → granica czasu (naiwny UTC) albo None (wszystko)."""
    from datetime import timezone
    from fastapi import HTTPException
    if mode not in PURGE_MODES:
        raise HTTPException(400, "Nieznany tryb czyszczenia — dozwolone: before, all")
    if mode == "all":
        return None
    raw = (before or "").strip()
    if not raw:
        raise HTTPException(400, "Podaj datę, przed którą wpisy mają zostać usunięte")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Nieprawidłowa data — użyj formatu RRRR-MM-DD")
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def run_log_purge(session: Session, request, user, *, log: str, password: str,
                  reason: str, mode: str, before: Optional[str]) -> dict:
    """Czyszczenie dziennika przez superadmina (POST /api/audit/purge,
    POST /api/security/purge). Kolejność: walidacja → hasło → atomowe
    usunięcie → kontrola triggerów → ślad (audit + zdarzenie critical).
    Wpisy śladu czyszczenia (PURGE_TRACE_ACTIONS) nigdy nie są usuwane."""
    from fastapi import HTTPException
    from models import SecuritySeverity
    from services.security_events import emit as emit_security_event

    table, time_col, key_col, trace_action, label = _PURGE_TARGETS[log]
    reason = (reason or "").strip()
    if len(reason) < PURGE_REASON_MIN:
        raise HTTPException(400,
            f"Podaj powód czyszczenia (co najmniej {PURGE_REASON_MIN} znaków)")
    cutoff = parse_purge_cutoff(mode, before)
    meta = request_meta(request)
    confirm_password(session, user, password,
                     operation=f"czyszczenie {label}", ip=meta["ip"])
    # Transakcja czyszczenia idzie osobnym połączeniem z BEGIN IMMEDIATE —
    # sesja żądania nie może trzymać otwartej transakcji zapisu.
    session.commit()

    try:
        deleted = purge_log_table(table, time_column=time_col, key_column=key_col,
                                  protected=PURGE_TRACE_ACTIONS, cutoff=cutoff)
    except PurgeError as exc:
        missing = missing_log_triggers(table)
        emit_security_event(
            session, event_type=f"{log}.purge_failed", source=log,
            severity=SecuritySeverity.critical if missing else SecuritySeverity.high,
            summary=(f"Nieudane czyszczenie {label} przez {user.username} — "
                     "zmiany wycofane"
                     + (" — BRAK OCHRONY APPEND-ONLY" if missing else "")),
            details={"error": str(exc), "missing_triggers": missing},
            user_id=user.id, ip=meta["ip"],
        )
        raise HTTPException(500,
            f"Czyszczenie {label} nie powiodło się — zmiany wycofane, "
            "żadne wpisy nie zostały usunięte.")

    details = {"reason": reason, "mode": mode,
               "before": cutoff.isoformat() if cutoff else None, "deleted": deleted}
    record_event(session, action=trace_action, user_id=user.id, username=user.username,
                 target_type=table, ip=meta["ip"], user_agent=meta["user_agent"],
                 details=details)
    emit_security_event(
        session, event_type=trace_action, source=log, severity=SecuritySeverity.critical,
        summary=(f"Wyczyszczono {label} ({deleted} wpisów) przez {user.username}: "
                 f"{reason}"),
        details=details, user_id=user.id, ip=meta["ip"],
    )
    missing = missing_log_triggers(table)
    if missing:
        _log.error("Po czyszczeniu %s brak triggerów append-only: %s", table, missing)
        emit_security_event(
            session, event_type="audit.triggers_missing", source=log,
            severity=SecuritySeverity.critical,
            summary=f"Dziennik zdarzeń bez ochrony append-only po czyszczeniu {label}",
            details={"missing_triggers": missing}, user_id=user.id, ip=meta["ip"],
        )
    return {"deleted": deleted}
