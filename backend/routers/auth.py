"""
Router: Auth — setup, local login, LDAP login, logout, password change.
"""
from __future__ import annotations

import logging
import os
import secrets as _secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import User, AuthType, AppSettings, LdapSettings, SecuritySeverity, parse_roles, roles_to_json, primary_role
from services.audit import record_event, request_meta
from services.security_events import emit as emit_security_event
from services.auth_service import (
    hash_password, verify_password, create_access_token, get_current_user,
    validate_password_strength, is_password_expired, revoke_token_jti,
    get_current_token_payload, MAX_FAILED_LOGINS, LOCKOUT_MINUTES,
    password_change_required,
)

router = APIRouter()
_log = logging.getLogger("szup.auth")


def test_mode_env_allowed() -> bool:
    """Tryb testowy (logowanie bez hasła) wymaga JAWNEJ zgody środowiska.

    Sama flaga `test_mode` w bazie NIE wystarcza — trzeba dodatkowo ustawić
    zmienną środowiskową `SZUP_ALLOW_TEST_MODE` (1/true/yes/on). Dzięki temu
    baza produkcyjna z przypadkowo włączoną flagą nie otwiera passwordless-login,
    a włączenie wymaga świadomej decyzji na poziomie wdrożenia (nie tylko UI).
    """
    return os.getenv("SZUP_ALLOW_TEST_MODE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def test_mode_effective(app_cfg: Optional[AppSettings]) -> bool:
    """Tryb testowy działa tylko gdy flaga w bazie ORAZ zgoda środowiska."""
    return bool(app_cfg and app_cfg.test_mode) and test_mode_env_allowed()


_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_PER_WINDOW = 10
# Górny limit liczby śledzonych adresów — słownik żyje w pamięci procesu,
# więc bez sprzątania rósłby bez końca (np. przy skanowaniu z wielu adresów).
_IP_HITS_MAX_KEYS = 10000
_ip_hits: dict[str, deque] = defaultdict(deque)
_ip_lock = Lock()
_ip_last_purge = 0.0


def _purge_ip_hits(now: float) -> None:
    """Usuń adresy bez prób w bieżącym oknie; gdy nadal za dużo — najstarsze.
    Wołać pod `_ip_lock`."""
    global _ip_last_purge
    cutoff = now - _LOGIN_WINDOW_SECONDS
    for key in [k for k, dq in _ip_hits.items() if not dq or dq[-1] < cutoff]:
        _ip_hits.pop(key, None)
    overflow = len(_ip_hits) - _IP_HITS_MAX_KEYS
    if overflow > 0:
        for key in sorted(_ip_hits, key=lambda k: _ip_hits[k][-1])[:overflow]:
            _ip_hits.pop(key, None)
    _ip_last_purge = now


def _check_ip_rate_limit(ip: Optional[str]) -> None:
    if not ip:
        return
    now = time.monotonic()
    with _ip_lock:
        if now - _ip_last_purge > _LOGIN_WINDOW_SECONDS or len(_ip_hits) >= _IP_HITS_MAX_KEYS:
            _purge_ip_hits(now)
        dq = _ip_hits[ip]
        cutoff = now - _LOGIN_WINDOW_SECONDS
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _LOGIN_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Zbyt wiele prób logowania z tego adresu. Spróbuj za chwilę.",
            )
        dq.append(now)


class SetupRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TestLoginRequest(BaseModel):
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # ID konta — front zapamiętuje je przy logowaniu (np. ukrywa „Zamknij” przy
    # własnych zdarzeniach bezpieczeństwa), tak samo jak z /auth/me.
    id: Optional[int] = None
    username: str
    roles: list[str]
    role: str                  # primary role (dla kompatybilności)
    full_name: Optional[str] = None
    must_change_password: bool = False
    # True, gdy powodem wymuszonej zmiany jest WYGASŁE hasło (a nie reset przez
    # admina) — wtedy /change-password wymaga podania obecnego hasła.
    password_expired: bool = False
    password_expires_in_days: Optional[int] = None


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str


