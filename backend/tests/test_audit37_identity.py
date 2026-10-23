"""Audyt 3.7 — tożsamość, konta administracyjne, LDAPS, limity zapytań.

Regresje dla poprawek 3.8 (testy dowodowe audytu przerobione na asercje
poprawnego zachowania):
  1. Sesja identyfikowana po ID konta (`uid`), zmiana loginu przy zmianie
     nazwiska (SoD, unieważnienie sesji, login bez względu na wielkość liter).
  2. Kontem z rolą admin / superadmin zarządza wyłącznie superadmin.
  3. „Struktura” (/users/my-subtree) liczy uprawnienia jak „Pracownicy”.
  4. Dezaktywacja konta powiadamia nowego odpowiedzialnego; import z AD nie
     reaktywuje kont wyłączonych w SZUP.
  5. LDAPS / STARTTLS z weryfikacją certyfikatu; bez TLS hasło nie wychodzi.
  7. Ujemne `limit` / `offset` → 422.
"""
from __future__ import annotations

import json
import ssl
import time

import pytest
from jose import jwt
from sqlmodel import Session, select

from database import engine
from models import (
    AuthType, Department, LdapSettings, RequestItem, SecurityEvent,
    SecuritySeverity, User,
)
from services import auth_service
from tests.conftest import PW
from tests.test_audit34_logic import _capture_jobs, _create, _hr_request, _world


def _uid(name: str) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == name)).first().id


def _events(event_type: str) -> list[SecurityEvent]:
    with Session(engine) as s:
        return s.exec(select(SecurityEvent)
                      .where(SecurityEvent.event_type == event_type)).all()


def _token(payload: dict) -> str:
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 3600, "jti": "t" + str(now), **payload},
                      auth_service._jwt_secret(), algorithm=auth_service.ALGORITHM)


