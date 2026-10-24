"""E2E: kształt odpowiedzi i zakresy widoczności, których nie pokrywają inne
testy (kondycja konfiguracji, pulpit, filtr `active`, dostęp twórcy wniosku)."""
from __future__ import annotations


def _world(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    rtype = api.request_type(sup, "NEW_EMP")
    return dict(sup=sup, unit=unit, dep=dep, rtype=rtype)


def _new_request(api, w, token, name="Ola Nowa"):
    r = api.post("/requests/", token=token, json={
        "worker_name": name, "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": w["rtype"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_settings_health_shape_for_admin(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "adm", ["admin"], "Admin")
    api.mk_user(sup, "kier", ["manager"], "Kier")

    r = api.get("/settings/health", token=api.login("adm"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"checks", "issues"}
    assert body["checks"] and body["issues"]
    for c in body["checks"]:
        assert {"key", "label", "ok", "detail", "link"} <= set(c), c
        assert isinstance(c["ok"], bool)
    for i in body["issues"]:
        assert {"key", "label", "count", "link"} <= set(i), i
        assert isinstance(i["count"], int)
    keys = {c["key"] for c in body["checks"]}
    assert {"ldap", "structure", "request_types", "it_step", "helpdesk"} <= keys

    # tylko dla administratora
    assert api.get("/settings/health", token=api.login("kier")).status_code == 403


def test_dashboard_entries_have_step_since_and_waiting_for(api):
    w = _world(api)
    rid = _new_request(api, w, api.login("hr"))

    dash = api.get("/requests/dashboard", token=api.login("kier")).json()
    entry = next(e for e in dash["pending_approvals_list"] if e["request_id"] == rid)
    assert entry["node_type"] == "select_permissions"
    assert entry["step_since"]                       # od kiedy czeka na kroku
    assert "Jan Kierownik" in (entry["waiting_for"] or "")
    assert dash["pending_prepare_count"] >= 1


def test_list_requests_active_filter_hides_closed(api):
    w = _world(api)
    hr = api.login("hr")
    open_id = _new_request(api, w, hr, "Otwarty")
    closed_id = _new_request(api, w, hr, "Odrzucony")
    r = api.post(f"/requests/{closed_id}/workflow/action", token=api.login("kier"),
                 json={"action": "reject", "comment": "nie"})
    assert r.status_code == 200, r.text

    all_ids = {x["id"] for x in api.get("/requests/", token=hr).json()}
    active_ids = {x["id"] for x in api.get("/requests/?active=true", token=hr).json()}
    assert {open_id, closed_id} <= all_ids
    assert open_id in active_ids and closed_id not in active_ids


def test_creator_sees_own_request_others_do_not(api):
    w = _world(api)
    api.mk_user(w["sup"], "hr2", ["hr"], "HR Druga", unit_ids=[w["unit"]])
    other_unit = api.mk_unit(w["sup"], "Inna", "INNA")
    kid2 = api.mk_user(w["sup"], "kier2", ["manager"], "Kier Obcy")
    api.mk_department(w["sup"], other_unit, kid2, name="Obca")

    rid = _new_request(api, w, api.login("hr"))

    assert api.get(f"/requests/{rid}", token=api.login("hr")).status_code == 200
    assert api.get(f"/requests/{rid}/workflow", token=api.login("hr")).status_code == 200
    # inna kadrowa (nie twórca) i kierownik spoza zakresu — brak dostępu
    # 3.11 (N-4): cudzy wniosek — 404, jak nieistniejący.
    assert api.get(f"/requests/{rid}", token=api.login("hr2")).status_code == 404
    assert api.get(f"/requests/{rid}", token=api.login("kier2")).status_code == 404
