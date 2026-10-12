"""E2E: ochrona przed podwójnym krokiem (H4) — optymistyczna kontrola węzła."""
from __future__ import annotations


def _setup(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    hr = api.login("hr"); it = api.login("it"); kier = api.login("kier")
    rid = api.post("/requests/", token=hr, json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    return dict(sup=sup, rid=rid, kier=kier, it=it, sid=sid, pid=pid)


def test_stale_expected_node_id_conflicts(api):
    s = _setup(api)
    wf = api.get(f"/requests/{s['rid']}/workflow", token=s["kier"]).json()
    node_now = wf["current_node_id"]

    # pierwszy select przechodzi
    r = api.post(f"/requests/{s['rid']}/workflow/action", token=s["kier"], json={
        "action": "select", "expected_node_id": node_now,
        "items": [{"system_id": s["sid"], "permission_id": s["pid"]}]})
    assert r.status_code == 200, r.text

    # druga akcja z NIEAKTUALNYM expected_node_id (obieg już przeszedł) → 409
    r2 = api.post(f"/requests/{s['rid']}/workflow/action", token=s["kier"], json={
        "action": "select", "expected_node_id": node_now,
        "items": [{"system_id": s["sid"], "permission_id": s["pid"]}]})
    assert r2.status_code == 409, r2.text


def test_action_on_wrong_node_rejected(api):
    s = _setup(api)
    # IT próbuje 'execute', ale obieg jest na select_permissions → walidacja akcji/węzła
    r = api.post(f"/requests/{s['rid']}/workflow/action", token=s["it"], json={
        "action": "execute", "ad_username": "p"})
    assert r.status_code in (400, 403)
