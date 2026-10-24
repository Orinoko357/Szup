"""
JWT auth helpers, password policy, FastAPI dependency.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta
from threading import Lock
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError as JWTError
from passlib.context import CryptContext

_DATA_DIR   = Path(os.getenv("SZUP_DATA_DIR", "/opt/szup/data"))
_SECRET_FILE = _DATA_DIR / "jwt_secret.key"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

MAX_FAILED_LOGINS        = 5
LOCKOUT_MINUTES          = 15
# Wylogowanie po bezczynności — ta sama wartość co w kliencie
# (frontend/src/hooks/useIdleLogout.js: IDLE_TIMEOUT_MS = 30 minut). Serwer
# odrzuca token (401), gdy ostatnia aktywność sesji jest starsza (3.11).
IDLE_TIMEOUT_MINUTES     = 30
# Zapis ostatniej aktywności sesji do bazy najwyżej raz na tyle sekund.
ACTIVITY_WRITE_INTERVAL_S = 60
PASSWORD_MIN_LEN         = 12
PASSWORD_MAX_AGE_DAYS_ADMIN = 90
PASSWORD_MAX_AGE_DAYS_USER  = 180

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
_log = logging.getLogger("szup.auth")


def write_secret_file(path: Path, content: str) -> None:
    """Zapisz plik z sekretem od razu z prawami 0600.

    `os.open(..., 0o600)` nadaje prawa przy tworzeniu — bez okna, w którym plik
    istnieje z domyślnymi prawami (0644 przy umask 022), zanim zrobimy chmod.
    O_EXCL: nie nadpisujemy istniejącego klucza (dwa procesy startujące naraz).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(content)


def _jwt_secret() -> str:
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    try:
        write_secret_file(_SECRET_FILE, secret)
    except FileExistsError:
        # Inny proces utworzył klucz w międzyczasie — używamy jego wersji.
        return _SECRET_FILE.read_text().strip()
    return secret


def invalidate_tokens_now(user) -> None:
    """Unieważnij wszystkie wcześniej wydane tokeny konta (`tokens_valid_from`).

    Pełna sekunda (bez mikrosekund): `iat` w JWT ma rozdzielczość sekundy, więc
    token z ponownego logowania tuż po zmianie nie zostanie odrzucony jako
    „starszy”. Commit robi wywołujący."""
    user.tokens_valid_from = datetime.utcnow().replace(microsecond=0)


# ---------------------------------------------------------------------------
# Wspólny limit nieudanych potwierdzeń hasłem (3.10)
#
# Jeden licznik per konto dla WSZYSTKICH miejsc, w których zalogowana sesja
# potwierdza tożsamość hasłem: zmiana hasła (obecne hasło), operacje superadmina
# (czyszczenie dzienników, usunięcie komórki, usunięcie posiadanej grupy) i reset
# fabryczny. Osobne liczniki pozwalały zgadywać hasło z przejętej sesji przez
# ścieżkę bez limitu (/auth/change-password). Licznik jest w bazie, więc restart
# usługi go nie zeruje. Po CONFIRM_MAX_FAILURES próbach w oknie
# CONFIRM_WINDOW_MINUTES minut każda kolejna próba dostaje 429.
# ---------------------------------------------------------------------------

# Jeden budżet (3.11) — te same wartości co limit logowań.
CONFIRM_MAX_FAILURES = MAX_FAILED_LOGINS
CONFIRM_WINDOW_MINUTES = LOCKOUT_MINUTES

# 3.11 — JEDEN budżet prób hasła (N-7): nieudane potwierdzenia hasłem z sesji
# (`ATTEMPT_CONFIRM`, liczone dla konta niezależnie od adresu) i nieudane
# logowania hasłem (`ATTEMPT_LOGIN`, liczone dla pary konto + adres IP — N8:
# obcy z innego adresu nie zablokuje logowania właściciela konta). Każda próba
# z danego adresu widzi: potwierdzenia konta + logowania z tego adresu. Próba
# jest zapisywana PRZED weryfikacją hasła, atomowo z kontrolą limitu
# (BEGIN IMMEDIATE) — równoległe żądania nie przekroczą limitu (N7).
ATTEMPT_CONFIRM = "confirm"
ATTEMPT_LOGIN = "login"


