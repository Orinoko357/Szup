"""
Testy poprawek bezpieczeństwa (audyt 3.2):
  1. logowanie AD/SSO tylko dla kont domenowych, sekret proxy i realm w SSO,
  3. normalizacja loginu AD (bez duplikatów kont),
  7. blokada konta nie unieważnia ważnych sesji,
  8. wymuszona zmiana hasła egzekwowana w backendzie,
  + samonadawanie ról przez admina, wspólny helper IP (X-Forwarded-For).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from conftest import PW
from database import engine
from models import AuthType, LdapSettings, SecurityEvent, User, roles_to_json

NEW_PW = "NoweHaslo123!@#ABC"


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _enable_ldap(sso: bool = False, base_dn: str = "DC=wods,DC=local"):
    with Session(engine) as s:
        cfg = s.exec(select(LdapSettings)).first() or LdapSettings()
        cfg.enabled = True
        cfg.host = "ldap.test"
        cfg.base_dn = base_dn
        cfg.sso_enabled = sso
        s.add(cfg); s.commit()


def _user(username):
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == username)).first()


def _set(username, **fields):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).first()
        for k, v in fields.items():
            setattr(u, k, v)
        s.add(u); s.commit()


def _add_ldap_user(username, roles=("viewer",)):
    with Session(engine) as s:
        u = User(username=username, roles=roles_to_json(list(roles)),
                 auth_type=AuthType.ldap, password_hash="!ldap-managed!")
        s.add(u); s.commit()


def _sec_events(event_type):
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)).all()


@pytest.fixture()
def ldap_ok(monkeypatch):
    """AD „przyjmuje” każde hasło (atakujący kontroluje serwer LDAP)."""
    import services.ldap_service as ls
    seen = []

    def fake_auth(settings, username, password):
        seen.append(username)
        return True
    monkeypatch.setattr(ls, "authenticate_ldap", fake_auth)
    monkeypatch.setattr(ls, "lookup_user", lambda settings, username: ("ok", {}))
    return seen


# ---------------------------------------------------------------------------
# 1. Logowanie AD / SSO tylko dla kont domenowych
# ---------------------------------------------------------------------------

def test_ldap_login_refuses_local_superadmin(api, ldap_ok):
    api.setup_superadmin("root")
    _enable_ldap()
    r = api.post("/auth/login/ldap", json={"username": "root", "password": "cokolwiek"})
    assert r.status_code == 401
    assert "access_token" not in r.text
    assert _sec_events("auth.domain_login_local_account")


def test_sso_refuses_local_account(api, ldap_ok, monkeypatch):
    api.setup_superadmin("root")
    _enable_ldap(sso=True)
    monkeypatch.setenv("SZUP_SSO_PROXY_SECRET", "s3cret")
    r = api.c.get("/api/auth/sso-login", follow_redirects=False,
                  headers={"X-Remote-User": "root", "X-SSO-Proxy-Secret": "s3cret"})
    assert r.status_code == 303
    assert "sso=error" in r.headers["location"]
    assert _sec_events("auth.domain_login_local_account")


def test_sso_requires_proxy_secret(api, ldap_ok, monkeypatch):
    api.setup_superadmin("root")
    _enable_ldap(sso=True)
    _add_ldap_user("jan.kowalski")
    monkeypatch.delenv("SZUP_SSO_PROXY_SECRET", raising=False)
    r = api.c.get("/api/auth/sso-login", follow_redirects=False,
                  headers={"X-Remote-User": "jan.kowalski"})
    assert "sso=error" in r.headers["location"]
    assert _sec_events("sso.no_proxy_secret")
    # Health pokazuje to jako niespełniony punkt.
    tok = api.login("root")
    checks = {c["key"]: c for c in api.get("/settings/health", token=tok).json()["checks"]}
    assert checks["sso_secret"]["ok"] is False


def test_sso_realm_check_and_success(api, ldap_ok, monkeypatch):
    api.setup_superadmin("root")
    _enable_ldap(sso=True)
    _add_ldap_user("jan.kowalski")
    monkeypatch.setenv("SZUP_SSO_PROXY_SECRET", "s3cret")
    h = {"X-SSO-Proxy-Secret": "s3cret"}
    bad = api.c.get("/api/auth/sso-login", follow_redirects=False,
                    headers={**h, "X-Remote-User": "jan.kowalski@OBCA.LOCAL"})
    assert "sso=error" in bad.headers["location"]
    assert _sec_events("sso.foreign_realm")
    ok = api.c.get("/api/auth/sso-login", follow_redirects=False,
                   headers={**h, "X-Remote-User": "Jan.Kowalski@WODS.LOCAL"})
    assert ok.headers["location"].startswith("/sso-callback?code=")
    # Zły sekret → odrzucone.
    wrong = api.c.get("/api/auth/sso-login", follow_redirects=False,
                      headers={"X-SSO-Proxy-Secret": "zly", "X-Remote-User": "jan.kowalski"})
    assert "sso=error" in wrong.headers["location"]


def test_ldap_settings_require_superadmin(api):
    root = api.setup_superadmin("root")
    api.mk_user(root, "adm", ["admin"])
    adm = api.login("adm")
    body = {"enabled": True, "host": "evil.example", "base_dn": "DC=x"}
    assert api.put("/settings/ldap", token=adm, json=body).status_code == 403
    r = api.put("/settings/ldap", token=root, json={**body, "bind_password": "tajne"})
    assert r.status_code == 200
    ev = _sec_events("settings.ldap")
    assert ev and "tajne" not in (ev[-1].details or "")


# ---------------------------------------------------------------------------
# 3. Normalizacja loginu AD — bez duplikatów
# ---------------------------------------------------------------------------

def test_ldap_login_normalizes_and_is_case_insensitive(api, ldap_ok):
    api.setup_superadmin("root")
    _enable_ldap()
    variants = ["WODS\\Jan.Kowalski", "jan.kowalski@wods.local", " JAN.KOWALSKI "]
    names = []
    for v in variants:
        r = api.post("/auth/login/ldap", json={"username": v, "password": "x"})
        assert r.status_code == 200, r.text
        names.append(r.json()["username"])
    assert set(names) == {"jan.kowalski"}
    assert ldap_ok == ["jan.kowalski"] * 3      # do AD trafia login bez realmu
    with Session(engine) as s:
        rows = s.exec(select(User).where(User.auth_type == AuthType.ldap)).all()
    assert [u.username for u in rows] == ["jan.kowalski"]


def test_ldap_login_finds_legacy_mixed_case_account(api, ldap_ok):
    api.setup_superadmin("root")
    _enable_ldap()
    _add_ldap_user("Anna.Nowak", roles=("manager",))
    r = api.post("/auth/login/ldap", json={"username": "anna.nowak", "password": "x"})
    assert r.status_code == 200
    assert r.json()["username"] == "Anna.Nowak"
    assert "manager" in r.json()["roles"]
    with Session(engine) as s:
        assert len(s.exec(select(User).where(User.auth_type == AuthType.ldap)).all()) == 1


def test_login_regex_rejects_realm_suffix():
    from services.ldap_service import is_valid_login, normalize_login
    assert not is_valid_login("jan@domena")
    assert is_valid_login(normalize_login("jan@domena"))
    assert normalize_login("DOMENA\\Jan") == "jan"


# ---------------------------------------------------------------------------
# 7. Blokada konta nie zabija ważnych sesji
# ---------------------------------------------------------------------------

def test_lockout_does_not_kill_existing_session(api):
    root = api.setup_superadmin("root")
    for _ in range(5):
        api.post("/auth/login", json={"username": "root", "password": "zle-haslo"})
    assert _user("root").locked_until is not None
    # Ważny token nadal działa…
    assert api.get("/auth/me", token=root).status_code == 200
    assert api.get("/users/", token=root).status_code == 200
    # …a nowe logowanie hasłem jest zablokowane.
    r = api.post("/auth/login", json={"username": "root", "password": PW})
    assert r.status_code == 423


# ---------------------------------------------------------------------------
# 8. Wymuszona zmiana hasła po stronie backendu
# ---------------------------------------------------------------------------

def _assert_pw_change_required(r):
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == {
        "code": "PASSWORD_CHANGE_REQUIRED",
        "message": "Wymagana zmiana hasła przed dalszym korzystaniem z systemu",
    }


def test_must_change_password_enforced_until_changed(api):
    root = api.setup_superadmin("root")
    # Konto zakładamy bezpośrednio (mk_user zdejmuje flagę dla testów obiegu).
    r = api.post("/users/", token=root, json={
        "username": "nowy", "password": PW, "full_name": "Nowy", "roles": ["admin"]})
    assert r.status_code == 201
    login = api.post("/auth/login", json={"username": "nowy", "password": PW}).json()
    assert login["must_change_password"] is True
    tok = login["access_token"]

    _assert_pw_change_required(api.get("/users/", token=tok))
    _assert_pw_change_required(api.get("/settings/health", token=tok))
    me = api.get("/auth/me", token=tok)
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    assert me.json()["auth_type"] == "local"

    r = api.post("/auth/change-password", token=tok, json={"new_password": NEW_PW})
    assert r.status_code == 200, r.text
    assert _user("nowy").must_change_password is False

    tok2 = api.login("nowy", NEW_PW)
    assert api.get("/users/", token=tok2).status_code == 200


def test_expired_password_enforced(api):
    root = api.setup_superadmin("root")
    _set("root", password_changed_at=datetime.utcnow() - timedelta(days=400))
    tok = api.post("/auth/login", json={"username": "root", "password": PW}).json()
    assert tok["must_change_password"] is True and tok["password_expired"] is True
    _assert_pw_change_required(api.get("/users/", token=tok["access_token"]))
    # Przy wygasłym haśle zmiana wymaga obecnego hasła.
    r = api.post("/auth/change-password", token=tok["access_token"],
                 json={"current_password": PW, "new_password": NEW_PW})
    assert r.status_code == 200, r.text
    assert api.get("/users/", token=api.login("root", NEW_PW)).status_code == 200
    del root


def test_ldap_account_not_subject_to_forced_change(api, ldap_ok):
    api.setup_superadmin("root")
    _enable_ldap()
    _add_ldap_user("piotr")
    _set("piotr", must_change_password=True)
    tok = api.post("/auth/login/ldap", json={"username": "piotr", "password": "x"}).json()["access_token"]
    assert api.get("/settings/declaration-text", token=tok).status_code == 200


# ---------------------------------------------------------------------------
# 9. Admin nie nadaje sobie ról / stanowisk
# ---------------------------------------------------------------------------

def test_admin_cannot_escalate_self(api):
    root = api.setup_superadmin("root")
    adm_id = api.mk_user(root, "adm", ["admin"])
    adm = api.login("adm")
    r = api.patch(f"/users/{adm_id}", token=adm, json={"roles": ["admin", "manager"]})
    assert r.status_code == 403
    # Bez zmiany ról — dozwolone (np. edycja nazwiska).
    r = api.patch(f"/users/{adm_id}", token=adm, json={"roles": ["admin"], "full_name": "A"})
    assert r.status_code == 200
    unit = api.mk_unit(root)
    assert api.patch(f"/units/{unit}", token=adm, json={"manager_user_id": adm_id}).status_code == 403
    dept = api.mk_department(root, unit, None)
    assert api.post(f"/units/departments/{dept}/deputies", token=adm,
                    json={"user_id": adm_id}).status_code == 403
    # Superadmin może.
    assert api.patch(f"/units/{unit}", token=root, json={"manager_user_id": adm_id}).status_code == 200


def test_deactivation_releases_manager_posts(api):
    root = api.setup_superadmin("root")
    mgr = api.mk_user(root, "kier", ["manager"])
    unit = api.mk_unit(root)
    dept = api.mk_department(root, unit, mgr)
    assert api.patch(f"/users/{mgr}", token=root, json={"is_active": False}).status_code == 200
    from models import Department
    with Session(engine) as s:
        assert s.get(Department, dept).manager_user_id is None


# ---------------------------------------------------------------------------
# 6. X-Forwarded-For — tylko od zaufanego proxy, ostatni element
# ---------------------------------------------------------------------------

class _Req:
    def __init__(self, peer, xff=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


def test_client_ip_trusts_only_local_proxy_last_hop():
    from services.audit import client_ip
    assert client_ip(_Req("127.0.0.1", "6.6.6.6, 10.0.0.5")) == "10.0.0.5"
    assert client_ip(_Req("10.1.1.1", "6.6.6.6")) == "10.1.1.1"
    assert client_ip(_Req("::1")) == "::1"


def test_ip_rate_limit_dict_is_bounded(monkeypatch):
    from routers import auth
    monkeypatch.setattr(auth, "_IP_HITS_MAX_KEYS", 50)
    auth._ip_hits.clear()
    for i in range(200):
        auth._check_ip_rate_limit(f"10.0.{i // 250}.{i % 250}")
    assert len(auth._ip_hits) <= 51
    auth._ip_hits.clear()
