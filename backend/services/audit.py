"""
Audit logging — append-only, retencja co najmniej 24 miesiące (NIS2/KSC).

Dziennik zdarzeń (auditlog) jest append-only (triggery). Wyjątek: czyszczenie
przez superadmina (`run_log_purge`) — wyłącznie wpisów starszych niż
RETENTION_MONTHS miesięcy, z hasłem i powodem, ze śladem zapisanym w tej samej
transakcji. Ślady czyszczeń i resetu fabrycznego są nieusuwalne.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

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
# komórek i posiadanych grup, reset fabryczny).
# ---------------------------------------------------------------------------

def verify_user_password(session: Session, user, password: str) -> bool:
    """Czy `password` jest hasłem konta: lokalnym (bcrypt) albo w AD (bind).
    Błąd połączenia z AD = brak potwierdzenia (zapisany w logu)."""
    from sqlmodel import select
    from models import AuthType, LdapSettings
    from services.auth_service import verify_password
    if not password:
        return False
    if user.auth_type == AuthType.ldap:
        from services.ldap_service import authenticate_ldap
        cfg = session.exec(select(LdapSettings)).first()
        if not cfg or not cfg.enabled:
            return False
        try:
            return bool(authenticate_ldap(cfg, user.username, password))
        except Exception as exc:  # noqa: BLE001
            _log.warning("Potwierdzenie hasłem w AD nieudane (%s): %s", user.username, exc)
            return False
    return bool(user.password_hash) and verify_password(password, user.password_hash)


def confirm_password(session: Session, user, password: str, *,
                     operation: str, ip: Optional[str] = None,
                     event_type: str = "superadmin.confirm_denied",
                     source: str = "audit",
                     denied_detail: str = "Nieprawidłowe hasło — operacja przerwana") -> None:
    """Weryfikuje hasło wykonującego (lokalne albo bind do AD) przed operacją
    nieodwracalną. Korzysta ze WSPÓLNEGO, trwałego licznika prób konta
    (`services.auth_service`, ten sam co zmiana hasła): po
    CONFIRM_MAX_FAILURES nieudanych próbach w oknie → 429. Nieudana próba =
    zdarzenie bezpieczeństwa high (critical przy blokadzie) i 403."""
    from fastapi import HTTPException
    from services.auth_service import verify_password_with_limit

    # Próba jest rezerwowana atomowo PRZED sprawdzeniem hasła (3.11, N7) —
    # równoległe żądania nie przekroczą limitu.
    if verify_password_with_limit(
            session, user, password, operation=operation, ip=ip,
            event_type=event_type, source=source,
            verify=lambda: verify_user_password(session, user, password)):
        return
    raise HTTPException(403, denied_detail)


# ---------------------------------------------------------------------------
# Czyszczenie dzienników (audit log, zdarzenia bezpieczeństwa) — superadmin
# ---------------------------------------------------------------------------

# Ślady czyszczeń dzienników — nieusuwalne. Żadne czyszczenie (ani reset
# fabryczny) ich nie obejmuje, a w securityevent chronią je dodatkowo triggery
# (`database.SECURITYEVENT_TRIGGERS`; auditlog jest w całości append-only).
PURGE_TRACE_ACTIONS = ("audit.purged", "security.purged", "settings.factory_reset")

# Minimalna retencja dzienników (NIS2/KSC): czyścić wolno wyłącznie wpisy
# starsze niż RETENTION_MONTHS miesięcy.
RETENTION_MONTHS = 24

# Data „przed” bez strefy (np. RRRR-MM-DD z formularza) to północ czasu polskiego.
_LOCAL_TZ_NAME = "Europe/Warsaw"


class PurgeError(RuntimeError):
    """Czyszczenie wycofane — w bazie nic się nie zmieniło."""


def table_triggers(conn, table: str) -> dict[str, str]:
    """{nazwa: SQL} triggerów założonych na tabeli `table` (połączenie DBAPI)."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (table,)).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def _db_time(value: datetime) -> str:
    """Format daty, w jakim SQLAlchemy zapisuje DateTime w SQLite."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def purge_log_table(table: str, *, time_column: str, key_column: str,
                    protected: tuple[str, ...], cutoff: Optional[datetime],
                    trace: Optional[Callable[[Any, int, dict[str, int]], None]] = None) -> int:
    """Usuwa wpisy z tabeli dziennika — atomowo, na JEDNYM połączeniu.

    W jednej transakcji (BEGIN IMMEDIATE): zdjęcie triggerów append-only,
    DELETE (z pominięciem wpisów, których `key_column` jest w `protected`,
    i — gdy `cutoff` — tylko starszych niż `cutoff`), ponowne założenie
    triggerów, zapis śladu (`trace(kursor, usunięte, {typ: liczba})`), COMMIT.
    DDL w SQLite podlega transakcji, więc błąd na dowolnym etapie — także przy
    zapisie śladu — wycofuje WSZYSTKO: nie ma czyszczenia bez śladu. Po
    wycofaniu dodatkowo odtwarzamy triggery. Zwraca liczbę usuniętych
    wierszy; przy błędzie rzuca PurgeError.
    """
    from database import engine as db_engine, _install_auditlog_triggers

    where = [f'COALESCE("{key_column}", \'\') NOT IN ({", ".join("?" for _ in protected)})']
    params: list[Any] = list(protected)
    if cutoff is not None:
        where.append(f'"{time_column}" < ?')
        params.append(_db_time(cutoff))
    where_sql = " AND ".join(where)

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
            # Co usuwamy — liczba wpisów każdego typu trafia do śladu.
            by_type = {str(k or ""): int(n) for k, n in cur.execute(
                f'SELECT "{key_column}", COUNT(*) FROM "{table}" WHERE {where_sql} '
                f'GROUP BY "{key_column}"', params).fetchall()}
            for name in triggers:
                cur.execute(f'DROP TRIGGER IF EXISTS "{name}"')
            cur.execute(f'DELETE FROM "{table}" WHERE {where_sql}', params)
            deleted = cur.rowcount if cur.rowcount is not None else 0
            for name, trg_sql in triggers.items():
                cur.execute(trg_sql)
            missing = set(triggers) - set(table_triggers(cur, table))
            if missing:
                raise PurgeError(f"triggery nie zostały odtworzone: {sorted(missing)}")
            if trace is not None:
                trace(cur, int(deleted), by_type)
            cur.execute("COMMIT")
            return int(deleted)
        except Exception as exc:
            try:
                cur.execute("ROLLBACK")
            except Exception as rb_exc:  # noqa: BLE001
                _log.error("ROLLBACK czyszczenia %s nieudany: %s", table, rb_exc)
            _log.error("Czyszczenie %s wycofane: %s", table, exc)
            raise PurgeError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        dbapi.isolation_level = prev_isolation
        raw.close()
        # Asekuracja: ochrona dzienników ma istnieć niezależnie od wyniku.
        try:
            _install_auditlog_triggers()
        except Exception as exc:  # noqa: BLE001
            _log.error("Nie odtworzono triggerów append-only po czyszczeniu %s: %s",
                       table, exc)


def missing_log_triggers(table: str) -> list[str]:
    """Triggery append-only, których brakuje na tabeli dziennika (pusta = OK)."""
    from database import engine as db_engine, AUDITLOG_TRIGGERS, SECURITYEVENT_TRIGGERS
    expected = {"auditlog": set(AUDITLOG_TRIGGERS),
                "securityevent": set(SECURITYEVENT_TRIGGERS)}.get(table, set())
    if not expected:
        return []
    raw = db_engine.raw_connection()
    try:
        present = set(table_triggers(raw.driver_connection, table))
    finally:
        raw.close()
    return sorted(expected - present)


PURGE_MODES = ("before",)
PURGE_REASON_MIN = 10

# Dziennik → (tabela, kolumna czasu, kolumna klucza, akcja śladu, nazwa do komunikatów)
_PURGE_TARGETS = {
    "audit":    ("auditlog", "timestamp", "action", "audit.purged", "dziennika zdarzeń"),
    "security": ("securityevent", "created_at", "event_type", "security.purged",
                 "zdarzeń bezpieczeństwa"),
}


# Nazwa dziennika w bierniku — „Wyczyszczono dziennik zdarzeń”.
_PURGE_LABEL_ACC = {"audit": "dziennik zdarzeń", "security": "dziennik zdarzeń bezpieczeństwa"}


def _local_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_LOCAL_TZ_NAME)
    except Exception as exc:  # noqa: BLE001 — brak bazy stref (tzdata)
        _log.warning("Brak strefy %s (%s) — daty czyszczenia liczone w UTC",
                     _LOCAL_TZ_NAME, exc)
        from datetime import timezone
        return timezone.utc


def retention_limit(now: Optional[datetime] = None) -> datetime:
    """Najpóźniejsza dopuszczalna granica czyszczenia (naiwny UTC): teraz minus
    RETENTION_MONTHS miesięcy (29 lutego → 28 lutego)."""
    now = now or datetime.utcnow()
    month_index = now.year * 12 + (now.month - 1) - RETENTION_MONTHS
    year, month = divmod(month_index, 12)
    month += 1
    import calendar
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def parse_purge_cutoff(mode: Optional[str], before: Optional[str]) -> datetime:
    """Walidacja czyszczenia → granica czasu (naiwny UTC).

    Czyścić można wyłącznie wpisy starsze niż RETENTION_MONTHS miesięcy —
    trybu „wszystko” nie ma (od 3.10). Data bez strefy (RRRR-MM-DD) oznacza
    północ czasu polskiego."""
    from datetime import timezone
    from fastapi import HTTPException
    mode = (mode or "before").strip()
    if mode == "all":
        raise HTTPException(400,
            f"Czyszczenie całego dziennika nie jest dostępne — wpisy z ostatnich "
            f"{RETENTION_MONTHS} miesięcy podlegają obowiązkowej retencji. "
            "Podaj datę, przed którą wpisy mają zostać usunięte.")
    if mode not in PURGE_MODES:
        raise HTTPException(400, "Nieznany tryb czyszczenia — dozwolony tryb: before")
    raw = (before or "").strip()
    if not raw:
        raise HTTPException(400, "Podaj datę, przed którą wpisy mają zostać usunięte")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Nieprawidłowa data — użyj formatu RRRR-MM-DD")
    if value.tzinfo is None:
        value = value.replace(tzinfo=_local_tz())
    value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value > datetime.utcnow():
        raise HTTPException(400, "Data czyszczenia nie może być z przyszłości")
    limit = retention_limit()
    if value > limit:
        latest = limit.replace(tzinfo=timezone.utc).astimezone(_local_tz()).date()
        raise HTTPException(400,
            f"Dzienniki przechowujemy co najmniej {RETENTION_MONTHS} miesiące — "
            f"można usunąć tylko wpisy sprzed {latest.isoformat()} "
            "(podaj tę datę lub wcześniejszą).")
    return value


def _purge_trace_writer(*, table: str, log: str, trace_action: str, label: str,
                        user, meta: dict, details: dict
                        ) -> Callable[[Any, int, dict[str, int]], None]:
    """Zapis śladu czyszczenia (wpis audytu + zdarzenie critical) surowym SQL
    na kursorze transakcji czyszczenia — w tej samej transakcji co DELETE."""
    def write(cur, deleted: int, by_type: dict[str, int]) -> None:
        now = _db_time(datetime.utcnow())
        full = {**details, "deleted": deleted, "deleted_by_type": by_type}
        payload = json.dumps(full, ensure_ascii=False, default=str)
        cur.execute(
            'INSERT INTO "auditlog" (timestamp, user_id, username, action, target_type, '
            'ip, user_agent, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (now, user.id, user.username, trace_action, table, meta.get("ip"),
             (meta.get("user_agent") or "")[:512] or None, payload))
        from services.security_events import local_date, plural
        summary = (f"Wyczyszczono {_PURGE_LABEL_ACC.get(log, label)} ({deleted} "
                   f"{plural(deleted, 'wpis', 'wpisy', 'wpisów')} sprzed "
                   f"{local_date(details.get('before'))}) przez {user.username}: "
                   f"{details.get('reason')}")[:512]
        cur.execute(
            'INSERT INTO "securityevent" (created_at, event_type, severity, source, '
            'summary, details, user_id, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (now, trace_action, "critical", log, summary, payload, user.id, meta.get("ip")))
    return write


def run_log_purge(session: Session, request, user, *, log: str, password: str,
                  reason: str, mode: Optional[str], before: Optional[str]) -> dict:
    """Czyszczenie dziennika przez superadmina (POST /api/audit/purge,
    POST /api/security/purge). Kolejność: walidacja (powód, data zgodna
    z retencją) → hasło → atomowe usunięcie RAZEM ze śladem (wpis audytu
    + zdarzenie critical w tej samej transakcji) → kontrola triggerów.
    Wpisy śladów (PURGE_TRACE_ACTIONS) nigdy nie są usuwane."""
    from fastapi import HTTPException
    from models import SecuritySeverity
    from services.security_events import emit as emit_security_event

    table, time_col, key_col, trace_action, label = _PURGE_TARGETS[log]
    reason = (reason or "").strip()
    if len(reason) < PURGE_REASON_MIN:
        raise HTTPException(400,
            f"Podaj powód czyszczenia (co najmniej {PURGE_REASON_MIN} znaków)")
    if len(reason) > 1000:
        raise HTTPException(400, "Powód czyszczenia może mieć najwyżej 1000 znaków")
    cutoff = parse_purge_cutoff(mode, before)
    meta = request_meta(request)
    confirm_password(session, user, password,
                     operation=f"czyszczenie {label}", ip=meta["ip"])
    # Transakcja czyszczenia idzie osobnym połączeniem z BEGIN IMMEDIATE —
    # sesja żądania nie może trzymać otwartej transakcji zapisu.
    session.commit()

    details = {"reason": reason, "mode": "before", "before": cutoff.isoformat(),
               "retention_months": RETENTION_MONTHS}
    try:
        deleted = purge_log_table(
            table, time_column=time_col, key_column=key_col,
            protected=PURGE_TRACE_ACTIONS, cutoff=cutoff,
            trace=_purge_trace_writer(table=table, log=log, trace_action=trace_action,
                                      label=label, user=user, meta=meta,
                                      details=details))
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

    missing = missing_log_triggers(table)
    if missing:
        _log.error("Po czyszczeniu %s brak triggerów append-only: %s", table, missing)
        emit_security_event(
            session, event_type="audit.triggers_missing", source=log,
            severity=SecuritySeverity.critical,
            summary=f"Dziennik zdarzeń bez ochrony append-only po czyszczeniu {label}",
            details={"missing_triggers": missing}, user_id=user.id, ip=meta["ip"],
        )
    return {"deleted": deleted, "before": cutoff.isoformat()}
