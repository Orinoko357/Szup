"""
CLI: re-encrypt all Fernet-encrypted fields with the current primary key.
Run after rotating SZUP_SECRET_KEY (see services/crypto.py header for procedure).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import engine, init_db
from models import EmailSettings, LdapSettings
from services.crypto import rotate, reset_cache
from sqlmodel import Session, select

reset_cache()
init_db()

with Session(engine) as s:
    for cfg in s.exec(select(EmailSettings)).all():
        if cfg.smtp_password_enc:
            cfg.smtp_password_enc = rotate(cfg.smtp_password_enc)
            s.add(cfg)
    for cfg in s.exec(select(LdapSettings)).all():
        if cfg.bind_password_enc:
            cfg.bind_password_enc = rotate(cfg.bind_password_enc)
            s.add(cfg)
    s.commit()

print("Rotacja kluczy zakończona.")
