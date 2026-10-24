"""Poprawki obiegu wniosków po audycie 3.10 (wersja 3.11, agent A).

1. Ustanie dla osoby bez żywej komórki — tylko kadry, z komórką docelową;
   wniosek `revoke` przyjmuje wyłącznie odebrania; superadmin nigdy nie jest
   pracownikiem, administrator — nie w ścieżce „bez komórki”.
2. D1/D2/F2, N1/N4, M1 — akceptację wyższą wykonuje osoba stojąca wyżej niż
   pracownik; wspinanie się po łańcuchu; rezerwa superadmina (także na etapie
   kierownika w obiegu bez akceptacji wyższej) z adnotacją awaryjną.
3. Ś11 — kto wykonał krok etapu kierownika, nie realizuje wniosku w IT.
4. Ustanie — pozycje ustalone.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, Department, PermissionDeclaration, RequestItem, RequestStatus,
    User, WorkflowInstance, WorkflowStep, roles_to_json,
)
from test_audit35_logic import _act, _create, _det, _items, _world
from test_310_workflow import DECL, _deputy, _grant_done, _set, _tpl_type


def _steps(rid):
    with Session(engine) as s:
        inst = s.exec(select(WorkflowInstance).where(WorkflowInstance.request_id == rid)).one()
        return s.exec(select(WorkflowStep).where(WorkflowStep.instance_id == inst.id)
                      .order_by(WorkflowStep.step_index)).all()


def _top_world(api, deputy=False):
    """Jednostka T bez dyrektora: komórka najwyższego poziomu K (kierownik `m`)."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "T", "T")
    m = api.mk_user(sup, "m", ["manager"], "Marek Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, m, name="K")
    _set(User, m, department_id=dep)
    d = None
    if deputy:
        d = api.mk_user(sup, "dz", ["manager"], "Dorota Zast")
        _set(User, d, department_id=dep)
        assert api.post(f"/units/departments/{dep}/deputies", token=sup,
                        json={"user_id": d}).status_code == 201
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, m=m, d=d, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"))


def _revoke_type(api, w):
    return api.request_type(w["sup"], "REVOKE")


# ---------------------------------------------------------------------------
# 1. Ustanie dla osoby bez komórki / z komórki nieaktywnej
# ---------------------------------------------------------------------------

def test_orphan_termination_only_by_hr(api):
    w = _world(api)
    x = api.mk_user(w["sup"], "odp", ["viewer"], "Odpięty Pracownik")
    _grant_done(x, w["unit"], w["dep"], w["sid"], w["pid"])
    _set(User, x, department_id=None)
    body = {"worker_name": "Odpięty", "worker_user_id": x, "unit_id": w["unit"],
            "department_id": w["dep"], "kind": "revoke",
            "request_type_id": _revoke_type(api, w), "items": []}
    # Kierownik (bez funkcji kadr) — 403, nawet do własnej komórki.
    r = api.post("/requests/", token=api.login("kier"), json=body)
    assert r.status_code == 403, r.text
    # Kierownik nie widzi też uprawnień tej osoby.
    assert api.get(f"/users/{x}/permissions", token=api.login("kier")).status_code == 403
    # Kadry — do wskazanej komórki docelowej; pozycje = wszystkie uprawnienia.
    r = api.post("/requests/", token=api.login("hr"), json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["is_termination"] is True and out["is_system"] is False
    assert [(i["permission_id"], i["kind"]) for i in out["items"]] == [(w["pid"], "revoke")]


def test_termination_for_worker_of_inactive_department_routed_by_hr(api):
    w = _world(api)
    sup = w["sup"]
    old = api.mk_department(sup, w["unit"], None, name="Stara")
    x = api.mk_user(sup, "prac", ["viewer"], "Paweł Pracownik")
    _set(User, x, department_id=old)
    _grant_done(x, w["unit"], old, w["sid"], w["pid"])
    _set(Department, old, is_active=False)
    hr = api.login("hr")
    # Wyszukiwarka kadr: komórka nieżywa.
    res = api.get("/users/search", token=hr, params={"q": "pawe"}).json()
    row = next(r for r in res if r["id"] == x)
    assert row["department_live"] is False and row["is_active"] is True
    # Wniosek do komórki nieaktywnej — 400 (komórka nie przyjmuje wniosków).
    body = {"worker_name": "Paweł", "worker_user_id": x, "unit_id": w["unit"],
            "kind": "revoke", "request_type_id": _revoke_type(api, w), "items": []}
    assert api.post("/requests/", token=hr, json={**body, "department_id": old}).status_code == 400
    # Do aktywnej komórki docelowej — 201, kierownik K wykonuje wybór.
    r = api.post("/requests/", token=hr, json={**body, "department_id": w["dep"]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    kier = api.login("kier")
    # Kierownik komórki docelowej widzi uprawnienia osoby (działa na wniosku).
    assert api.get(f"/users/{x}/permissions", token=kier).status_code == 200
    r = _act(api, rid, kier, "select",
             items=[{"system_id": w["sid"], "permission_id": w["pid"], "kind": "revoke"}])
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"


def test_search_include_inactive_only_for_hr(api):
    w = _world(api)
    x = api.mk_user(w["sup"], "nieakt", ["viewer"], "Nina Nieaktywna")
    y = api.mk_user(w["sup"], "nieakt2", ["viewer"], "Nina Bezuprawnien")
    _grant_done(x, w["unit"], w["dep"], w["sid"], w["pid"])
    _set(User, x, department_id=w["dep"], is_active=False)
    _set(User, y, department_id=w["dep"], is_active=False)
    hr = api.login("hr")
    assert api.get("/users/search", token=hr, params={"q": "nina"}).json() == []
    res = api.get("/users/search", token=hr,
                  params={"q": "nina", "include_inactive": "true"}).json()
    assert [(r["id"], r["is_active"], r["department_live"]) for r in res] == [(x, False, True)]
    # Kierownik — parametr ignorowany.
    res = api.get("/users/search", token=api.login("kier"),
                  params={"q": "nina", "include_inactive": "true"}).json()
    assert res == []


def test_superadmin_and_admin_cannot_be_workers(api):
    w = _world(api)
    hr = api.login("hr")
    with Session(engine) as s:
        root_id = s.exec(select(User).where(User.username == "root")).one().id
    adm = api.mk_user(w["sup"], "adm", ["admin"], "Admin")
    for kind, rt in (("grant", w["rtype"]), ("revoke", _revoke_type(api, w))):
        r = api.post("/requests/", token=hr, json={
            "worker_name": "Root", "worker_user_id": root_id, "unit_id": w["unit"],
            "department_id": w["dep"], "kind": kind, "request_type_id": rt, "items": []})
        assert r.status_code == 400, r.text
        assert "superadmin" in r.json()["detail"]
    # Administrator bez komórki — nie w ścieżce „bez komórki”.
    r = api.post("/requests/", token=hr, json={
        "worker_name": "Admin", "worker_user_id": adm, "unit_id": w["unit"],
        "department_id": w["dep"], "kind": "revoke",
        "request_type_id": _revoke_type(api, w), "items": []})
    assert r.status_code == 400, r.text


def test_revoke_request_accepts_only_revoke_items(api):
    w = _world(api)
    x = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, x, department_id=w["dep"])
    sid2, p2 = api.mk_system_perm(w["sup"], "Inny", "X")
    body = {"worker_name": "Paweł", "worker_user_id": x, "unit_id": w["unit"],
            "department_id": w["dep"], "kind": "revoke",
            "request_type_id": _revoke_type(api, w)}
    r = api.post("/requests/", token=api.login("hr"),
                 json={**body, "items": [{"system_id": sid2, "permission_id": p2,
                                          "kind": "grant"}]})
    assert r.status_code == 400, r.text
    rid = api.post("/requests/", token=api.login("hr"), json={**body, "items": []}).json()["id"]
    kier = api.login("kier")
    r = _act(api, rid, kier, "select",
             items=[{"system_id": sid2, "permission_id": p2, "kind": "grant"}])
    assert r.status_code == 400, r.text
    r = api.post(f"/requests/{rid}/draft", token=kier,
                 json={"items": [{"system_id": sid2, "permission_id": p2, "kind": "grant"}]})
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 4. Ustanie — pozycje ustalone (F8, M9)
# ---------------------------------------------------------------------------

def test_termination_items_cannot_be_narrowed(api):
    w = _world(api)
    sid2, p2 = api.mk_system_perm(w["sup"], "Inny", "X")
    x = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, x, department_id=w["dep"])
    _grant_done(x, w["unit"], w["dep"], w["sid"], w["pid"])
    _grant_done(x, w["unit"], w["dep"], sid2, p2)
    rid = _create(api, w, worker_user_id=x, worker_name="Paweł", kind="revoke",
                  request_type_id=_revoke_type(api, w))
    kier = api.login("kier")
    d = _det(api, rid, kier)
    assert d["is_termination"] is True and d["declaration_required"] is False
    assert len(d["items"]) == 2
    one = [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "revoke"}]
    r = _act(api, rid, kier, "select", items=one)
    assert r.status_code == 400 and "wszystkie uprawnienia" in r.json()["detail"], r.text
    r = _act(api, rid, kier, "select", items=[], allow_empty=True)
    assert r.status_code == 400, r.text
    assert api.post(f"/requests/{rid}/draft", token=kier, json={"items": one}).status_code == 400
    both = one + [{"system_id": sid2, "permission_id": p2, "kind": "revoke"}]
    r = _act(api, rid, kier, "select", items=both)
    assert r.status_code == 200, r.text
    # IT nie dokłada nadania do wniosku o odebranie.
    it = api.login("it")
    r = _act(api, rid, it, "execute", comment="moduł zależny",
             added_items=[{"system_id": sid2, "permission_id": p2}])
    assert r.status_code == 400, r.text
    assert _act(api, rid, it, "execute").status_code == 200
    assert api.get(f"/users/{x}/permissions", token=kier).json()["permissions"] == []


def test_manager_own_termination_cannot_be_emptied(api):
    """F8: kierownik K dostaje do wyboru własne ustanie — nie opróżni listy."""
    w = _world(api)
    _set(User, w["kid"], department_id=w["dep"])
    _grant_done(w["kid"], w["unit"], w["dep"], w["sid"], w["pid"])
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="revoke",
                  request_type_id=_revoke_type(api, w))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=[], allow_empty=True).status_code == 400