def _confirm_window_start() -> datetime:
    return datetime.utcnow() - timedelta(minutes=CONFIRM_WINDOW_MINUTES)


def _db_time(value: datetime) -> str:
    """Format daty, w jakim SQLAlchemy zapisuje DateTime w SQLite."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _budget_clause(ip: Optional[str]):
    """Warunek SQLAlchemy: wpisy liczące się do budżetu prób z adresu `ip`."""
    from sqlalchemy import func, or_
    from models import PasswordConfirmFailure as F
    kind = func.coalesce(F.kind, ATTEMPT_CONFIRM)
    login_here = (kind == ATTEMPT_LOGIN) & (F.ip == ip if ip is not None else F.ip.is_(None))
    return or_(kind == ATTEMPT_CONFIRM, login_here)


def password_confirm_failures(session, user_id: int, ip: Optional[str] = None) -> int:
    """Liczba nieudanych prób hasła konta w bieżącym oknie, które liczą się
    dla adresu `ip` (potwierdzenia konta + logowania z tego adresu)."""
    from sqlalchemy import func
    from sqlmodel import select
    from models import PasswordConfirmFailure
    return int(session.exec(
        select(func.count()).select_from(PasswordConfirmFailure)
        .where(PasswordConfirmFailure.user_id == user_id)
        .where(PasswordConfirmFailure.created_at > _confirm_window_start())
        .where(_budget_clause(ip))
    ).one() or 0)


def _too_many_confirm_attempts() -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Zbyt wiele nieudanych prób potwierdzenia hasłem. "
        f"Spróbuj ponownie za {CONFIRM_WINDOW_MINUTES} minut.")


def begin_password_attempt(user_id: int, *, kind: str, ip: Optional[str],
                           operation: str) -> tuple[Optional[int], int]:
    """Atomowo (BEGIN IMMEDIATE, osobne połączenie): sprząta wpisy spoza okna,
    liczy próby z budżetu (`_budget_clause`) i — jeśli limit nie jest
    wyczerpany — zapisuje TĘ próbę jako nieudaną, zanim hasło zostanie
    sprawdzone. Udana weryfikacja usuwa wpis (`end_password_attempt`).

    Zwraca (id wpisu albo None, gdy limit wyczerpany; liczba prób przed tą)."""
    from database import engine as db_engine
    window = _db_time(_confirm_window_start())
    raw = db_engine.raw_connection()
    dbapi = raw.driver_connection
    prev_isolation = dbapi.isolation_level
    try:
        dbapi.isolation_level = None
        cur = dbapi.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute('DELETE FROM "passwordconfirmfailure" WHERE user_id = ? '
                        'AND created_at <= ?', (user_id, window))
            n = cur.execute(
                'SELECT COUNT(*) FROM "passwordconfirmfailure" WHERE user_id = ? '
                'AND created_at > ? AND (COALESCE(kind, ?) = ? '
                'OR (COALESCE(kind, ?) = ? AND ip IS ?))',
                (user_id, window, ATTEMPT_CONFIRM, ATTEMPT_CONFIRM,
                 ATTEMPT_CONFIRM, ATTEMPT_LOGIN, ip)).fetchone()[0]
            if n >= CONFIRM_MAX_FAILURES:
                cur.execute("COMMIT")
                return None, int(n)
            cur.execute(
                'INSERT INTO "passwordconfirmfailure" (user_id, created_at, operation, '
                'kind, ip) VALUES (?, ?, ?, ?, ?)',
                (user_id, _db_time(datetime.utcnow()), (operation or "")[:200], kind,
                 (ip or None) and str(ip)[:64]))
            attempt_id = cur.lastrowid
            cur.execute("COMMIT")
            return int(attempt_id), int(n)
        except Exception:
            try:
                cur.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                _log.warning("ROLLBACK zapisu próby hasła nieudany", exc_info=True)
            raise
    finally:
        dbapi.isolation_level = prev_isolation
        raw.close()


def end_password_attempt(session, attempt_id: Optional[int], *, user_id: int,
                         kind: str, ip: Optional[str] = None) -> None:
    """Hasło poprawne: usuń wpis tej próby i wcześniejsze porażki — przy
    potwierdzeniu wszystkie porażki potwierdzeń konta, przy logowaniu porażki
    logowania z tego adresu. Zatwierdza od razu."""
    from sqlalchemy import delete, func
    from models import PasswordConfirmFailure as F
    if attempt_id is not None:
        session.execute(delete(F).where(F.id == attempt_id))
    stmt = delete(F).where(F.user_id == user_id)
    if kind == ATTEMPT_LOGIN:
        stmt = stmt.where(F.kind == ATTEMPT_LOGIN).where(
            F.ip == ip if ip is not None else F.ip.is_(None))
    else:
        stmt = stmt.where(func.coalesce(F.kind, ATTEMPT_CONFIRM) == ATTEMPT_CONFIRM)
    session.execute(stmt)
    session.commit()


def report_password_confirm_failure(session, user, *, operation: str, event_type: str,
                                    source: str, ip: Optional[str] = None,
                                    severity=None) -> bool:
    """Zdarzenie bezpieczeństwa po nieudanym potwierdzeniu (wpis próby zapisał
    już `begin_password_attempt`). `severity` — waga pojedynczej próby
    (domyślnie high); próba, która wyczerpuje limit, dostaje wagę o stopień
    wyższą (high → critical, medium → high). Zwraca True, gdy limit wyczerpany."""
    from models import SecuritySeverity
    from services.security_events import emit as emit_security_event

    severity = severity or SecuritySeverity.high
    failures = password_confirm_failures(session, user.id, ip)
    blocked = failures >= CONFIRM_MAX_FAILURES
    if blocked:
        severity = (SecuritySeverity.critical if severity == SecuritySeverity.high
                    else SecuritySeverity.high)
    emit_security_event(
        session, event_type=event_type, source=source, severity=severity,
        summary=(f"Nieudane potwierdzenie hasłem ({operation}) przez {user.username}"
                 + (f" — kolejne próby zablokowane na {CONFIRM_WINDOW_MINUTES} minut"
                    if blocked else "")),
        details={"operation": operation, "failures_in_window": failures,
                 "target_user_id": user.id},
        user_id=user.id, ip=ip,
    )
    return blocked


def verify_password_with_limit(session, user, password: str, *, verify, operation: str,
                               ip: Optional[str], event_type: str, source: str,
                               severity=None) -> bool:
    """Potwierdzenie hasłem z sesji w ramach wspólnego budżetu prób: rezerwacja
    próby (429, gdy limit wyczerpany) → `verify()` → przy sukcesie wyczyszczenie
    licznika, przy porażce zdarzenie bezpieczeństwa. Zwraca wynik weryfikacji."""
    attempt_id, _before = begin_password_attempt(user.id, kind=ATTEMPT_CONFIRM, ip=ip,
                                                 operation=operation)
    if attempt_id is None:
        raise _too_many_confirm_attempts()
    if verify():
        end_password_attempt(session, attempt_id, user_id=user.id, kind=ATTEMPT_CONFIRM)
        return True
    report_password_confirm_failure(session, user, operation=operation,
                                    event_type=event_type, source=source, ip=ip,
                                    severity=severity)
    return False


# ---------------------------------------------------------------------------
# Pola tekstowe kont (login, imię i nazwisko, e-mail) — limity (3.10, N2)
# ---------------------------------------------------------------------------

IDENTITY_FIELD_MAX = 200
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# Znaki sterujące kierunkiem tekstu (LRE/RLE/PDF/LRO/RLO, LRI/RLI/FSI/PDI) —
# pozwalają „odwrócić” wyświetlane nazwisko czy nazwę (podszycie). Usuwamy je.
BIDI_CONTROL_RE = re.compile("[\u202a-\u202e\u2066-\u2069]")
# Znaki niewidoczne (zero-width, znaczniki kierunku, BOM, miękki dywiz) —
# nazwa złożona WYŁĄCZNIE z nich wygląda na pustą.
_INVISIBLE_RE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def strip_bidi_controls(value: Optional[str]) -> Optional[str]:
    """Usuwa znaki sterujące kierunkiem tekstu (U+202A–U+202E, U+2066–U+2069)."""
    if value is None:
        return None
    return BIDI_CONTROL_RE.sub("", str(value))


def is_blank_text(value: Optional[str]) -> bool:
    """Pusty tekst albo złożony wyłącznie z białych i niewidocznych znaków."""
    return not _INVISIBLE_RE.sub("", value or "").strip()


def clean_text_field(value: Optional[str], label: str, *,
                     max_len: int = IDENTITY_FIELD_MAX,
                     required: bool = False,
                     multiline: bool = False) -> Optional[str]:
    """Przycina spacje i sprawdza pole tekstowe: długość ≤ `max_len`, bez znaków
    sterujących (NUL, CR/LF, tabulator… — w polu `multiline` dozwolone są nowa
    linia i tabulator). Znaki sterujące kierunkiem tekstu są usuwane, a tekst
    złożony wyłącznie ze znaków niewidocznych traktowany jak pusty (3.11).
    Puste → None (albo 400, gdy `required`). Błąd = HTTPException 400
    z polskim komunikatem."""
    if value is None:
        if required:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Pole „{label}” jest wymagane")
        return None
    text = strip_bidi_controls(str(value)).strip()
    if is_blank_text(text):
        if text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Pole „{label}” nie może składać się wyłącznie "
                                "ze znaków niewidocznych")
        if required:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Pole „{label}” jest wymagane")
        return None
    if len(text) > max_len:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Pole „{label}” może mieć najwyżej {max_len} znaków")
    check = text.replace("\n", "").replace("\r", "").replace("\t", "") if multiline else text
    if _CONTROL_CHARS_RE.search(check):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Pole „{label}” zawiera niedozwolone znaki sterujące "
                            "(np. znak nowej linii)")
    return text


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password_strength(password: str) -> None:
    if not password or len(password) < PASSWORD_MIN_LEN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Hasło musi mieć co najmniej {PASSWORD_MIN_LEN} znaków",
        )
    classes = sum([
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"[0-9]", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ])
    if classes < 3:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Hasło musi zawierać znaki z co najmniej 3 z 4 klas: "
            "małe litery, wielkie litery, cyfry, znaki specjalne",
        )
    common = {"password", "password1", "qwerty", "12345678", "123456789",
              "letmein", "admin123", "welcome1", "szup1234"}
    if password.lower() in common:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hasło jest zbyt popularne")


def password_max_age_days(roles: list[str]) -> int:
    if "superadmin" in roles or "admin" in roles:
        return PASSWORD_MAX_AGE_DAYS_ADMIN
    return PASSWORD_MAX_AGE_DAYS_USER


def is_password_expired(user) -> bool:
    from models import AuthType, parse_roles
    if user.auth_type != AuthType.local:
        return False
    if not user.password_changed_at:
        return False
    max_age = password_max_age_days(parse_roles(user.roles))
    return datetime.utcnow() - user.password_changed_at > timedelta(days=max_age)


class _RolesProxy:
    """Pomocniczy obiekt z polem `roles` (JSON string) dla `primary_role()`."""
    def __init__(self, roles: list[str]):
        import json
        self.roles = json.dumps(roles or ["viewer"])


def create_access_token(username: str, roles: list[str], user_id: Optional[int] = None) -> str:
    from models import primary_role
    # UWAGA: NIE używamy datetime.utcnow().timestamp() — naive datetime jest interpretowany
    # jako czas LOKALNY przez .timestamp(), więc na serwerze CET/CEST iat byłby cofnięty
    # o 1-2 godziny w stosunku do prawdziwego UTC. To powodowało, że `tokens_valid_from`
    # (zapisywany jako naive UTC) był większy od `utcfromtimestamp(iat)` i każdy świeży
    # token był odrzucany jako "starszy niż reset". time.time() zwraca prawdziwy UTC epoch.
    now_epoch = int(time.time())
    payload = {
        "sub": username,
        "roles": roles,
        "role":  primary_role(_RolesProxy(roles)),
        "uid": user_id,
        "iat": now_epoch,
        "exp": now_epoch + ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def revoke_token_jti(jti: str, user_id: Optional[int], exp_ts: int) -> None:
    from database import engine as db_engine
    from sqlmodel import Session
    from models import RevokedToken
    try:
        with Session(db_engine) as s:
            if s.get(RevokedToken, jti):
                return
            s.add(RevokedToken(
                jti=jti,
                user_id=user_id,
                expires_at=datetime.utcfromtimestamp(exp_ts) if exp_ts else datetime.utcnow() + timedelta(hours=8),
            ))
            s.commit()
    except Exception:
        # Wylogowany token pozostałby ważny do wygaśnięcia — musi to być widać w logu.
        _log.warning("Nie udało się unieważnić tokenu (jti=%s, user_id=%s) przy wylogowaniu",
                     jti, user_id, exc_info=True)


def _jti_is_revoked(jti: str) -> bool:
    if not jti:
        return False
    from database import engine as db_engine
    from sqlmodel import Session
    from models import RevokedToken
    try:
        with Session(db_engine) as s:
            return s.get(RevokedToken, jti) is not None
    except Exception:
        _log.warning("Nie udało się sprawdzić listy unieważnionych tokenów (jti=%s)",
                     jti, exc_info=True)
        return False


# Wymuszona zmiana hasła (must_change_password / hasło wygasłe) — egzekwowana
# w backendzie, nie tylko we froncie. Do czasu zmiany hasła konto lokalne ma
# dostęp WYŁĄCZNIE do poniższych ścieżek (ekran wymuszonej zmiany hasła).
PASSWORD_CHANGE_ALLOWED_PATHS = frozenset({
    "/api/auth/change-password",
    "/api/auth/me",
    "/api/auth/logout",
})

PASSWORD_CHANGE_REQUIRED_DETAIL = {
    "code": "PASSWORD_CHANGE_REQUIRED",
    "message": "Wymagana zmiana hasła przed dalszym korzystaniem z systemu",
}


def password_change_required(user) -> bool:
    """Czy konto musi zmienić hasło przed dalszą pracą. Tylko konta lokalne —
    konta AD zmieniają hasło w domenie (tam obowiązuje polityka domeny)."""
    from models import AuthType
    if user.auth_type != AuthType.local:
        return False
    return bool(user.must_change_password) or is_password_expired(user)


# Ostatnia aktywność sesji zapisana w bazie (jti → epoch) — pamięć procesu
# ogranicza zapisy do jednego na ACTIVITY_WRITE_INTERVAL_S; źródłem prawdy
# (także dla kilku procesów) jest tabela SessionActivity.
_activity_seen: dict[str, float] = {}
_activity_lock = Lock()
_ACTIVITY_CACHE_MAX = 20000
_activity_new_rows = 0


def _session_idle_expired(session, jti: Optional[str], uid: int, iat: Optional[int]) -> bool:
    """Wylogowanie po bezczynności po stronie serwera (3.11). Ostatnia
    aktywność = max(zapis w bazie, pamięć procesu, wydanie tokenu). Starsza niż
    IDLE_TIMEOUT_MINUTES → True (token odrzucany). Inaczej odnotowuje bieżącą
    aktywność — w bazie najwyżej raz na ACTIVITY_WRITE_INTERVAL_S sekund."""
    if not jti:
        return False
    from models import SessionActivity
    now = time.time()
    with _activity_lock:
        last = _activity_seen.get(jti)
    if last is None or now - last >= ACTIVITY_WRITE_INTERVAL_S:
        row = session.get(SessionActivity, jti)
        known = [x for x in (last, float(iat) if iat else None,
                             (row.last_seen_at - datetime(1970, 1, 1)).total_seconds()
                             if row else None) if x is not None]
        last = max(known) if known else now
        if now - last > IDLE_TIMEOUT_MINUTES * 60:
            return True
        try:
            if row is None:
                row = SessionActivity(jti=jti, user_id=uid)
                global _activity_new_rows
                _activity_new_rows += 1
                if _activity_new_rows % 200 == 0:
                    purge_session_activity(session)
            row.last_seen_at = datetime.utcfromtimestamp(now)
            session.add(row)
            session.commit()
        except Exception:  # noqa: BLE001 — np. równoległy INSERT tego samego jti
            session.rollback()
            _log.debug("Nie zapisano aktywności sesji %s", jti, exc_info=True)
        with _activity_lock:
            if len(_activity_seen) >= _ACTIVITY_CACHE_MAX:
                cutoff = now - IDLE_TIMEOUT_MINUTES * 60
                for k in [k for k, v in _activity_seen.items() if v < cutoff]:
                    _activity_seen.pop(k, None)
                if len(_activity_seen) >= _ACTIVITY_CACHE_MAX:
                    _activity_seen.clear()
            _activity_seen[jti] = now
        return False
    return now - last > IDLE_TIMEOUT_MINUTES * 60


def purge_session_activity(session) -> int:
    """Usuwa wpisy aktywności sesji starszych niż ważność tokenu (sprzątanie)."""
    from sqlalchemy import delete
    from models import SessionActivity
    cutoff = datetime.utcnow() - timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    res = session.execute(delete(SessionActivity).where(SessionActivity.last_seen_at < cutoff))
    session.commit()
    return int(res.rowcount or 0)


def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    from database import engine as db_engine
    from sqlmodel import Session
    from models import User

    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nieautoryzowany",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        uid = payload.get("uid")
        jti: str | None = payload.get("jti")
        iat: int | None = payload.get("iat")
    except JWTError:
        raise exc
    # Sesję identyfikuje ID KONTA (`uid`), a login (`sub`) musi się z nim zgadzać.
    # Sam login nie wystarcza: po zmianie loginu (zmiana nazwiska) albo usunięciu
    # konta ten sam login może trafić do INNEGO konta, a stary token działałby
    # wtedy jako ono. Tokeny bez `uid` (sprzed 3.8) są odrzucane — ponowne logowanie.
    if not username or not isinstance(uid, int) or isinstance(uid, bool):
        raise exc

    if jti and _jti_is_revoked(jti):
        raise exc

    with Session(db_engine) as session:
        user = session.get(User, uid)
        if not user or user.username != username or not user.is_active:
            raise exc
        if user.tokens_valid_from and iat is not None:
            if datetime.utcfromtimestamp(iat) < user.tokens_valid_from:
                raise exc
        if _session_idle_expired(session, jti, user.id, iat):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sesja wygasła z powodu bezczynności — zaloguj się ponownie",
                headers={"WWW-Authenticate": "Bearer"})
        # Blokada konta (locked_until) po błędnych hasłach blokuje WYŁĄCZNIE nowe
        # logowania hasłem — nie unieważnia ważnych sesji. Inaczej każdy mógłby
        # wylogować np. superadmina, wpisując kilka razy złe hasło (DoS).
        if password_change_required(user):
            path = (request.url.path or "").rstrip("/") if request is not None else ""
            if path not in PASSWORD_CHANGE_ALLOWED_PATHS:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail=dict(PASSWORD_CHANGE_REQUIRED_DETAIL))
        return user


def get_current_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieautoryzowany")
