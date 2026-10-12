"""E2E: autoryzacja — Wariant A (H5), IDOR (H1/H2), scoping HR (M3), tryb testowy (C2)."""
from __future__ import annotations

import os

from conftest import PW


def _world(api):
    sup = api.setup_superadmin("root")
    unit = api.mk_unit(sup, "U", "U")
    adm = api.mk_user(sup, "adm", ["admin"], "Admin")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    hrid = api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    tokens = {r: api.login(r) for r in ("adm", "kier", "it", "hr")}
    return dict(sup=sup, unit=unit, adm_id=adm, kid=kid, hrid=hrid, dep=dep,
                sid=sid, pid=pid, rtype=rtype, **tokens)


# --- H5 / Wariant A ---------------------------------------------------------

def test_admin_cannot_create_request(api):
    w = _world(api)
    r = api.post("/requests/", token=w["adm"], json={
        "worker_name": "P", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]})
    assert r.status_code == 403


def test_admin_cannot_act_in_workflow_but_operational_roles_can(api):
    w = _world(api)
    rid = api.post("/requests/", token=w["hr"], json={
        "worker_name": "P", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]}).json()["id"]
    # admin nie może wybrać uprawnień
    r = api.post(f"/requests/{rid}/workflow/action", token=w["adm"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 403
    # kierownik może
    r = api.post(f"/requests/{rid}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200
    # admin nie może realizować, IT może
    assert api.post(f"/requests/{rid}/workflow/action", token=w["adm"],
                    json={"action": "execute", "ad_username": "p"}).status_code == 403
    assert api.post(f"/requests/{rid}/workflow/action", token=w["it"],
                    json={"action": "execute", "ad_username": "p"}).status_code == 200


def test_superadmin_breakglass_can_act(api):
    w = _world(api)
    rid = api.post("/requests/", token=w["hr"], json={
        "worker_name": "P", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]}).json()["id"]
    r = api.post(f"/requests/{rid}/workflow/action", token=w["sup"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200


def test_admin_config_access_it_no_admin_pages(api):
    w = _world(api)
    # admin ma dostęp do konfiguracji
    assert api.get("/settings/app", token=w["adm"]).status_code == 200
    assert api.get("/users/", token=w["adm"]).status_code == 200
    # IT nie ma dostępu do stron administracyjnych
    assert api.get("/settings/app", token=w["it"]).status_code == 403
    assert api.get("/audit/", token=w["it"]).status_code in (403, 404)
    assert api.get("/workflow-templates/", token=w["it"]).status_code == 403
    # ...ale IT ma dostęp do rejestru oprogramowania
    assert api.get("/systems/", token=w["it"]).status_code == 200


# --- H1: IDOR by-department -------------------------------------------------

def test_by_department_scoping_hr(api):
    w = _world(api)
    other_unit = api.mk_unit(w["sup"], "Inna", "I")
    other_kier = api.mk_user(w["sup"], "kier2", ["manager"], "K2")
    other_dep = api.mk_department(w["sup"], other_unit, other_kier, name="Obca")
    # HR przypisany tylko do w["unit"] — nie widzi pracowników obcej jednostki
    r = api.get(f"/users/by-department/{other_dep}", token=w["hr"])
    assert r.status_code == 403
    # ale widzi swoją komórkę
    assert api.get(f"/users/by-department/{w['dep']}", token=w["hr"]).status_code == 200


def test_by_department_scoping_manager(api):
    w = _world(api)
    other_kier = api.mk_user(w["sup"], "kier2", ["manager"], "K2")
    other_dep = api.mk_department(w["sup"], w["unit"], other_kier, name="Cudza")
    # kier zarządza tylko w["dep"], nie cudzą komórką
    assert api.get(f"/users/by-department/{other_dep}", token=w["kier"]).status_code == 403
    assert api.get(f"/users/by-department/{w['dep']}", token=w["kier"]).status_code == 200


# --- H2: IDOR deputies (tylko admin) ----------------------------------------

def test_deputies_admin_only(api):
    w = _world(api)
    assert api.get(f"/units/departments/{w['dep']}/deputies", token=w["it"]).status_code == 403
    assert api.get(f"/units/departments/{w['dep']}/deputies", token=w["adm"]).status_code == 200


# --- M3: HR bez jednostki nie utworzy wniosku -------------------------------

def test_hr_without_unit_cannot_create(api):
    w = _world(api)
    api.mk_user(w["sup"], "hr2", ["hr"], "HR bez jednostki")  # brak unit_ids
    hr2 = api.login("hr2")
    r = api.post("/requests/", token=hr2, json={
        "worker_name": "P", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]})
    assert r.status_code == 403


# --- M1: FK egzekwowane — brak osieroceń ------------------------------------

def test_cannot_delete_user_referenced_by_department(api):
    w = _world(api)
    # kier jest kierownikiem w["dep"] → nie można go usunąć (FK RESTRICT → 409)
    r = api.delete(f"/users/{w['kid']}", token=w["sup"])
    assert r.status_code == 409, r.text


def test_cannot_delete_unit_with_requests(api):
    w = _world(api)
    # utwórz wniosek wiążący jednostkę, potem próba usunięcia jednostki
    api.post("/requests/", token=w["hr"], json={
        "worker_name": "P", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]})
    # najpierw i tak blokuje "posiada wydziały" (400) — sprawdźmy że NIE 500/204
    r = api.delete(f"/units/{w['unit']}", token=w["adm"])
    assert r.status_code in (400, 409), r.text


# --- C2: tryb testowy wymaga zmiennej środowiskowej -------------------------

def test_test_mode_requires_env(api, monkeypatch):
    w = _world(api)
    # włącz flagę w bazie (endpoint to PUT /settings/app)
    r = api.put("/settings/app", token=w["adm"], json={"test_mode": True})
    assert r.status_code == 200, r.text
    # bez env — status pokazuje test_mode False i login/test 403
    monkeypatch.delenv("SZUP_ALLOW_TEST_MODE", raising=False)
    assert api.get("/auth/status").json()["test_mode"] is False
    r = api.post("/auth/login/test", json={"username": "hr"})
    assert r.status_code == 403
    # z env — działa dla konta nieuprzywilejowanego
    monkeypatch.setenv("SZUP_ALLOW_TEST_MODE", "1")
    assert api.get("/auth/status").json()["test_mode"] is True
    assert api.post("/auth/login/test", json={"username": "hr"}).status_code == 200
    # ...ale NIE dla konta administracyjnego (nawet w trybie testowym)
    assert api.post("/auth/login/test", json={"username": "adm"}).status_code == 403
    assert api.post("/auth/login/test", json={"username": "root"}).status_code == 403
