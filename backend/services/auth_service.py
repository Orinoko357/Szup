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
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

_DATA_DIR   = Path(os.getenv("SZUP_DATA_DIR", "/opt/szup/data"))
_SECRET_FILE = _DATA_DIR / "jwt_secret.key"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

MAX_FAILED_LOGINS        = 5
LOCKOUT_MINUTES          = 15
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
