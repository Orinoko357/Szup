"""E2E: uprawnienie z kontrolką „lista wielokrotnego wyboru"."""
from __future__ import annotations

PERM = {"permission_name": "Moduły", "input_type": "multiselect",
        "input_required": True, "options": ["FK", "KP", "ŚT", "JPK"]}


def _world(api, perm=PERM):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid = api.post("/systems/", token=sup, json={
        "name": "FK", "all_units": True}).json()["id"]
    pid = api.post(f"/systems/{sid}/permissions", token=sup,
                   json=perm).json()["id"]
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    return dict(sup=sup, rid=rid, sid=sid, pid=pid, kier=api.login("kier"), it=api.login("it"))


def _select(api, w, value):
    return api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Moduły": value}}]})


def test_multiple_values_are_saved(api):
    w = _world(api)
    assert _select(api, w, "FK, JPK").status_code == 200
    det = api.get(f"/requests/{w['rid']}", token=w["it"]).json()
    assert det["items"][0]["custom_values"]["Moduły"] == "FK, JPK"


def test_values_normalized_to_definition_order(api):
    """Kolejność zapisu wynika z definicji pola, nie z kolejności klikania."""
    w = _world(api)
    assert _select(api, w, "JPK,FK").status_code == 200
    det = api.get(f"/requests/{w['rid']}", token=w["it"]).json()
    assert det["items"][0]["custom_values"]["Moduły"] == "FK, JPK"


def test_duplicates_are_collapsed(api):
    w = _world(api)
    assert _select(api, w, "FK, FK, KP").status_code == 200
    det = api.get(f"/requests/{w['rid']}", token=w["it"]).json()
    assert det["items"][0]["custom_values"]["Moduły"] == "FK, KP"


def test_value_outside_options_rejected(api):
    w = _world(api)
    r = _select(api, w, "FK, Admin")
    assert r.status_code == 400 and "Admin" in r.text


def test_required_multiselect_blocks_empty(api):
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 400 and "Moduły" in r.text


def test_optional_multiselect_can_be_empty(api):
    w = _world(api, {"permission_name": "Moduły", "input_type": "multiselect",
                     "input_required": False, "options": ["FK", "KP"]})
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200, r.text
