"""Decyzje 3.9 — role i uprawnienia:
  1. rola „hr” zniesiona; kadry = komórka kadrowa z pełnym zakresem jednostek,
  2. rozpatrywanie zmian nazwiska tylko przez IT; superadmin bez ról operacyjnych,
  3. LDAP bez TLS działa (rekomendacja w liście kontrolnej, poziomy `level`),
  4. neutralizacja formuł w eksporcie CSV (`csv_safe`).
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlmodel import Session, select

import database
from database import engine
from models import AuditLog, User
from tests.conftest import PW


def _roles(uid: int) -> list[str]:
    with Session(engine) as s:
        return json.loads(s.get(User, uid).roles)


def _world(api):
    sup = api.setup_superadmin("root")
    unit_a = api.mk_unit(sup, "Jednostka A", "A")
    unit_b = api.mk_unit(sup, "Jednostka B", "B")
    kid_a = api.mk_user(sup, "kierA", ["manager"], "Kierownik A")
    kid_b = api.mk_user(sup, "kierB", ["manager"], "Kierownik B")
    dep_a = api.mk_department(sup, unit_a, kid_a, name="Wydział A")
    dep_b = api.mk_department(sup, unit_b, kid_b, name="Wydział B")
    # Pracownik kadr: komórka kadrowa w jednostce A (bez żadnych UserUnit).
    hr_id = api.mk_user(sup, "kadrowa", ["hr"], "Anna Kadrowa", unit_ids=[unit_a])
    worker = api.mk_user(sup, "pracownikb", ["viewer"], "Bogdan Pracownik")
    with Session(engine) as s:
        u = s.get(User, worker)
        u.department_id = dep_b
        s.add(u); s.commit()
    return dict(sup=sup, unit_a=unit_a, unit_b=unit_b, dep_a=dep_a, dep_b=dep_b,
                hr_id=hr_id, worker=worker, rtype=api.request_type(sup, "NEW_EMP"))


# ---------------------------------------------------------------------------
# 1. Rola „hr” zniesiona
# ---------------------------------------------------------------------------

def test_hr_role_rejected_on_create_and_update(api):
    sup = api.setup_superadmin()
    r = api.post("/users/", token=sup, json={
        "username": "nowa", "password": PW, "roles": ["hr"]})
    assert r.status_code == 400, r.text
    assert "komórki kadrowej" in r.json()["detail"]
    uid = api.mk_user(sup, "jan", ["viewer"])
    r = api.patch(f"/users/{uid}", token=sup, json={"roles": ["viewer", "hr"]})
    assert r.status_code == 400, r.text
    assert _roles(uid) == ["viewer"]


def test_migration_strips_hr_role_and_audits(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup)
    hr_dept = api.hr_department(unit)
    a = api.mk_user(sup, "hr_poza", ["manager"])
    b = api.mk_user(sup, "hr_w_kadrach", ["viewer"])
    c = api.mk_user(sup, "bez_hr", ["it_staff"])
    with Session(engine) as s:
        s.exec(text('UPDATE "user" SET roles = \'["hr","manager"]\' WHERE id = :i').bindparams(i=a))
        s.exec(text('UPDATE "user" SET roles = \'["hr"]\', department_id = :d WHERE id = :i')
               .bindparams(d=hr_dept, i=b))
        s.commit()

    assert database._strip_hr_role() == ["hr_poza", "hr_w_kadrach"]
    assert _roles(a) == ["manager"]
    assert _roles(b) == ["viewer"]
    assert _roles(c) == ["it_staff"]
    with Session(engine) as s:
        entry = s.exec(select(AuditLog).where(AuditLog.action == "user.hr_role_removed")).one()
    details = json.loads(entry.details)
    assert details["usernames"] == ["hr_poza", "hr_w_kadrach"]
    assert details["lost_hr_capability"] == ["hr_poza"]
    # Idempotentna — drugi przebieg nic nie zmienia i nie dubluje audytu.
    assert database._strip_hr_role() == []
    with Session(engine) as s:
        assert len(s.exec(select(AuditLog)
                          .where(AuditLog.action == "user.hr_role_removed")).all()) == 1
    # Członek komórki kadrowej zachowuje efektywną rolę „hr”.
    assert "hr" in api.get("/auth/me", token=api.login("hr_w_kadrach")).json()["roles"]
    assert "hr" not in api.get("/auth/me", token=api.login("hr_poza")).json()["roles"]


def test_hr_department_member_sees_all_units(api):
    w = _world(api)
    login = api.post("/auth/login", json={"username": "kadrowa", "password": PW}).json()
    assert "hr" in login["roles"]
    tok = login["access_token"]
    assert "hr" in api.get("/auth/me", token=tok).json()["roles"]
    # Zapisane role konta nie zawierają „hr”.
    assert "hr" not in _roles(w["hr_id"])

    # Wyszukiwanie i lista pracowników — także w obcej jednostce B.
    found = api.get("/users/search", token=tok, params={"q": "bogdan"}).json()
    assert [u["username"] for u in found] == ["pracownikb"]
    assert api.get(f"/users/by-department/{w['dep_b']}", token=tok).status_code == 200

    # Wniosek dla jednostki B (komórka kadrowa jest w A).
    r = api.post("/requests/", token=tok, json={
        "worker_name": "Nowy B", "unit_id": w["unit_b"], "department_id": w["dep_b"],
        "items": [], "request_type_id": w["rtype"]})
    assert r.status_code == 201, r.text


def test_user_units_no_longer_writable(api):
    w = _world(api)
    # unit_ids w żądaniu jest ignorowane — przypisań kadr już się nie zapisuje.
    r = api.patch(f"/users/{w['hr_id']}", token=w["sup"], json={"unit_ids": [w["unit_b"]]})
    assert r.status_code == 200, r.text
    assert r.json()["unit_ids"] == []


# ---------------------------------------------------------------------------
# 2. IT-only operacje, superadmin bez ról operacyjnych
# ---------------------------------------------------------------------------

def _name_change(api, token) -> int:
    r = api.post("/name-changes", token=token, json={"requested_full_name": "Nowe Nazwisko"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_admin_cannot_resolve_name_change_but_admin_with_it_staff_can(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "adm", ["admin"])
    api.mk_user(sup, "admit", ["admin", "it_staff"])
    api.mk_user(sup, "jan", ["viewer"])
    nc = _name_change(api, api.login("jan"))
    body = {"action": "apply"}
    for who in ("adm", "root"):
        tok = api.login(who) if who != "root" else sup
        r = api.post(f"/name-changes/{nc}/resolve", token=tok, json=body)
        assert r.status_code == 403, (who, r.text)
    # Podgląd kolejki admin nadal ma.
    assert api.get("/name-changes", token=api.login("adm")).status_code == 200
    r = api.post(f"/name-changes/{nc}/resolve", token=api.login("admit"), json=body)
    assert r.status_code == 200, r.text


def test_superadmin_cannot_hold_operational_roles(api):
    sup = api.setup_superadmin()
    for roles in (["superadmin", "manager"], ["superadmin", "it_staff"]):
        r = api.post("/users/", token=sup, json={
            "username": "sa2", "password": PW, "roles": roles})
        assert r.status_code == 400, r.text
    uid = api.mk_user(sup, "sa3", ["superadmin"])
    r = api.patch(f"/users/{uid}", token=sup, json={"roles": ["superadmin", "it_staff"]})
    assert r.status_code == 400, r.text
    # Admin z rolą IT — dozwolony.
    uid2 = api.mk_user(sup, "admit", ["admin", "it_staff", "manager"])
    assert set(_roles(uid2)) == {"admin", "it_staff", "manager"}


def test_health_warns_about_superadmin_with_operational_roles(api):
    sup = api.setup_superadmin()

    def _check():
        checks = api.get("/settings/health", token=sup).json()["checks"]
        return next(c for c in checks if c["key"] == "superadmin_operational")

    c = _check()
    assert c["ok"] is True and c["level"] == "warning"
    with Session(engine) as s:
        s.exec(text('UPDATE "user" SET roles = \'["superadmin","manager"]\' '
                    'WHERE username = \'root\''))
        s.commit()
    c = _check()
    assert c["ok"] is False and "root" in c["detail"]


# ---------------------------------------------------------------------------
# 3. LDAP bez TLS — rekomendacja, nie blokada
# ---------------------------------------------------------------------------

def test_plain_ldap_open_connection_does_not_raise(monkeypatch):
    import ldap3
    from models import LdapSettings
    from services.ldap_service import build_server, open_connection
    seen = {}
    monkeypatch.setattr(ldap3, "Connection", lambda server, **kw: seen.update(kw) or "conn")
    cfg = LdapSettings(host="dc.local", port=389, use_ssl=False)
    assert open_connection(cfg, build_server(cfg), "svc", "haslo") == "conn"
    assert seen["password"] == "haslo"


_LDAP = {"enabled": True, "host": "dc.local", "port": 389, "use_ssl": False,
         "base_dn": "DC=wods,DC=local", "bind_dn": "svc"}


def test_health_levels_and_ldap_recommendation(api):
    root = api.setup_superadmin()
    r = api.put("/settings/ldap", token=root, json={**_LDAP, "allow_insecure": True})
    assert r.status_code == 200, r.text
    assert "allow_insecure" not in r.json()
    checks = api.get("/settings/health", token=root).json()["checks"]
    assert all(c["level"] in ("required", "warning", "recommendation") for c in checks)
    by_key = {c["key"]: c for c in checks}
    assert by_key["ldap"]["level"] == "required"
    tls = by_key["ldap_tls"]
    assert tls["ok"] is False and tls["level"] == "recommendation"
    assert "Zalecamy" in tls["detail"]
    api.put("/settings/ldap", token=root, json={**_LDAP, "use_ssl": True, "port": 636,
                                                 "tls_verify": False})
    tls = {c["key"]: c for c in api.get("/settings/health", token=root).json()["checks"]}["ldap_tls"]
    assert tls["ok"] is False and tls["level"] == "recommendation"


# ---------------------------------------------------------------------------
# 4. CSV — neutralizacja formuł
# ---------------------------------------------------------------------------

def test_csv_safe():
    from services.csv_utils import csv_safe, csv_safe_row
    for v in ("=1+1", "+48", "-2", "@SUM(A1)", "\tx", "\rx", "  =HYPERLINK()"):
        assert csv_safe(v) == "'" + v
    for v in ("Jan Kowalski", "", "a=b", "  tekst"):
        assert csv_safe(v) == v
    assert csv_safe(5) == 5 and csv_safe(None) is None
    assert csv_safe_row(["=x", 1]) == ["'=x", 1]
