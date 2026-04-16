from __future__ import annotations
import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _make_fernet() -> Fernet:
    key_hex = settings.LDAP_ENCRYPTION_KEY
    if key_hex and len(key_hex) >= 64:
        raw = bytes.fromhex(key_hex[:64])
    else:
        # Derive stable key from JWT_SECRET when LDAP_ENCRYPTION_KEY not configured
        raw = hashlib.sha256(settings.JWT_SECRET.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(raw)
    return Fernet(fernet_key)


def encrypt_ldap_password(plain: str) -> str:
    return _make_fernet().encrypt(plain.encode()).decode()


def decrypt_ldap_password(enc: str) -> str:
    return _make_fernet().decrypt(enc.encode()).decode()


def create_access_token(payload: dict[str, Any]) -> str:
    data = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(payload: dict[str, Any]) -> str:
    data = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    data.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(data, settings.JWT_REFRESH_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def verify_refresh_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_REFRESH_SECRET, algorithms=[settings.JWT_ALGORITHM])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def build_token_payload(user) -> dict[str, Any]:
    return {
        "sub": str(user.id),
        "userId": user.id,
        "username": user.username,
        "email": user.email,
        "rola": user.rola,
        "tenantId": user.tenant_id,
    }
