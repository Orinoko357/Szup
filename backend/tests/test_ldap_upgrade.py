"""Aktualizacja istniejącej instalacji do 3.8: nowe zabezpieczenia LDAP nie mogą
odciąć logowania AD (zachowanie sprzed aktualizacji + ostrzeżenie w liście
kontrolnej), a nowa instalacja dostaje bezpieczne wartości domyślne."""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

import database
from database import engine


def _ldap_row():
    with Session(engine) as s:
        return s.exec(text('SELECT use_ssl, tls_verify, allow_insecure FROM "ldapsettings"')).first()


def _old_install(use_ssl: int):
    """Stan sprzed 3.8: wiersz ustawień LDAP bez nowych kolumn."""
    from models import LdapSettings
    with Session(engine) as s:
        s.exec(text('DELETE FROM "ldapsettings"'))
        s.add(LdapSettings(enabled=True, host="dc.local", port=389, use_ssl=bool(use_ssl),
                           base_dn="DC=wods,DC=local", bind_dn="svc"))
        s.commit()
    engine.dispose()
    with engine.connect() as c:
        for col in ("tls_verify", "allow_insecure"):
            c.execute(text(f'ALTER TABLE "ldapsettings" DROP COLUMN {col}'))
        c.commit()


def test_upgrade_plain_ldap_keeps_working():
    _old_install(use_ssl=0)
    database._run_migrations()
    assert tuple(_ldap_row()) == (0, 0, 1)      # bez weryfikacji, LDAP bez SSL dozwolony


def test_upgrade_ldaps_keeps_working_without_ca():
    _old_install(use_ssl=1)
    database._run_migrations()
    assert tuple(_ldap_row()) == (1, 0, 0)      # LDAPS jak dotąd, bez weryfikacji CA


def test_fresh_defaults_are_secure():
    from models import LdapSettings
    cfg = LdapSettings()
    assert cfg.tls_verify is True and cfg.allow_insecure is False


def test_plain_ldap_refused_unless_allowed():
    import pytest
    from models import LdapSettings
    from services.ldap_service import open_connection, LdapInsecureError
    cfg = LdapSettings(host="dc.local", port=389, use_ssl=False)
    with pytest.raises(LdapInsecureError):
        open_connection(cfg, None, "svc", "haslo")