def _effective_roles(session, user: User, user_roles: list[str]) -> list[str]:
    """Role widoczne dla frontu. Pracownik komórki kadrowej (Department.is_hr)
    dostaje efektywnie rolę 'hr' — żeby zobaczył Kartotekę i mógł zgłaszać
    nowych pracowników/ustania. Token (JWT) i baza pozostają bez zmian;
    autoryzację po stronie backendu i tak egzekwuje `user_is_hr`."""
    try:
        if "hr" not in user_roles and getattr(user, "department_id", None):
            from models import Department
            d = session.get(Department, user.department_id)
            if d and getattr(d, "is_hr", False):
                return [*user_roles, "hr"]
    except Exception:
        pass
    return user_roles


def _days_until_expiry(user: User) -> Optional[int]:
    from services.auth_service import password_max_age_days
    if user.auth_type != AuthType.local or not user.password_changed_at:
        return None
    deadline = user.password_changed_at + timedelta(days=password_max_age_days(parse_roles(user.roles)))
    delta = deadline - datetime.utcnow()
    return max(0, delta.days)


def _handle_failed_login(session: Session, user: Optional[User], username: str,
                         request: Request, reason: str):
    meta = request_meta(request)
    if user and user.auth_type == AuthType.local:
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
            session.add(user); session.commit()
            record_event(session, action="login.lockout", user_id=user.id, username=user.username,
                         ip=meta["ip"], user_agent=meta["user_agent"],
                         details={"reason": reason, "locked_minutes": LOCKOUT_MINUTES})
            emit_security_event(
                session, event_type="auth.lockout", source="auth",
                severity=SecuritySeverity.high,
                summary=f"Konto {user.username} zablokowane po {MAX_FAILED_LOGINS} błędnych logowaniach",
                details={"ip": meta["ip"]}, user_id=user.id, ip=meta["ip"],
            )
            return
        session.add(user); session.commit()
    record_event(session, action="login.failed",
                 user_id=user.id if user else None, username=username,
                 ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"reason": reason})


def _account_is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.utcnow())


@router.get("/server-time")
def server_time():
    """Zwraca aktualny czas serwera (UTC) jako epoch_ms i ISO string.
    Nie wymaga uwierzytelnienia — używany do synchronizacji zegara klient↔serwer."""
    # time.time() zwraca prawdziwy UTC epoch — naive datetime.timestamp() byłby
    # interpretowany jako czas lokalny i dał błędną wartość na serwerze nie-UTC.
    epoch_s = time.time()
    now = datetime.utcfromtimestamp(epoch_s)
    return {
        "epoch_ms": int(epoch_s * 1000),
        "utc": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }


@router.get("/status")
def auth_status(session: Session = Depends(get_session)):
    from services.permissions import users_with_role
    has_superadmin = bool(users_with_role(session, "superadmin", active_only=False))
    ldap = session.exec(select(LdapSettings)).first()
    app_cfg = session.exec(select(AppSettings)).first()
    return {
        "first_run": not has_superadmin,
        "ldap_enabled": bool(ldap and ldap.enabled),
        # Front pokazuje opcję logowania testowego tylko gdy jest ONA REALNIE
        # aktywna (flaga w bazie + zgoda środowiska SZUP_ALLOW_TEST_MODE).
        "test_mode": test_mode_effective(app_cfg),
        # SSO (Kerberos/Negotiate) — przycisk „Zaloguj poświadczeniami Windows".
        "sso_enabled": bool(ldap and ldap.enabled and getattr(ldap, "sso_enabled", False)),
        "sso_auto": bool(ldap and ldap.enabled and getattr(ldap, "sso_enabled", False)
                         and getattr(ldap, "sso_auto", False)),
    }


