"""
Audyt 3.5 — bezpieczeństwo administracji:
  - role administracyjne (admin/superadmin) nadaje i odbiera tylko superadmin,
  - zdarzenia high/critical zamyka tylko superadmin; admin nie zamyka zdarzeń
    dotyczących jego konta (także przez details.target_user_id),
  - client_ip: wiele nagłówków X-Forwarded-For — liczy się ostatni element,
  - zmiana serwera / konta LDAP bez nowego hasła czyści zapisane hasło.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select
from starlette.requests import Request

from database import engine
from models import LdapSettings, SecurityEvent, SecuritySeverity, User, parse_roles


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

def _admin(api):
    root = api.setup_superadmin()
    api.mk_user(root, "adm", ["admin"])
    return root, api.login("adm")


def _uid(username: str) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == username)).one().id


def _roles(uid: int) -> set[str]:
    with Session(engine) as s:
        return set(parse_roles(s.get(User, uid).roles))


def _event(severity: SecuritySeverity, *, user_id=None, details=None) -> int:
    with Session(engine) as s:
        ev = SecurityEvent(event_type="test.event", source="tests", severity=severity,
                           summary="Zdarzenie testowe", user_id=user_id,
                           details=json.dumps(details) if details is not None else None)
        s.add(ev); s.commit(); s.refresh(ev)
        return ev.id


def _create(api, token, username, roles):
    from tests.conftest import PW
    return api.post("/users/", token=token, json={
        "username": username, "password": PW, "full_name": username,
        "email": f"{username}@t.local", "roles": roles})


# ---------------------------------------------------------------------------
# 1. Role administracyjne — tylko superadmin
# ---------------------------------------------------------------------------

def test_admin_cannot_create_admin_or_superadmin(api):
    _root, adm = _admin(api)
    for roles in (["admin"], ["superadmin"], ["viewer", "admin"]):
        r = _create(api, adm, f"puppet-{'-'.join(roles)}", roles)
        assert r.status_code == 403, (roles, r.text)
    # Role operacyjne admin nadaje nadal.
    assert _create(api, adm, "kierownik", ["manager"]).status_code == 201


def test_superadmin_can_create_admin(api):
    root = api.setup_superadmin()
    assert _create(api, root, "adm2", ["admin"]).status_code == 201
    assert _create(api, root, "root2", ["superadmin"]).status_code == 201


def test_admin_cannot_grant_or_revoke_admin_roles(api):
    root, adm = _admin(api)
    viewer = api.mk_user(root, "zwykly", ["viewer"])
    other_admin = api.mk_user(root, "adm-inny", ["admin"])

    # Nadanie roli admin istniejącemu kontu — odmowa, role bez zmian.
    r = api.patch(f"/users/{viewer}", token=adm, json={"roles": ["viewer", "admin"]})
    assert r.status_code == 403, r.text
    assert _roles(viewer) == {"viewer"}
    r = api.patch(f"/users/{viewer}", token=adm, json={"roles": ["superadmin"]})
    assert r.status_code == 403, r.text

    # Odebranie roli admin innemu administratorowi — też tylko superadmin.
    r = api.patch(f"/users/{other_admin}", token=adm, json={"roles": ["viewer"]})
    assert r.status_code == 403, r.text
    assert "admin" in _roles(other_admin)

    # Zmiana ról operacyjnych konta z rolą admin (admin zostaje) — dozwolona.
    r = api.patch(f"/users/{other_admin}", token=adm, json={"roles": ["admin", "it_staff"]})
    assert r.status_code == 200, r.text
    assert _roles(other_admin) == {"admin", "it_staff"}

    # Role operacyjne zwykłego konta — dozwolone.
    r = api.patch(f"/users/{viewer}", token=adm, json={"roles": ["viewer", "hr"]})
    assert r.status_code == 200, r.text


def test_superadmin_can_grant_and_revoke_admin(api):
    root = api.setup_superadmin()
    uid = api.mk_user(root, "awans", ["viewer"])
    r = api.patch(f"/users/{uid}", token=root, json={"roles": ["viewer", "admin"]})
    assert r.status_code == 200, r.text
    assert "admin" in _roles(uid)
    r = api.patch(f"/users/{uid}", token=root, json={"roles": ["viewer"]})
    assert r.status_code == 200, r.text
    assert _roles(uid) == {"viewer"}


# ---------------------------------------------------------------------------
# 2. Zamykanie zdarzeń bezpieczeństwa
# ---------------------------------------------------------------------------

def test_admin_cannot_resolve_high_or_critical(api):
    root, adm = _admin(api)
    for sev in (SecuritySeverity.high, SecuritySeverity.critical):
        ev = _event(sev)
        r = api.post(f"/security/{ev}/resolve", token=adm, json={})
        assert r.status_code == 403, (sev, r.text)
        assert "superadmin" in r.json()["detail"]
        assert api.post(f"/security/{ev}/resolve", token=root, json={}).status_code == 200
    for sev in (SecuritySeverity.low, SecuritySeverity.medium):
        ev = _event(sev)
        assert api.post(f"/security/{ev}/resolve", token=adm, json={}).status_code == 200


def test_admin_cannot_resolve_event_targeting_own_account(api):
    root, adm = _admin(api)
    me = _uid("adm")
    own = _event(SecuritySeverity.medium, details={"target_user_id": me})
    other = _event(SecuritySeverity.medium, details={"target_user_id": me + 1000})
    r = api.post(f"/security/{own}/resolve", token=adm, json={})
    assert r.status_code == 403, r.text
    assert api.post(f"/security/{other}/resolve", token=adm, json={}).status_code == 200
    assert api.post(f"/security/{own}/resolve", token=root, json={}).status_code == 200


def test_admin_cannot_resolve_roles_granted_event_he_caused(api):
    """Nadanie roli operacyjnej przez admina → zdarzenie medium, którego sprawcą
    jest ten admin — sam go nie zamknie (zacieranie śladów), superadmin tak."""
    root, adm = _admin(api)
    uid = api.mk_user(root, "pracownik", ["viewer"])
    assert api.patch(f"/users/{uid}", token=adm,
                     json={"roles": ["viewer", "manager"]}).status_code == 200
    with Session(engine) as s:
        ev = s.exec(select(SecurityEvent)
                    .where(SecurityEvent.event_type == "user.roles_granted")
                    .order_by(SecurityEvent.id.desc())).first()
    # Zdarzenie wywołał sam admin (user_id) — zamyka je ktoś inny.
    assert api.post(f"/security/{ev.id}/resolve", token=adm, json={}).status_code == 403
    assert api.post(f"/security/{ev.id}/resolve", token=root, json={}).status_code == 200


# ---------------------------------------------------------------------------
# 3. client_ip — wiele nagłówków X-Forwarded-For
# ---------------------------------------------------------------------------

def _req(peer: str, xff_values: list[str]) -> Request:
    headers = [(b"x-forwarded-for", v.encode()) for v in xff_values]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 12345), "query_string": b""})


def test_client_ip_uses_last_of_all_xff_headers():
    from services.audit import client_ip
    # Klient dosłał własny nagłówek; Apache dopisał prawdziwy adres w drugim.
    assert client_ip(_req("127.0.0.1", ["6.6.6.6", "10.0.0.5"])) == "10.0.0.5"
    assert client_ip(_req("127.0.0.1", ["6.6.6.6, 7.7.7.7", "10.0.0.5"])) == "10.0.0.5"
    assert client_ip(_req("::1", ["1.1.1.1, 10.0.0.9"])) == "10.0.0.9"
    # Bez nagłówka — adres proxy.
    assert client_ip(_req("127.0.0.1", [])) == "127.0.0.1"
    # Połączenie spoza zaufanego proxy — nagłówek ignorowany.
    assert client_ip(_req("192.168.1.20", ["6.6.6.6"])) == "192.168.1.20"


# ---------------------------------------------------------------------------
# 4. LDAP — zmiana serwera / konta czyści zapisane hasło
# ---------------------------------------------------------------------------

_LDAP = {"enabled": False, "host": "dc1.example.local", "port": 389, "use_ssl": False,
         "base_dn": "DC=example,DC=local", "bind_dn": "CN=svc,DC=example,DC=local",
         "user_search_base": "", "user_filter": "(sAMAccountName={username})"}


def _ldap_has_password() -> bool:
    with Session(engine) as s:
        return bool(s.exec(select(LdapSettings)).first().bind_password_enc)


def test_ldap_host_change_clears_bind_password(api):
    root = api.setup_superadmin()
    r = api.put("/settings/ldap", token=root, json={**_LDAP, "bind_password": "Tajne123!"})
    assert r.status_code == 200, r.text
    assert r.json()["has_password"] is True and not r.json().get("warning")

    # Zapis bez zmiany serwera — hasło zostaje.
    r = api.put("/settings/ldap", token=root, json={**_LDAP, "port": 636})
    assert r.status_code == 200, r.text
    assert r.json()["has_password"] is True and not r.json().get("warning")

    # Inny serwer bez nowego hasła — hasło usunięte, ostrzeżenie w odpowiedzi.
    r = api.put("/settings/ldap", token=root, json={**_LDAP, "host": "evil.example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_password"] is False
    assert body["warning"] and "hasło" in body["warning"]
    assert not _ldap_has_password()


def test_ldap_bind_dn_change_clears_password_but_new_password_is_kept(api):
    root = api.setup_superadmin()
    api.put("/settings/ldap", token=root, json={**_LDAP, "bind_password": "Tajne123!"})
    r = api.put("/settings/ldap", token=root,
                json={**_LDAP, "bind_dn": "CN=inne,DC=example,DC=local"})
    assert r.json()["has_password"] is False and r.json()["warning"]

    # Zmiana serwera RAZEM z nowym hasłem — nowe hasło zostaje zapisane.
    r = api.put("/settings/ldap", token=root,
                json={**_LDAP, "host": "dc2.example.local", "bind_password": "Nowe456!"})
    assert r.status_code == 200, r.text
    assert r.json()["has_password"] is True and not r.json().get("warning")