def _name_change(api, token, new_name="Nowe Nazwisko") -> int:
    r = api.post("/name-changes", token=token, json={"requested_full_name": new_name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _resolve(api, nc_id, token, **body):
    return api.post(f"/name-changes/{nc_id}/resolve", token=token,
                    json={"action": "apply", **body})


# ---------------------------------------------------------------------------
# 1. Sesja po ID konta, zmiana loginu
# ---------------------------------------------------------------------------

def test_token_without_uid_or_with_mismatched_login_is_rejected(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"])
    jan_id = _uid("jan")
    assert api.get("/auth/me", token=api.login("jan")).status_code == 200
    # Token sprzed 3.8 (bez `uid`) — wymagane ponowne logowanie.
    assert api.get("/auth/me", token=_token({"sub": "jan"})).status_code == 401
    # `uid` innego konta niż `sub` — odrzucony.
    assert api.get("/auth/me", token=_token({"sub": "root", "uid": jan_id})).status_code == 401
    assert api.get("/auth/me", token=_token({"sub": "jan", "uid": jan_id})).status_code == 200


def test_login_response_includes_account_id(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"])
    r = api.post("/auth/login", json={"username": "jan", "password": PW})
    assert r.json()["id"] == _uid("jan")


def test_rename_cannot_take_over_admin_account(api):
    """Dowód S1/H4: IT przemianowuje siebie, potem konto admina na swój stary
    login. Teraz: brak realizacji własnego wniosku, zmiana loginu admina tylko
    przez superadmina, a stary token nie przechodzi na inne konto."""
    w = _world(api)
    sup = w["sup"]
    api.mk_user(sup, "itguy", ["it_staff"])
    it_old = api.login("itguy")
    it_other = api.login("it")

    nc_it = _name_change(api, it_old, "IT Nowy")
    assert _resolve(api, nc_it, it_old, new_username="itguy2").status_code == 403
    r = _resolve(api, nc_it, it_other, new_username="itguy2")
    assert r.status_code == 200, r.text
    # Stara sesja po zmianie loginu wygasa (tokens_valid_from + sub ≠ login).
    assert api.get("/auth/me", token=it_old).status_code == 401
    it_new = api.login("itguy2")
    assert api.get("/auth/me", token=it_new).status_code == 200

    adm = api.login("adm")
    nc_adm = _name_change(api, adm, "Admin Nowak")
    r = _resolve(api, nc_adm, it_new, new_username="itguy")
    assert r.status_code == 403, r.text
    # Superadmin może — ale stary token IT (sub=itguy, uid=IT) nie staje się adminem.
    r = _resolve(api, nc_adm, sup, new_username="itguy")
    assert r.status_code == 200, r.text
    assert api.get("/users/", token=it_old).status_code == 401
    assert api.get("/auth/me", token=it_old).status_code == 401
    assert api.get("/auth/me", token=adm).status_code == 401   # admin loguje się ponownie

    evs = _events("user.login_changed")
    assert len(evs) == 2
    assert all(e.severity == SecuritySeverity.high for e in evs)
    assert {json.loads(e.details)["target_user_id"] for e in evs} == {_uid("itguy2"), _uid("itguy")}


def test_name_change_without_login_change_keeps_session(api):
    _world(api)
    tok = api.login("kier")
    nc = _name_change(api, tok)
    assert _resolve(api, nc, api.login("it")).status_code == 200
    assert api.get("/auth/me", token=tok).status_code == 200
    assert not _events("user.login_changed")


def test_name_change_login_taken_case_insensitive(api):
    """A09: „KIERP” obok istniejącego „kierP” — odrzucone."""
    _world(api)
    nc = _name_change(api, api.login("kier"))
    r = _resolve(api, nc, api.login("it"), new_username="KIERP")
    assert r.status_code == 400, r.text
    assert "zajęty" in r.json()["detail"]
    # Zmiana wielkości liter WŁASNEGO loginu nie koliduje z samym sobą.
    r = _resolve(api, nc, api.login("it"), new_username="Kier")
    assert r.status_code == 200, r.text


def test_old_token_does_not_map_to_new_account_with_reused_login(api):
    """A28: po zmianie loginu ten sam login dostaje nowe konto — stary token
    nie działa na nie."""
    w = _world(api)
    sup = w["sup"]
    api.mk_user(sup, "jkowalska", ["viewer"], "Joanna Kowalska")
    old = api.login("jkowalska")
    nc = _name_change(api, old, "Joanna Nowak")
    assert _resolve(api, nc, api.login("it"), new_username="jnowak").status_code == 200
    api.mk_user(sup, "jkowalska", ["viewer"], "Inna Osoba")
    assert api.get("/auth/me", token=old).status_code == 401


def test_name_change_ldap_account_login_normalized(api):
    w = _world(api)
    nc = _name_change(api, api.login("kier"))
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == "kier")).first()
        u.auth_type = AuthType.ldap
        s.add(u); s.commit()
    r = _resolve(api, nc, api.login("it"), new_username="Jan.Nowak")
    assert r.status_code == 200, r.text
    assert r.json()["new_username"] == "jan.nowak"
    with Session(engine) as s:
        assert s.get(User, w["kid"]).username == "jan.nowak"


def test_name_change_resolution_notifies_worker(api, monkeypatch):
    _world(api)
    nc = _name_change(api, api.login("kier"), "Jan Nowy")
    jobs = _capture_jobs(monkeypatch)
    assert _resolve(api, nc, api.login("it"), new_username="jnowy").status_code == 200
    mails = [kw for name, kw in jobs if name == "_send"]
    assert len(mails) == 1
    assert mails[0]["to_address"] == "kier@t.local"
    assert "jnowy" in mails[0]["body"] and "Jan Nowy" in mails[0]["body"]


# ---------------------------------------------------------------------------
# 2. Konta z rolą admin — tylko superadmin
# ---------------------------------------------------------------------------

def test_admin_cannot_manage_peer_admin_account(api):
    """Dowód S4 / code_ops 1: admin resetował hasło innego admina i działał
    jako on."""
    sup = api.setup_superadmin()
    a = api.mk_user(sup, "admA", ["admin"])
    b = api.mk_user(sup, "admB", ["admin"])
    ta = api.login("admA")

    assert api.post(f"/users/{b}/reset-password", token=ta,
                    json={"new_password": PW}).status_code == 403
    assert api.post(f"/users/{b}/unlock", token=ta).status_code == 403
    assert api.patch(f"/users/{b}", token=ta, json={"is_active": False}).status_code == 403
    assert api.patch(f"/users/{b}", token=ta,
                     json={"roles": ["admin", "it_staff"]}).status_code == 403
    assert api.delete(f"/users/{b}", token=ta).status_code == 403
    with Session(engine) as s:
        assert s.get(User, b).is_active is True

    # Własne dane admin nadal edytuje; superadmin zarządza kontem admina.
    assert api.patch(f"/users/{a}", token=ta, json={"full_name": "Adam A"}).status_code == 200
    assert api.post(f"/users/{b}/reset-password", token=sup,
                    json={"new_password": PW}).status_code == 200
    assert api.patch(f"/users/{b}", token=sup, json={"is_active": False}).status_code == 200


def test_password_reset_of_privileged_account_emits_high_event(api):
    sup = api.setup_superadmin()
    adm = api.mk_user(sup, "adm", ["admin"])
    it = api.mk_user(sup, "it", ["it_staff"])
    viewer = api.mk_user(sup, "zwykly", ["viewer"])
    ta = api.login("adm")
    assert api.post(f"/users/{it}/reset-password", token=ta,
                    json={"new_password": PW}).status_code == 200
    assert api.post(f"/users/{viewer}/reset-password", token=ta,
                    json={"new_password": PW}).status_code == 200
    evs = _events("user.password_reset")
    assert len(evs) == 1
    assert evs[0].severity == SecuritySeverity.high
    assert evs[0].user_id == adm
    assert json.loads(evs[0].details)["target_user_id"] == it
    # Zdarzenie wysokie zamyka tylko superadmin (nie sprawca).
    assert api.post(f"/security/{evs[0].id}/resolve", token=ta, json={}).status_code == 403


# ---------------------------------------------------------------------------
# 3. /users/my-subtree = _effective_permissions
# ---------------------------------------------------------------------------

def _complete(api, w, worker_id, items, kind):
    r = _create(api, w, api.login("hr"), items=items, kind=kind, worker_user_id=worker_id)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    kier = api.login("kier")
    if api.node_type(rid, kier) == "select_permissions":
        r = api.post(f"/requests/{rid}/workflow/action", token=kier,
                     json={"action": "select", "items": items})
        assert r.status_code == 200, r.text
    r = api.post(f"/requests/{rid}/workflow/action", token=api.login("it"),
                 json={"action": "execute"})
    assert r.status_code == 200, r.text
    return rid


def _subtree_perms(tree: dict, worker_id: int) -> list:
    stack = list(tree["roots"])
    while stack:
        d = stack.pop()
        for wk in d["workers"]:
            if wk["id"] == worker_id:
                return wk["permissions"]
        stack.extend(d["children"])
    raise AssertionError("pracownika nie ma w strukturze")


def test_my_subtree_hides_revoked_and_denied_permissions(api):
    """H3: odebrane i odmówione pozycje nie są „posiadane” w Strukturze."""
    w = _world(api)
    sup = w["sup"]
    _sid2, pid2 = api.mk_system_perm(sup, "EZD", "Odczyt")
    with Session(engine) as s:
        from models import SystemPermission
        sid2 = s.get(SystemPermission, pid2).system_id
    worker = api.mk_user(sup, "anna", ["viewer"], "Anna Pracownik")
    assert api.patch(f"/users/{worker}", token=sup,
                     json={"department_id": w["dep"]}).status_code == 200

    grant = [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"},
             {"system_id": sid2, "permission_id": pid2, "kind": "grant"}]
    rid = _complete(api, w, worker, grant, "grant")
    # Druga pozycja odmówiona (stan jak po odmowie na akceptacji wyższej / w IT).
    with Session(engine) as s:
        it = s.exec(select(RequestItem).where(RequestItem.request_id == rid)
                    .where(RequestItem.permission_id == pid2)).first()
        it.denied = True
        s.add(it); s.commit()

    kier = api.login("kier")
    held = api.get(f"/users/{worker}/permissions", token=sup).json()["permissions"]
    tree = api.get("/users/my-subtree", token=kier).json()
    assert [p["permission_id"] for p in _subtree_perms(tree, worker)] == [w["pid"]]
    assert [p["permission_id"] for p in held] == [w["pid"]]

    _complete(api, w, worker,
              [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "revoke"}], "revoke")
    tree = api.get("/users/my-subtree", token=kier).json()
    assert _subtree_perms(tree, worker) == []
    assert api.get(f"/users/{worker}/permissions", token=sup).json()["permissions"] == []


# ---------------------------------------------------------------------------
# 4. Dezaktywacja — powiadomienie; import z AD nie reaktywuje
# ---------------------------------------------------------------------------

def _stage_mails(jobs) -> set[str]:
    return {kw.get("to_address") for name, kw in jobs if name == "notify_workflow_stage"}


def test_deactivating_manager_notifies_new_responsible(api, monkeypatch):
    """logic 1: po dezaktywacji kierownika K wniosek na wyborze przechodzi do
    kierownika komórki nadrzędnej — ten dostaje powiadomienie."""
    w = _world(api)
    rid = _hr_request(api, w)
    assert api.node_type(rid, api.login("kier")) == "select_permissions"
    jobs = _capture_jobs(monkeypatch)
    r = api.patch(f"/users/{w['kid']}", token=w["sup"], json={"is_active": False})
    assert r.status_code == 200, r.text
    assert "kierP@t.local" in _stage_mails(jobs)


def _ldap_world(api, monkeypatch, *, enabled_in_ad: bool):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    dep = api.mk_department(sup, unit, None, name="D")
    with Session(engine) as s:
        cfg = s.exec(select(LdapSettings)).first() or LdapSettings()
        cfg.enabled = True; cfg.host = "x"; cfg.base_dn = "DC=t,DC=l"
        s.add(cfg)
        d = s.get(Department, dep); d.ldap_dn = "OU=D,DC=t,DC=l"; s.add(d)
        u = User(username="jan", roles='["viewer"]', auth_type=AuthType.ldap,
                 password_hash="!ldap-managed!", department_id=dep, is_active=True,
                 email="jan@t.local")
        s.add(u); s.commit(); uid = u.id
    import services.ldap_service as ls
    monkeypatch.setattr(ls, "fetch_ldap_users", lambda cfg, base: [{
        "dn": "CN=jan,OU=D,DC=t,DC=l", "parent_dn": "OU=D,DC=t,DC=l", "username": "jan",
        "full_name": "Jan Nowy", "email": None, "title": "",
        "is_enabled_in_ad": enabled_in_ad}])
    return sup, uid


def test_ldap_import_does_not_reactivate_account_disabled_in_szup(api, monkeypatch):
    """S6: konto wyłączone w SZUP (np. podejrzenie przejęcia) zostaje wyłączone."""
    sup, uid = _ldap_world(api, monkeypatch, enabled_in_ad=True)
    assert api.patch(f"/users/{uid}", token=sup, json={"is_active": False}).status_code == 200
    r = api.post("/users/ldap/import", token=sup, json={"usernames": ["jan"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reactivation_skipped"] == 1
    assert any("pominięto reaktywację" in d for d in body["details"])
    with Session(engine) as s:
        u = s.get(User, uid)
        assert u.is_active is False
        assert u.full_name == "Jan Nowy"     # pozostałe dane z AD aktualizowane


def test_ldap_import_deactivation_notifies_new_responsible(api, monkeypatch):
    w = _world(api)
    with Session(engine) as s:
        cfg = s.exec(select(LdapSettings)).first() or LdapSettings()
        cfg.enabled = True; cfg.host = "x"; cfg.base_dn = "DC=t,DC=l"
        s.add(cfg)
        d = s.get(Department, w["dep"]); d.ldap_dn = "OU=K,DC=t,DC=l"; s.add(d)
        u = s.get(User, w["kid"]); u.auth_type = AuthType.ldap; s.add(u)
        s.commit()
    import services.ldap_service as ls
    monkeypatch.setattr(ls, "fetch_ldap_users", lambda cfg, base: [{
        "dn": "CN=kier,OU=K,DC=t,DC=l", "parent_dn": "OU=K,DC=t,DC=l", "username": "kier",
        "full_name": "Jan Kier", "email": None, "title": "", "is_enabled_in_ad": False}])
    _hr_request(api, w)
    jobs = _capture_jobs(monkeypatch)
    r = api.post("/users/ldap/import", token=w["sup"], json={"usernames": ["kier"]})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(User, w["kid"]).is_active is False
    assert "kierP@t.local" in _stage_mails(jobs)


def test_ldap_import_skips_admin_accounts_for_plain_admin(api, monkeypatch):
    sup, uid = _ldap_world(api, monkeypatch, enabled_in_ad=False)
    with Session(engine) as s:
        u = s.get(User, uid); u.roles = '["admin"]'; s.add(u); s.commit()
    api.mk_user(sup, "adm", ["admin"])
    r = api.post("/users/ldap/import", token=api.login("adm"), json={"usernames": ["jan"]})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(User, uid).is_active is True


# ---------------------------------------------------------------------------
# 5. LDAPS / STARTTLS
# ---------------------------------------------------------------------------

class _Cfg:
    def __init__(self, **kw):
        self.host = "dc.example.local"
        self.port = 636
        self.use_ssl = True
        self.use_starttls = False
        self.tls_verify = True
        self.ca_cert_file = None
        self.bind_dn = "svc"
        self.base_dn = "DC=example,DC=local"
        self.bind_password_enc = None
        self.user_search_base = ""
        self.user_filter = "(sAMAccountName={username})"
        self.__dict__.update(kw)


def test_ldaps_verifies_certificate_by_default(tmp_path):
    from services.ldap_service import build_server
    server = build_server(_Cfg())
    assert server.ssl is True
    assert server.tls.validate == ssl.CERT_REQUIRED

    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    server = build_server(_Cfg(ca_cert_file=str(ca)))
    assert server.tls.ca_certs_file == str(ca)

    # Starsza baza (NULL) = weryfikacja włączona; jawne wyłączenie — CERT_NONE.
    assert build_server(_Cfg(tls_verify=None)).tls.validate == ssl.CERT_REQUIRED
    assert build_server(_Cfg(tls_verify=False)).tls.validate == ssl.CERT_NONE
    # STARTTLS: zwykły port, TLS z weryfikacją.
    server = build_server(_Cfg(use_ssl=False, use_starttls=True, port=389))
    assert server.ssl is False and server.tls.validate == ssl.CERT_REQUIRED


def test_ldap_password_never_sent_without_tls(monkeypatch):
    import ldap3
    from services import ldap_service as ls

    def _boom(*a, **kw):
        raise AssertionError("połączenie z LDAP bez TLS nie powinno powstać")

    monkeypatch.setattr(ldap3, "Connection", _boom)
    plain = _Cfg(use_ssl=False, port=389)
    with pytest.raises(ls.LdapInsecureError):
        ls.open_connection(plain, ls.build_server(plain), "CN=jan", "Haslo123!")
    assert ls.authenticate_ldap(plain, "jan", "Haslo123!") is False


def test_starttls_runs_before_bind(monkeypatch):
    import ldap3
    from services import ldap_service as ls
    seen = {}
    monkeypatch.setattr(ldap3, "Connection",
                        lambda server, **kw: seen.update(kw) or "conn")
    cfg = _Cfg(use_ssl=False, use_starttls=True, port=389)
    assert ls.open_connection(cfg, ls.build_server(cfg), "CN=jan", "x") == "conn"
    assert seen["auto_bind"] == ldap3.AUTO_BIND_TLS_BEFORE_BIND


_LDAP = {"enabled": True, "host": "dc1.example.local", "port": 636, "use_ssl": True,
         "base_dn": "DC=example,DC=local", "bind_dn": "svc",
         "user_search_base": "", "user_filter": "(sAMAccountName={username})"}


def test_ldap_settings_expose_tls_fields_and_clear_password(api, tmp_path):
    root = api.setup_superadmin()
    r = api.get("/settings/ldap", token=root).json()
    assert r["tls_verify"] is True and r["use_starttls"] is False and r["ca_cert_file"] is None

    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    r = api.put("/settings/ldap", token=root,
                json={**_LDAP, "ca_cert_file": str(ca), "bind_password": "Tajne123!"})
    assert r.status_code == 200, r.text
    assert r.json()["ca_cert_file"] == str(ca) and r.json()["has_password"] is True
    assert api.get("/settings/ldap", token=root).json()["ca_cert_file"] == str(ca)

    # Nieistniejący / względny plik CA i LDAPS+STARTTLS naraz — odrzucone.
    assert api.put("/settings/ldap", token=root,
                   json={**_LDAP, "ca_cert_file": "/brak/ca.pem"}).status_code == 400
    assert api.put("/settings/ldap", token=root,
                   json={**_LDAP, "ca_cert_file": "ca.pem"}).status_code == 400
    assert api.put("/settings/ldap", token=root,
                   json={**_LDAP, "use_starttls": True}).status_code == 400

    # S8: zmiana szyfrowania, portu, Base DN (konto bez domeny) lub weryfikacji
    # bez nowego hasła — hasło konta usługowego usunięte.
    base = {**_LDAP, "ca_cert_file": str(ca)}
    for change in ({"use_ssl": False, "port": 389}, {"port": 3269},
                   {"base_dn": "DC=inna,DC=local"}, {"tls_verify": False}):
        r = api.put("/settings/ldap", token=root, json={**base, "bind_password": "Tajne123!"})
        assert r.json()["has_password"] is True
        r = api.put("/settings/ldap", token=root, json={**base, **change})
        assert r.status_code == 200, r.text
        assert r.json()["has_password"] is False and r.json()["warning"], change


def test_health_warns_about_ldap_without_tls(api):
    root = api.setup_superadmin()

    def _check():
        checks = api.get("/settings/health", token=root).json()["checks"]
        return next((c for c in checks if c["key"] == "ldap_tls"), None)

    assert _check() is None    # LDAP wyłączony — bez ostrzeżenia
    api.put("/settings/ldap", token=root, json={**_LDAP, "use_ssl": False, "port": 389})
    c = _check()
    assert c and c["ok"] is False and "szyfrowania" in c["label"]
    api.put("/settings/ldap", token=root, json={**_LDAP, "tls_verify": False})
    c = _check()
    assert c and c["ok"] is False and "certyfikatu" in c["label"]
    api.put("/settings/ldap", token=root, json=_LDAP)
    assert _check()["ok"] is True


# ---------------------------------------------------------------------------
# 7. Parametry stronicowania
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/security/?limit=-1", "/security/?limit=0",
    "/audit/?limit=-1", "/audit/?offset=-1",
    "/registry/granted?limit=-1", "/registry/granted?offset=-1",
    "/snapshots?limit=-1", "/snapshots?offset=-5",
])
def test_negative_limit_and_offset_rejected(api, path):
    root = api.setup_superadmin()
    r = api.get(path, token=root)
    assert r.status_code == 422, (path, r.status_code, r.text[:200])


# ---------------------------------------------------------------------------
# 8. Import plików — limit rozmiaru
# ---------------------------------------------------------------------------

def test_permission_import_rejects_oversized_file(api):
    from routers.systems import MAX_IMPORT_BYTES
    root = api.setup_superadmin()
    sid, _pid = api.mk_system_perm(root, "Duzy", "X")
    r = api.post(f"/systems/{sid}/permissions/import/preview", token=root,
                 files={"file": ("lista.csv", b"a;b\n" * (MAX_IMPORT_BYTES // 4 + 10), "text/csv")})
    assert r.status_code == 413, r.text