@router.post("/setup", response_model=TokenResponse)
def setup(data: SetupRequest, request: Request, session: Session = Depends(get_session)):
    from services.permissions import users_with_role
    if users_with_role(session, "superadmin", active_only=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konfiguracja już została ukończona")

    validate_password_strength(data.password)

    user = User(
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        roles=roles_to_json(["superadmin"]),
        auth_type=AuthType.local,
        password_changed_at=datetime.utcnow(),
    )
    session.add(user); session.commit(); session.refresh(user)

    meta = request_meta(request)
    record_event(session, action="auth.setup", user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"])

    user_roles = parse_roles(user.roles)
    token = create_access_token(user.username, user_roles, user.id)
    return TokenResponse(access_token=token, id=user.id, username=user.username,
                         roles=_effective_roles(session, user, user_roles), role=primary_role(user),
                         full_name=user.full_name, must_change_password=False,
                         password_expires_in_days=_days_until_expiry(user))


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, session: Session = Depends(get_session)):
    meta = request_meta(request)
    _check_ip_rate_limit(meta["ip"])

    user = session.exec(select(User).where(User.username == data.username)).first()
    if not user or user.auth_type != AuthType.local or not user.password_hash:
        _handle_failed_login(session, user, data.username, request, "unknown_user_or_wrong_auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy login lub hasło")
    if _account_is_locked(user):
        record_event(session, action="login.blocked_locked",
                     user_id=user.id, username=user.username,
                     ip=meta["ip"], user_agent=meta["user_agent"])
        raise HTTPException(status.HTTP_423_LOCKED, "Konto tymczasowo zablokowane — spróbuj później")
    if not verify_password(data.password, user.password_hash):
        _handle_failed_login(session, user, data.username, request, "bad_password")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy login lub hasło")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto nieaktywne")

    user.failed_login_count = 0
    user.locked_until = None
    session.add(user); session.commit(); session.refresh(user)

    must_change = bool(user.must_change_password) or is_password_expired(user)
    record_event(session, action="login.success",
                 user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"must_change_password": must_change})

    user_roles = parse_roles(user.roles)
    token = create_access_token(user.username, user_roles, user.id)
    return TokenResponse(access_token=token, id=user.id, username=user.username,
                         roles=_effective_roles(session, user, user_roles), role=primary_role(user),
                         full_name=user.full_name, must_change_password=must_change,
                         password_expired=is_password_expired(user) and not user.must_change_password,
                         password_expires_in_days=_days_until_expiry(user))


@router.post("/login/test", response_model=TokenResponse)
def login_test(data: TestLoginRequest, request: Request, session: Session = Depends(get_session)):
    """
    Tryb testowy: logowanie samym loginem, bez hasła. Dostępne TYLKO jeśli administrator
    włączył tryb testowy w Ustawieniach. Każda próba i każde udane logowanie jest zapisywane
    jako security event — tryb NIE jest przeznaczony na produkcję.
    """
    meta = request_meta(request)
    _check_ip_rate_limit(meta["ip"])

    app_cfg = session.exec(select(AppSettings)).first()
    # Wymóg dwuskładnikowy: flaga w bazie ORAZ zgoda środowiska
    # (SZUP_ALLOW_TEST_MODE). Bez zmiennej środowiskowej passwordless-login jest
    # twardo zablokowany, nawet jeśli ktoś zostawił flagę w bazie.
    if not test_mode_effective(app_cfg):
        if app_cfg and app_cfg.test_mode and not test_mode_env_allowed():
            emit_security_event(
                session, event_type="auth.test_mode_blocked", source="auth",
                severity=SecuritySeverity.high,
                summary="Próba logowania testowego przy braku SZUP_ALLOW_TEST_MODE",
                details={"ip": meta["ip"], "username": data.username}, ip=meta["ip"],
            )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tryb testowy nie jest włączony")

    user = session.exec(select(User).where(User.username == data.username)).first()
    if not user:
        record_event(session, action="login.failed", username=data.username,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"reason": "test_mode_unknown_user"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Użytkownik nie istnieje")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto nieaktywne")

    # Konta uprzywilejowane (superadmin/admin) NIGDY nie logują się bez hasła —
    # nawet w trybie testowym. Break-glass superadmin musi mieć realne hasło.
    priv_roles = parse_roles(user.roles)
    if "superadmin" in priv_roles or "admin" in priv_roles:
        emit_security_event(
            session, event_type="auth.test_mode_privileged_blocked", source="auth",
            severity=SecuritySeverity.critical,
            summary=f"Zablokowano logowanie testowe konta uprzywilejowanego: {user.username}",
            details={"ip": meta["ip"]}, user_id=user.id, ip=meta["ip"],
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Konta administracyjne nie mogą logować się w trybie testowym — użyj hasła.")

    record_event(session, action="login.success",
                 user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"auth_type": "test_mode"})
    emit_security_event(
        session, event_type="auth.test_mode_login", source="auth",
        severity=SecuritySeverity.high,
        summary=f"Logowanie w trybie testowym: {user.username}",
        details={"ip": meta["ip"]}, user_id=user.id, ip=meta["ip"],
    )

    user_roles = parse_roles(user.roles)
    token = create_access_token(user.username, user_roles, user.id)
    # Flaga zgodna z egzekwowaniem w get_current_user — inaczej front nie pokaże
    # ekranu zmiany hasła, a backend odrzuci każde żądanie (403).
    return TokenResponse(access_token=token, id=user.id, username=user.username,
                         roles=_effective_roles(session, user, user_roles), role=primary_role(user),
                         full_name=user.full_name, must_change_password=password_change_required(user))