# ---------------------------------------------------------------------------
# 2. D1/D2/F2, N1, N4 — akceptacja wyższa tylko przez osobę wyżej
# ---------------------------------------------------------------------------

def test_n1_director_member_of_k_requires_superadmin_fallback(api):
    """D2/N1: dyrektor jednostki jest członkiem K — wybór kierownika K nie
    kieruje wniosku do IT; nad dyrektorem nie ma nikogo → superadmin."""
    w = _world(api)
    _set(User, w["did"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["did"], worker_name="Dorota Dyrektor",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    assert _det(api, rid, kier)["next_node_type"] == "higher_manager_approve"
    r = _act(api, rid, kier, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "higher_manager_approve"
    d = _det(api, rid, w["sup"])
    assert d["can_act"] is True and d["superadmin_emergency"] is True
    assert d["waiting_for"].startswith("superadmin")
    # Podwładni dyrektora nie zatwierdzają.
    for who in ("kierP", "zastP"):
        assert _act(api, rid, api.login(who), "approve").status_code == 403, who
    r = _act(api, rid, w["sup"], "approve", declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"
    last = [st for st in _steps(rid) if st.node_type == "higher_manager_approve"][-1]
    assert json.loads(last.payload)["superadmin_emergency"] is True
    with Session(engine) as s:
        dec = s.exec(select(PermissionDeclaration)
                     .where(PermissionDeclaration.request_id == rid)
                     .order_by(PermissionDeclaration.id.desc())).first()
        from services.declarations import EMERGENCY_NOTE
        assert dec.declaration_text.startswith(EMERGENCY_NOTE)


def test_f2_parent_manager_sitting_in_child_approved_by_director(api):
    w = _world(api)
    _set(User, w["pid_user"], department_id=w["dep"])     # kierP przypisany do K
    rid = _create(api, w, worker_user_id=w["pid_user"], worker_name="Anna Przełożona",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    r = _act(api, rid, kier, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "higher_manager_approve"
    assert "Dorota Dyrektor" in _det(api, rid, kier)["waiting_for"]
    assert _act(api, rid, api.login("zastP"), "approve").status_code == 403
    assert _act(api, rid, w["sup"], "approve").status_code == 403
    r = _act(api, rid, api.login("dyr"), "approve", declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"


def test_d1_director_managing_child_not_approved_by_subordinate(api):
    w = _world(api)
    _set(Department, w["dep"], manager_user_id=w["did"])
    _set(User, w["did"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["did"], worker_name="Dorota Dyrektor",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    dyr = api.login("dyr")
    r = _act(api, rid, dyr, "select", items=_items(w))
    assert r.status_code == 200, r.text
    assert api.node_type(rid, dyr) == "higher_manager_approve"
    assert _act(api, rid, api.login("kierP"), "approve").status_code == 403
    assert _det(api, rid, w["sup"])["can_act"] is True
    assert _act(api, rid, w["sup"], "approve", declaration=DECL).status_code == 200


def test_manager_of_other_dept_member_of_k_needs_superior(api):
    """Pracownik K kieruje inną komórką (poza łańcuchem K) — wniosek dla niego
    wymaga akceptacji przełożonego tamtej komórki (tu: dyrektor)."""
    w = _world(api)
    other_mgr = api.mk_user(w["sup"], "kierC", ["manager"], "Cezary Inny")
    api.mk_department(w["sup"], w["unit"], other_mgr, name="C")
    _set(User, other_mgr, department_id=w["dep"])
    rid = _create(api, w, worker_user_id=other_mgr, worker_name="Cezary Inny",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w), declaration=DECL).status_code == 200
    assert api.node_type(rid, kier) == "higher_manager_approve"
    # kierP jest przełożonym K, ale nie stoi nad komórką C.
    assert _act(api, rid, api.login("kierP"), "approve").status_code == 403
    assert _act(api, rid, api.login("dyr"), "approve", declaration=DECL).status_code == 200


def test_n4_climbs_chain_before_superadmin(api):
    """Kierownik kieruje K i nadrzędną P, nad P jest G z kierownikiem X —
    akceptację wyższą wykonuje X, nie superadmin."""
    w = _world(api)
    sup = w["sup"]
    x = api.mk_user(sup, "xboss", ["manager"], "Xawery Boss")
    g = api.mk_department(sup, w["unit"], x, name="G")
    p2 = api.mk_department(sup, w["unit"], w["kid"], name="P2", parent_dept_id=g)
    assert api.patch(f"/units/departments/{w['dep']}", token=sup,
                     json={"parent_dept_id": p2}).status_code == 200
    _set(User, w["kid"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="change",
                  request_type_id=api.request_type(sup, "MODIFY"))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, kier) == "higher_manager_approve"
    d = _det(api, rid, sup)
    assert d["can_act"] is False and d["superadmin_emergency"] is False
    assert "Xawery Boss" in d["waiting_for"]
    assert _act(api, rid, sup, "approve").status_code == 403
    assert _act(api, rid, api.login("xboss"), "approve", declaration=DECL).status_code == 200


def test_m1_top_level_manager_without_higher_node_superadmin_fallback(api):
    """M1: K najwyższego poziomu, jednostka bez dyrektora, obieg wybór → IT.
    Wniosek dla kierownika K nie utyka — działa superadmin (rezerwa)."""
    w = _top_world(api, deputy=True)
    rt = _tpl_type("SELIT", "select_permissions", "it_execute")
    rid = _create(api, w, worker_user_id=w["m"], worker_name="Marek Kier", kind="change",
                  request_type_id=rt)
    m = api.login("m")
    assert _act(api, rid, m, "select", items=_items(w), declaration=DECL).status_code == 409
    assert _act(api, rid, api.login("dz"), "select", items=_items(w),
                declaration=DECL).status_code == 409
    d = _det(api, rid, w["sup"])
    assert d["can_act"] is True and d["superadmin_emergency"] is True
    assert d["waiting_for"].startswith("superadmin") and "przełożonego" in d["waiting_for"]
    # Pulpit superadmina — kafelek „do przygotowania”.
    dash = api.get("/requests/dashboard", token=w["sup"]).json()
    assert dash["show_prepare"] is True and dash["pending_prepare_count"] == 1
    assert [p["request_id"] for p in dash["pending_approvals_list"]] == [rid]
    r = _act(api, rid, w["sup"], "select", items=_items(w), declaration=None)
    assert r.status_code == 428, r.text
    r = _act(api, rid, w["sup"], "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, m) == "it_execute"
    sel = [st for st in _steps(rid) if st.node_type == "select_permissions"][-1]
    assert json.loads(sel.payload)["superadmin_emergency"] is True


def test_superadmin_dashboard_prepare_tile_and_mail_link(api, monkeypatch):
    """Wybór uprawnień czeka na superadmina (komórka bez kierownika, brak
    dyrektora) — kafelek widoczny, mail z linkiem do /requests/view/<id>."""
    import services.email_alerts as mail
    sent = []
    monkeypatch.setattr(mail, "_send_event",
                        lambda key, to, ctx, **kw: sent.append((key, to, ctx)))
    w = _top_world(api)
    _set(Department, w["dep"], manager_user_id=None)
    rid = _create(api, w)
    dash = api.get("/requests/dashboard", token=w["sup"]).json()
    assert dash["show_prepare"] is True
    stage = [(to, ctx["request_url"]) for key, to, ctx in sent if key == "workflow_stage"]
    assert stage and all(url.endswith(f"/requests/view/{rid}") for to, url in stage
                         if to == "root@t.local")
    assert any(to == "root@t.local" for to, _ in stage)


# ---------------------------------------------------------------------------
# 3. Ś11 — realizacja przez osobę, która wykonała krok etapu kierownika
# ---------------------------------------------------------------------------

def _it_manager_world(api):
    w = _world(api)
    _set(User, w["kid"], roles=roles_to_json(["manager", "it_staff"]))
    x = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, x, department_id=w["dep"])
    rid = _create(api, w, worker_user_id=x, worker_name="Paweł", kind="change",
                  request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w), declaration=DECL).status_code == 200
    assert api.node_type(rid, kier) == "it_execute"
    return w, rid, kier


def test_executor_who_did_manager_step_is_blocked(api):
    w, rid, kier = _it_manager_world(api)
    d = _det(api, rid, kier)
    assert d["execute_blocked_reason"] and "inna osoba z IT" in d["execute_blocked_reason"]
    r = _act(api, rid, kier, "execute")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EXECUTOR_DID_MANAGER_STEP"
    item_id = d["items"][0]["id"]
    r = api.post(f"/requests/{rid}/items/{item_id}/fulfill", token=kier, json={"fulfilled": True})
    assert r.status_code == 409
    it = api.login("it")
    assert _det(api, rid, it)["execute_blocked_reason"] is None
    assert _act(api, rid, it, "execute").status_code == 200


def test_executor_allowed_when_single_it_person(api):
    w, rid, kier = _it_manager_world(api)
    _set(User, w["it_id"], is_active=False)
    assert _det(api, rid, kier)["execute_blocked_reason"] is None
    assert _act(api, rid, kier, "execute").status_code == 200


# ---------------------------------------------------------------------------
# Serializacja: is_system / is_termination / draft_saved_at
# ---------------------------------------------------------------------------

def test_serialization_flags(api):
    w = _world(api)
    rid = _create(api, w)
    d = _det(api, rid, api.login("kier"))
    for key in ("is_system", "is_termination", "draft_saved_at", "execute_blocked_reason",
                "superadmin_emergency", "waiting_for"):
        assert key in d, key
    assert d["is_system"] is False and d["is_termination"] is False
    now = datetime.utcnow()
    with Session(engine) as s:
        rq = AccessRequest(worker_name="X", unit_id=w["unit"], department_id=w["dep"],
                           kind="revoke", status=RequestStatus.completed,
                           manager_comment="[SYSTEM] Usunięcie grupy uprawnień",
                           created_at=now, completed_at=now)
        s.add(rq); s.commit(); sys_id = rq.id
    d = _det(api, sys_id, w["sup"])
    assert d["is_system"] is True and d["is_termination"] is False
