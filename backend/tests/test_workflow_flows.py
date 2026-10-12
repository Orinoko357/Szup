"""E2E: obieg wniosków — 1-stopniowy, 2-stopniowy, grant/revoke/change."""
from __future__ import annotations


def _base(api):
    """Wspólny setup: superadmin, HR(z jednostką), kierownik, IT, system+uprawnienie."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "Urząd", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kierownik")
    api.mk_user(sup, "it", ["it_staff"], "Informatyk")
    api.mk_user(sup, "hr", ["hr"], "Kadrowa", unit_ids=[unit])
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    hr = api.login("hr"); it = api.login("it"); kier = api.login("kier")
    return dict(sup=sup, unit=unit, kid=kid, hr=hr, it=it, kier=kier,
                sid=sid, pid=pid, rtype=rtype)


def test_single_stage_flow(api):
    b = _base(api)
    dep = api.mk_department(b["sup"], b["unit"], b["kid"],
                            requires_higher_approval=False, name="Wydział A")
    r = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Anna Nowak", "worker_position": "Ref",
        "unit_id": b["unit"], "department_id": dep, "items": [],
        "request_type_id": b["rtype"]})
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]

    assert api.node_type(rid, b["kier"]) == "select_permissions"
    r = api.post(f"/requests/{rid}/workflow/action", token=b["kier"], json={
        "action": "select",
        "items": [{"system_id": b["sid"], "permission_id": b["pid"]}]})
    assert r.status_code == 200, r.text
    # 1-stopniowy → higher_manager_approve pominięty → prosto do IT
    assert api.node_type(rid, b["it"]) == "it_execute"

    r = api.post(f"/requests/{rid}/workflow/action", token=b["it"], json={
        "action": "execute", "ad_username": "anowak"})
    assert r.status_code == 200, r.text
    det = api.get(f"/requests/{rid}", token=b["sup"]).json()
    assert det["status"] == "completed"


def test_two_stage_flow(api):
    b = _base(api)
    kidB = api.mk_user(b["sup"], "kierB", ["manager"], "Kier Nadrzędny")
    kierB = api.login("kierB")
    parent = api.mk_department(b["sup"], b["unit"], kidB,
                               requires_higher_approval=False, name="Nadrzędny")
    child = api.mk_department(b["sup"], b["unit"], b["kid"],
                              requires_higher_approval=True, name="Referat",
                              parent_dept_id=parent)
    r = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Bartek Kowal", "unit_id": b["unit"],
        "department_id": child, "items": [], "request_type_id": b["rtype"]})
    rid = r.json()["id"]
    assert api.node_type(rid, b["kier"]) == "select_permissions"
    api.post(f"/requests/{rid}/workflow/action", token=b["kier"], json={
        "action": "select",
        "items": [{"system_id": b["sid"], "permission_id": b["pid"]}]})
    # 2-stopniowy → NIE pomija wyższego rzędu
    assert api.node_type(rid, kierB) == "higher_manager_approve"
    r = api.post(f"/requests/{rid}/workflow/action", token=kierB,
                 json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, b["it"]) == "it_execute"
    api.post(f"/requests/{rid}/workflow/action", token=b["it"],
             json={"action": "execute", "ad_username": "bkowal"})
    assert api.get(f"/requests/{rid}", token=b["sup"]).json()["status"] == "completed"


def _run_to_completion(api, b, dep, kind, items, worker_user_id=None):
    body = {"worker_name": "X", "unit_id": b["unit"], "department_id": dep,
            "items": items, "request_type_id": b["rtype"], "kind": kind}
    if worker_user_id is not None:
        body["worker_user_id"] = worker_user_id
    r = api.post("/requests/", token=b["hr"], json=body)
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    # kierownik potwierdza wybór (jeśli obieg czeka na select)
    if api.node_type(rid, b["kier"]) == "select_permissions":
        api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
                 json={"action": "select", "items": items})
    api.post(f"/requests/{rid}/workflow/action", token=b["it"],
             json={"action": "execute", "ad_username": "xworker"})
    return rid


def test_grant_revoke_change_effective_permissions(api):
    b = _base(api)
    dep = api.mk_department(b["sup"], b["unit"], b["kid"], name="Wydz")
    sid, pA = b["sid"], b["pid"]
    sid2, pB = api.mk_system_perm(b["sup"], "System2", "B")  # inny system/uprawn.

    # 1) NADANIE A
    rid1 = _run_to_completion(api, b, dep, "grant",
                              [{"system_id": sid, "permission_id": pA, "kind": "grant"}])
    det = api.get(f"/requests/{rid1}", token=b["sup"]).json()
    worker_id = det.get("worker_user_id")
    assert worker_id, "wniosek powinien dowiązać konto pracownika"

    eff = api.get(f"/users/{worker_id}/permissions", token=b["sup"]).json()
    perms = {(p["permission_name"]) for p in eff["permissions"]}
    assert "Dostęp" in perms  # pA

    # 2) ZMIANA: odbierz A, nadaj B (stan docelowy)
    _run_to_completion(api, b, dep, "change", [
        {"system_id": sid, "permission_id": pA, "kind": "revoke"},
        {"system_id": sid2, "permission_id": pB, "kind": "grant"},
    ], worker_user_id=worker_id)
    eff = api.get(f"/users/{worker_id}/permissions", token=b["sup"]).json()
    perms = {p["permission_name"] for p in eff["permissions"]}
    assert "B" in perms and "Dostęp" not in perms

    # 3) PONOWNE NADANIE A po odebraniu — chronologia działa
    _run_to_completion(api, b, dep, "grant",
                       [{"system_id": sid, "permission_id": pA, "kind": "grant"}],
                       worker_user_id=worker_id)
    eff = api.get(f"/users/{worker_id}/permissions", token=b["sup"]).json()
    perms = {p["permission_name"] for p in eff["permissions"]}
    assert "Dostęp" in perms and "B" in perms