def _reject_non_domain_account(session: Session, user: User, request: Request, channel: str) -> None:
    """Logowanie AD/SSO wolno wydać token WYŁĄCZNIE kontu domenowemu.

    Konto lokalne (w tym superadmin break-glass) loguje się tylko hasłem lokalnym
    (/auth/login). Inaczej ktoś, kto kontroluje serwer LDAP (np. admin zmieniający
    ustawienia) albo nagłówek SSO, zalogowałby się jako lokalny superadmin.
    Rejestrujemy to jako zdarzenie bezpieczeństwa; klient dostaje ogólny błąd."""
    meta = request_meta(request)
    record_event(session, action="login.failed", user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"auth_type": channel, "reason": "local_account_via_domain_login"})
    emit_security_event(
        session, event_type="auth.domain_login_local_account", source="auth",
        severity=SecuritySeverity.high,
        summary=f"Odrzucono logowanie {channel.upper()} na konto lokalne: {user.username}",
        details={"ip": meta["ip"], "channel": channel}, user_id=user.id, ip=meta["ip"],
    )


@router.post("/login/ldap", response_model=TokenResponse)
def login_ldap(data: LoginRequest, request: Request, session: Session = Depends(get_session)):
    from services.ldap_service import authenticate_ldap, normalize_login, find_user_by_login
    meta = request_meta(request)
    _check_ip_rate_limit(meta["ip"])

    ldap_settings = session.exec(select(LdapSettings)).first()
    if not ldap_settings or not ldap_settings.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Logowanie przez AD nie jest skonfigurowane")

    # 'DOMENA\\Jan.Kowalski' / 'jan.kowalski@domena' → 'jan.kowalski' — jedno konto AD
    # = jedno konto w aplikacji (tak samo jak w SSO i imporcie z AD).
    username = normalize_login(data.username)

    if not username or not authenticate_ldap(ldap_settings, username, data.password):
        record_event(session, action="login.failed", username=username or data.username,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"reason": "ldap_reject"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy login lub hasło AD")

    user = find_user_by_login(session, username)
    if user and user.auth_type != AuthType.ldap:
        _reject_non_domain_account(session, user, request, "ldap")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy login lub hasło AD")
    if not user:
        user = User(username=username, roles=roles_to_json(["viewer"]), auth_type=AuthType.ldap)
        session.add(user); session.commit(); session.refresh(user)

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto nieaktywne")

    record_event(session, action="login.success",
                 user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"auth_type": "ldap"})

    user_roles = parse_roles(user.roles)
    token = create_access_token(user.username, user_roles, user.id)
    return TokenResponse(access_token=token, id=user.id, username=user.username,
                         roles=_effective_roles(session, user, user_roles), role=primary_role(user),
                         full_name=user.full_name, must_change_password=False)


# ---------------------------------------------------------------------------
# SSO — Kerberos/Negotiate (wzorem dbac / wods-transfer)
#
# Apache (mod_auth_gssapi) chroni WYŁĄCZNIE /api/auth/sso-login i przekazuje
# zweryfikowany login w nagłówku X-Remote-User. Ten sam nagłówek przysłany
# przez przeglądarkę Apache usuwa ("RequestHeader unset ... early"), a backend
# słucha tylko na 127.0.0.1 — patrz deploy/szup-apache.conf. Dodatkowo WYMAGAMY
# zgodnego X-SSO-Proxy-Secret (SZUP_SSO_PROXY_SECRET, ustawia go
# deploy/enable-sso.sh w Apache i /opt/szup/.env) — bez sekretu SSO jest
# odrzucane, bo nagłówek X-Remote-User mógłby wysłać dowolny proces na hoście.
#
# Token JWT nie trafia do URL: sso-login wydaje jednorazowy kod (60 s),
# frontend wymienia go na token przez POST /sso-exchange.
# ---------------------------------------------------------------------------

