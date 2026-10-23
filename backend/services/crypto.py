"""
Fernet encryption helpers for sensitive settings.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet

_mf: MultiFernet | None = None
_KEY_FILE = Path(os.getenv("SZUP_DATA_DIR", "/opt/szup/data")) / "secret.key"


def _create_key_file() -> bytes:
    """Utwórz plik klucza od razu z prawami 0600 (`os.open` z trybem) — bez okna,
    w którym klucz leży na dysku z prawami domyślnymi, zanim zrobimy chmod.
    Gdy inny proces utworzył plik w międzyczasie (O_EXCL), używamy jego klucza."""
    k = Fernet.generate_key()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _KEY_FILE.read_bytes().strip()
    with os.fdopen(fd, "wb") as fh:
        fh.write(k)
    return k


def _load_keys() -> list[bytes]:
    keys: list[bytes] = []
    env_key = os.getenv("SZUP_SECRET_KEY")
    if env_key:
        keys.append(env_key.strip().encode())
    else:
        if _KEY_FILE.exists():
            keys.append(_KEY_FILE.read_bytes().strip())
        else:
            keys.append(_create_key_file())

    old = os.getenv("SZUP_SECRET_KEY_OLD", "").strip()
    if old:
        for chunk in old.split(","):
            chunk = chunk.strip()
            if chunk:
                keys.append(chunk.encode())
    return keys


def _get_mf() -> MultiFernet:
    global _mf
    if _mf is None:
        _mf = MultiFernet([Fernet(k) for k in _load_keys()])
    return _mf


def reset_cache() -> None:
    global _mf
    _mf = None


def encrypt(plaintext: str) -> str:
    return _get_mf().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_mf().decrypt(ciphertext.encode()).decode()


def rotate(ciphertext: str) -> str:
    return _get_mf().rotate(ciphertext.encode()).decode()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--genkey":
        print(Fernet.generate_key().decode())
    else:
        print("Usage: python -m services.crypto --genkey")
        sys.exit(1)
