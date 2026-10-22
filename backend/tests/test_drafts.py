"""E2E: wersje robocze kierownika komórki i przejęcie wniosku przez przełożonego."""
from __future__ import annotations

from sqlmodel import Session, select

from database import engine
from models import AuditLog, RequestItem


def _world(api):
    """Komórka K (własny kierownik `kier`) pod komórką P (`kierP`), IT, admin, HR,
    oraz komórka B bez kierownika pod P."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "adm", ["admin"], "Admin")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent)
    nomgr = api.mk_department(sup, unit, None, name="B", parent_dept_id=parent)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    sid2, pid2 = api.mk_system_perm(sup, "Kadry", "Zapis")
    rtype = api.request_type(sup, "NEW_EMP")
    return dict(sup=sup, unit=unit, dep=dep, nomgr=nomgr, parent=parent,
                sid=sid, pid=pid, sid2=sid2, pid2=pid2, rtype=rtype)


def _create(api, w, token, dep=None, items=None, **extra):
    return api.post("/requests/", token=token, json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"],
        "department_id": dep or w["dep"], "request_type_id": w["rtype"],
        "items": items or [], **extra})


def _items(rid):
    with Session(engine) as s:
        return [(i.system_id, i.permission_id) for i in
                s.exec(select(RequestItem).where(RequestItem.request_id == rid)).all()]


def _ids(api, token, **params):
    return {x["id"] for x in api.get("/requests/", token=token, params=params).json()}


def test_draft_create_hidden_from_it_and_admin_visible_to_circle(api):
    w = _world(api)
    kier = api.login("kier")
    r = _create(api, w, kier, items=[{"system_id": w["sid"], "permission_id": w["pid"]}],
                draft=True)
    assert r.status_code == 201, r.text
    body = r.json()
    rid = body["id"]
    # Bez automatycznego wyboru — zostaje u kierownika jako wersja robocza.
    assert body["current_node_type"] == "select_permissions"
    assert body["draft_saved_at"] and body["is_draft"] is True and body["manager_stage"] is True
    assert body["can_act"] is True and body["can_take_over"] is False
    assert body["taken_over_by_id"] is None and body["taken_over_at"] is None
    assert _items(rid) == [(w["sid"], w["pid"])]

    it, adm = api.login("it"), api.login("adm")
    for tok in (it, adm):
        assert rid not in _ids(api, tok)
        assert rid not in _ids(api, tok, scope="it")
        g = api.get(f"/requests/{rid}", token=tok)
        assert g.status_code == 403
        assert "roboczy" in g.json()["detail"]
        assert api.get(f"/requests/{rid}/workflow", token=tok).status_code == 403

    # Superadmin i twórca/kierownik widzą.
    assert rid in _ids(api, w["sup"])
    assert api.get(f"/requests/{rid}", token=kier).status_code == 200

    # Przełożony widzi tylko do odczytu, z możliwością przejęcia.
    kierP = api.login("kierP")
    row = next(x for x in api.get("/requests/", token=kierP,
                                  params={"scope": "manager", "active": True}).json()
               if x["id"] == rid)
    assert row["can_act"] is False and row["can_take_over"] is True and row["is_draft"] is True


def test_draft_create_by_hr_is_rejected_and_hr_request_visible_to_creator(api):
    w = _world(api)
    hr = api.login("hr")
    r = _create(api, w, hr, draft=True)
    assert r.status_code == 400
    assert "kierownik komórki" in r.json()["detail"]
    assert api.get("/requests/", token=w["sup"]).json() == []

    r = _create(api, w, hr, items=[{"system_id": w["sid"], "permission_id": w["pid"]}])
    rid = r.json()["id"]
    assert r.json()["manager_stage"] is True and r.json()["is_draft"] is False
    assert api.get(f"/requests/{rid}", token=hr).status_code == 200
    assert rid in _ids(api, hr)
    assert api.get(f"/requests/{rid}", token=api.login("it")).status_code == 403


def test_draft_save_replaces_items_without_advancing(api):
    w = _world(api)
    rid = _create(api, w, api.login("hr"),
                  items=[{"system_id": w["sid"], "permission_id": w["pid"]}]).json()["id"]
    kier = api.login("kier")
    r = api.post(f"/requests/{rid}/draft", token=kier, json={
        "items": [{"system_id": w["sid2"], "permission_id": w["pid2"]}],
        "comment": "Do uzupełnienia jutro"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["current_node_type"] == "select_permissions"
    assert out["is_draft"] is True and out["draft_saved_at"]
    assert out["manager_comment"] == "Do uzupełnienia jutro"
    assert [(i["system_id"], i["permission_id"]) for i in out["items"]] == [(w["sid2"], w["pid2"])]
    assert _items(rid) == [(w["sid2"], w["pid2"])]
    assert api.node_type(rid, kier) == "select_permissions"

    # Pusta wersja robocza na wniosku z pozycjami wymaga świadomego potwierdzenia.
    r = api.post(f"/requests/{rid}/draft", token=kier, json={"items": []})
    assert r.status_code == 400
    assert _items(rid) == [(w["sid2"], w["pid2"])]
    r = api.post(f"/requests/{rid}/draft", token=kier, json={"items": [], "allow_empty": True})
    assert r.status_code == 200, r.text
    assert _items(rid) == []

    with Session(engine) as s:
        row = s.exec(select(AuditLog).where(AuditLog.action == "request.draft_saved")).first()
        assert row
        # Dziennik (dostępny dla administratora) nie zawiera treści wersji roboczej.
        assert "permission_id" not in (row.details or "")

    # Osoby spoza kręgu (IT) i przełożony bez przejęcia nie zapiszą wersji roboczej.
    assert api.post(f"/requests/{rid}/draft", token=api.login("it"),
                    json={"items": []}).status_code == 403
    assert api.post(f"/requests/{rid}/draft", token=api.login("kierP"),
                    json={"items": []}).status_code == 403


def test_superior_must_take_over_and_own_manager_is_locked_out(api):
    w = _world(api)
    rid = _create(api, w, api.login("hr")).json()["id"]
    kier, kierP = api.login("kier"), api.login("kierP")
    sel = {"action": "select", "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]}

    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json=sel)
    assert r.status_code == 403
    assert "przejmij" in r.json()["detail"].lower()

    # Kierownik komórki nie może „przejąć" własnego wniosku.
    assert api.post(f"/requests/{rid}/take-over", token=kier).status_code == 403
    # IT nie widzi wniosku → 403.
    assert api.post(f"/requests/{rid}/take-over", token=api.login("it")).status_code == 403

    r = api.post(f"/requests/{rid}/take-over", token=kierP)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["taken_over_by_name"] == "Anna Przełożona" and out["taken_over_at"]
    assert out["can_act"] is True and out["can_take_over"] is False
    assert "items" in out
    # Ponowne przejęcie → 409.
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 409

    # Kierownik komórki widzi wniosek, ale nie może działać.
    det = api.get(f"/requests/{rid}", token=kier).json()
    assert det["can_act"] is False
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json=sel)
    assert r.status_code == 403
    assert "Anna Przełożona" in r.json()["detail"]
    assert api.post(f"/requests/{rid}/draft", token=kier, json={"items": []}).status_code == 403

    # Przejmujący zapisuje roboczo i wysyła.
    assert api.post(f"/requests/{rid}/draft", token=kierP, json={"items": []}).status_code == 200
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json=sel)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kierP) == "it_execute"
    # Historia przejęcia zostaje.
    det = api.get(f"/requests/{rid}", token=api.login("it")).json()
    assert det["taken_over_by_name"] == "Anna Przełożona"
    assert det["manager_stage"] is False and det["is_draft"] is False

    with Session(engine) as s:
        assert s.exec(select(AuditLog).where(AuditLog.action == "request.taken_over")).first()


def test_department_without_manager_superior_acts_directly(api):
    w = _world(api)
    rid = _create(api, w, api.login("hr"), dep=w["nomgr"]).json()["id"]
    kierP = api.login("kierP")
    det = api.get(f"/requests/{rid}", token=kierP).json()
    assert det["manager_stage"] is False and det["can_take_over"] is False
    assert det["can_act"] is True
    # Brak etapu roboczego → IT widzi wniosek jak dotąd.
    assert api.get(f"/requests/{rid}", token=api.login("it")).status_code == 200
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "select", "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kierP) == "it_execute"
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 409


def test_send_after_draft_makes_request_visible_to_it(api):
    w = _world(api)
    kier, it = api.login("kier"), api.login("it")
    rid = _create(api, w, kier, items=[{"system_id": w["sid"], "permission_id": w["pid"]}],
                  draft=True).json()["id"]
    assert rid not in _ids(api, it)
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 200, r.text
    row = next(x for x in api.get("/requests/", token=it).json() if x["id"] == rid)
    assert row["current_node_type"] == "it_execute" and row["can_act"] is True
    dash = api.get("/requests/dashboard", token=it).json()
    assert any(p["request_id"] == rid for p in dash["pending_approvals_list"])


def test_dashboard_superior_does_not_list_manager_stage(api):
    w = _world(api)
    rid = _create(api, w, api.login("hr")).json()["id"]
    dash = api.get("/requests/dashboard", token=api.login("kierP")).json()
    assert all(p["request_id"] != rid for p in dash["pending_approvals_list"])
    dash = api.get("/requests/dashboard", token=api.login("kier")).json()
    assert any(p["request_id"] == rid for p in dash["pending_approvals_list"])