_SSO_CODE_TTL = 60
_sso_codes: dict[str, tuple[int, float]] = {}
_sso_lock = Lock()


def _sso_fail(reason: str) -> RedirectResponse:
    return RedirectResponse(f"/login?sso={reason}", status_code=status.HTTP_303_SEE_OTHER)


def sso_proxy_secret() -> str:
    """Sekret współdzielony z Apache (nagłówek X-SSO-Proxy-Secret)."""
    return os.getenv("SZUP_SSO_PROXY_SECRET", "").strip()


@router.get("/sso-login")
def sso_login(request: Request, session: Session = Depends(get_session)):
    from services.ldap_service import lookup_user, normalize_login, find_user_by_login, login_realm_ok

    meta = request_meta(request)
    ldap_settings = session.exec(select(LdapSettings)).first()
    if not ldap_settings or not ldap_settings.enabled or not getattr(ldap_settings, "sso_enabled", False):
        return _sso_fail("off")

    expected = sso_proxy_secret()
    if not expected:
        # Sekret jest OBOWIĄZKOWY — bez niego nie odróżnimy Apache od dowolnego
        # lokalnego procesu wysyłającego X-Remote-User na 127.0.0.1:8003.
        _log.error("SSO odrzucone: brak SZUP_SSO_PROXY_SECRET w środowisku usługi "
                   "(uruchom deploy/enable-sso.sh i zrestartuj szup)")
        emit_security_event(
            session, event_type="sso.no_proxy_secret", source="auth",
            severity=SecuritySeverity.high,
            summary="SSO odrzucone: nie skonfigurowano sekretu proxy (SZUP_SSO_PROXY_SECRET)",
            details={"remote_user_header": request.headers.get("x-remote-user")}, ip=meta["ip"],
        )
        return _sso_fail("error")
    if not _secrets.compare_digest(request.headers.get("x-sso-proxy-secret", ""), expected):
        emit_security_event(
            session, event_type="sso.untrusted_proxy", source="auth",
            severity=SecuritySeverity.high,
            summary="Żądanie SSO bez poprawnego sekretu proxy — możliwa próba podszycia pod Apache",
            details={"remote_user_header": request.headers.get("x-remote-user")}, ip=meta["ip"],
        )
        return _sso_fail("error")

    raw_user = request.headers.get("x-remote-user", "")
    # Realm z Kerberosa musi należeć do domeny skonfigurowanej w LDAP — obcięcie
    # „@REALM” bez sprawdzenia wpuściłoby konto z obcej (zaufanej) domeny.
    if not login_realm_ok(ldap_settings, raw_user):
        record_event(session, action="login.failed", username=raw_user[:200],
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"auth_type": "sso", "reason": "foreign_realm"})
        emit_security_event(
            session, event_type="sso.foreign_realm", source="auth",
            severity=SecuritySeverity.high,
            summary="SSO: login z obcej domeny/realmu odrzucony",
            details={"remote_user_header": raw_user[:200]}, ip=meta["ip"],
        )
        return _sso_fail("error")
    username = normalize_login(raw_user)
    if not username:
        return _sso_fail("error")

    status_, info = lookup_user(ldap_settings, username)
    if status_ != "ok":
        record_event(session, action="login.failed", username=username,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"auth_type": "sso", "reason": status_, **info})
        if status_ == "error":
            emit_security_event(
                session, event_type="ldap.infra_error", source="auth",
                severity=SecuritySeverity.high,
                summary="SSO: nie udało się sprawdzić konta w AD", details=info, ip=meta["ip"],
            )
        return _sso_fail({"not_found": "notfound", "disabled": "disabled"}.get(status_, "error"))

    user = find_user_by_login(session, username)
    if user and user.auth_type != AuthType.ldap:
        _reject_non_domain_account(session, user, request, "sso")
        return _sso_fail("error")
    if not user:
        user = User(username=username, roles=roles_to_json(["viewer"]), auth_type=AuthType.ldap)
        session.add(user); session.commit(); session.refresh(user)

    if not user.is_active:
        record_event(session, action="login.blocked_inactive", user_id=user.id, username=user.username,
                     ip=meta["ip"], user_agent=meta["user_agent"], details={"auth_type": "sso"})
        return _sso_fail("inactive")

    code = _secrets.token_urlsafe(32)
    now = time.monotonic()
    with _sso_lock:
        for c in [c for c, (_, exp) in _sso_codes.items() if exp < now]:
            _sso_codes.pop(c, None)
        _sso_codes[code] = (user.id, now + _SSO_CODE_TTL)

    record_event(session, action="login.success", user_id=user.id, username=user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"], details={"auth_type": "sso"})
    return RedirectResponse(f"/sso-callback?code={code}", status_code=status.HTTP_303_SEE_OTHER)


class SsoExchange(BaseModel):
    code: str


@router.post("/sso-exchange", response_model=TokenResponse)
def sso_exchange(data: SsoExchange, session: Session = Depends(get_session)):
    with _sso_lock:
        entry = _sso_codes.pop(data.code, None)
    if not entry or entry[1] < time.monotonic():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kod logowania SSO wygasł — spróbuj ponownie")
    user = session.get(User, entry[0])
    if not user or not user.is_active or user.auth_type != AuthType.ldap:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Konto nieaktywne")
    user_roles = parse_roles(user.roles)
    token = create_access_token(user.username, user_roles, user.id)
    return TokenResponse(access_token=token, id=user.id, username=user.username,
                         roles=_effective_roles(session, user, user_roles), role=primary_role(user),
                         full_name=user.full_name, must_change_password=False)


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    payload: dict = Depends(get_current_token_payload),
    session: Session = Depends(get_session),
):
    jti = payload.get("jti")
    exp = payload.get("exp") or 0
    if jti:
        revoke_token_jti(jti, current_user.id, int(exp))
    meta = request_meta(request)
    record_event(session, action="logout", user_id=current_user.id,
                 username=current_user.username, ip=meta["ip"], user_agent=meta["user_agent"])
    return {"ok": True}


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if current_user.auth_type != AuthType.local or not current_user.password_hash:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Zmiana hasła dostępna tylko dla kont lokalnych")

    if not current_user.must_change_password:
        if not data.current_password or not verify_password(data.current_password, current_user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Obecne hasło jest nieprawidłowe")

    validate_password_strength(data.new_password)
    if data.current_password and data.current_password == data.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nowe hasło musi różnić się od poprzedniego")

    current_user.password_hash = hash_password(data.new_password)
    current_user.password_changed_at = datetime.utcnow()
    current_user.must_change_password = False
    # Unieważnij wcześniejsze tokeny. Pełna sekunda (bez mikrosekund i bez +1 s):
    # iat w JWT ma rozdzielczość sekundy, więc token z ponownego logowania zaraz
    # po wymuszonej zmianie hasła nie może zostać odrzucony jako „starszy”.
    current_user.tokens_valid_from = datetime.utcnow().replace(microsecond=0)
    session.add(current_user); session.commit()

    meta = request_meta(request)
    record_event(session, action="password.changed",
                 user_id=current_user.id, username=current_user.username,
                 ip=meta["ip"], user_agent=meta["user_agent"])
    return {"ok": True}


@router.get("/me")
def me(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Front odświeża zapamiętanego użytkownika z /me przy starcie — role muszą być
    # te same co w odpowiedzi logowania (z efektywną rolą „hr” komórki kadrowej).
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "roles": _effective_roles(session, current_user, parse_roles(current_user.roles)),
        "auth_type": getattr(current_user.auth_type, "value", current_user.auth_type),
        "role": primary_role(current_user),
        # Te same warunki co egzekwowanie w get_current_user (tylko konta lokalne).
        "must_change_password": password_change_required(current_user),
        "password_expired": is_password_expired(current_user) and not current_user.must_change_password,
        "password_expires_in_days": _days_until_expiry(current_user),
    }
