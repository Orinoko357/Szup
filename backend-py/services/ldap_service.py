from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import decrypt_ldap_password

logger = logging.getLogger(__name__)


async def ldap_authenticate(username: str, password: str, domena_id: Optional[int], session: Session) -> dict:
    if domena_id:
        rows = session.execute(
            text("SELECT * FROM ldap_domeny WHERE id=:id AND aktywna=1"),
            {"id": domena_id},
        ).mappings().all()
    else:
        rows = session.execute(
            text("SELECT * FROM ldap_domeny WHERE aktywna=1 ORDER BY kolejnosc"),
        ).mappings().all()

    domains = [dict(r) for r in rows]
    if not domains:
        raise ValueError("Brak aktywnych domen LDAP.")

    last_error = None
    for domain in domains:
        try:
            result = _authenticate_against_domain(domain, username, password)
            return {**result, "domenoId": domain["id"], "domena": domain["domena"]}
        except Exception as e:
            logger.debug(f"LDAP domain {domain.get('domena')} failed: {e}")
            last_error = e

    raise ValueError(str(last_error) if last_error else "Błąd uwierzytelniania LDAP.")


def _authenticate_against_domain(domain: dict, username: str, password: str) -> dict:
    try:
        from ldap3 import Server, Connection, ALL, NTLM, Tls
        import ssl
    except ImportError:
        raise ImportError("ldap3 is not installed")

    ldap_url = domain.get("ldap_url", "")
    use_tls = domain.get("tls", False)

    tls_config = None
    if use_tls:
        tls_config = Tls(validate=ssl.CERT_NONE)

    server = Server(ldap_url, use_ssl=ldap_url.startswith("ldaps://"), tls=tls_config, get_info=ALL)

    bind_dn = domain.get("bind_dn")
    bind_password_enc = domain.get("bind_password_enc")
    bind_password = None
    if bind_password_enc:
        try:
            bind_password = decrypt_ldap_password(bind_password_enc)
        except Exception:
            pass

    # Bind with service account
    if bind_dn and bind_password:
        conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
    else:
        conn = Connection(server, auto_bind=True)

    # Search for user
    user_filter = (domain.get("user_filter") or "(&(objectClass=user)(sAMAccountName=%s))") % username
    base_dn = domain.get("base_dn", "")
    attr_email = domain.get("attr_email", "mail")
    attr_fn = domain.get("attr_firstname", "givenName")
    attr_ln = domain.get("attr_lastname", "sn")
    attr_un = domain.get("attr_username", "sAMAccountName")

    conn.search(base_dn, user_filter, attributes=[attr_email, attr_fn, attr_ln, attr_un])
    if not conn.entries:
        raise ValueError("Użytkownik nie znaleziony w katalogu LDAP.")

    entry = conn.entries[0]
    user_dn = entry.entry_dn

    # Authenticate with user's credentials
    user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)

    email = str(entry[attr_email].value) if attr_email in entry else ""
    firstname = str(entry[attr_fn].value) if attr_fn in entry else ""
    lastname = str(entry[attr_ln].value) if attr_ln in entry else ""

    user_conn.unbind()
    conn.unbind()

    return {"email": email, "imie": firstname, "nazwisko": lastname, "username": username}


async def test_domain(domena_id: int, session: Session):
    row = session.execute(
        text("SELECT * FROM ldap_domeny WHERE id=:id"),
        {"id": domena_id},
    ).mappings().first()
    if not row:
        raise ValueError("Domena nie istnieje.")
    domain = dict(row)

    try:
        from ldap3 import Server, Connection, ALL
        ldap_url = domain.get("ldap_url", "")
        server = Server(ldap_url, get_info=ALL)
        bind_dn = domain.get("bind_dn")
        bind_password_enc = domain.get("bind_password_enc")
        bind_password = None
        if bind_password_enc:
            try:
                bind_password = decrypt_ldap_password(bind_password_enc)
            except Exception:
                pass
        if bind_dn and bind_password:
            conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
        else:
            conn = Connection(server, auto_bind=True)
        conn.unbind()
        return True
    except Exception as e:
        raise ValueError(f"Błąd połączenia LDAP: {e}")
