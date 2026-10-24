"""Poprawki obiegu z audytu 3.9 (wersja 3.10).

1. Wniosek „dla siebie” w szerokim sensie: wniosek dla kierownika (zastępcy)
   komórki albo z krokiem etapu kierownika wykonanym przez pracownika wymaga
   akceptacji przełożonego — także gdy krok wysyła zastępca lub podwładny.
2. Krok bez żadnej osoby uprawnionej w strukturze — rezerwa superadmina
   (może działać, „Czeka na”, e-mail albo ostrzeżenie w logu).
3. Zarchiwizowana / nieaktywna komórka nie przyjmuje wniosków.
4. Ustanie stosunku pracy dla pracownika bez komórki (odpiętego przy
   likwidacji komórki).
5. Systemowe odebranie (usunięcie grupy uprawnień) nie jest ustaniem.
6. Powiadomienia: realizacja do kadr, temat helpdesku, wniosek prowadzony
   przez przełożonego.
7. Limity pól wejściowych.
8. `declaration_required` w szczegółach wniosku.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, Department, RequestItem, RequestStatus, RequestType, User,
    WorkflowTemplate,
)
from conftest import PW
from test_audit35_logic import (
    _act, _create, _det, _items, _mails, _select_approve_type, _take_over, _world,
)

DECL = {"declared_by_name": "Jan Kier", "declared_date": datetime.utcnow().date().isoformat()}


def _set(model, oid, **fields):
    with Session(engine) as s:
        row = s.get(model, oid)
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row); s.commit()


def _tpl_type(code, *types) -> int:
    """Typ wniosku z liniowym szablonem start → `types` → end."""
    seq = [("s", "start")] + [(f"n{i}", t) for i, t in enumerate(types)] + [("e", "end")]
    g = {"nodes": [{"id": i, "type": t, "label": t, "props": {}} for i, t in seq],
         "edges": [{"from": seq[k][0], "to": seq[k + 1][0]} for k in range(len(seq) - 1)]}
    with Session(engine) as s:
        tpl = WorkflowTemplate(name=code, graph_json=json.dumps(g))
        s.add(tpl); s.flush()
        rt = RequestType(name=code, code=code, workflow_template_id=tpl.id)
        s.add(rt); s.commit()
        return rt.id


def _deputy(api, w, username, dept_key="dep"):
    uid = api.mk_user(w["sup"], username, ["manager"], f"Zastępca {username}")
    assert api.post(f"/units/departments/{w[dept_key]}/deputies", token=w["sup"],
                    json={"user_id": uid}).status_code == 201
    return uid


def _grant_done(uid, unit, dep, sid, pid):
    now = datetime.utcnow() - timedelta(days=30)
    with Session(engine) as s:
        u = s.get(User, uid)
        req = AccessRequest(worker_name=u.full_name, worker_user_id=uid, unit_id=unit,
                            department_id=dep, kind="grant", status=RequestStatus.completed,
                            created_at=now, approved_at=now, completed_at=now)
        s.add(req); s.flush()
        s.add(RequestItem(request_id=req.id, system_id=sid, permission_id=pid, kind="grant",
                          fulfilled=True, fulfilled_at=now))
        s.commit()
        return req.id


# ---------------------------------------------------------------------------
# 1. Wniosek „dla siebie” — zastępca / podwładny nie omija przełożonego
# ---------------------------------------------------------------------------

def test_self_select_then_deputy_approve_keeps_higher_approval(api):
    """Wybór → akceptacja kierownika → akceptacja wyższa → IT, komórka
    jednostopniowa: kierownik K wybiera dla siebie, zastępca K akceptuje —
    wniosek idzie do przełożonego, nie do IT."""
    w = _world(api)
    _deputy(api, w, "zastK")
    _set(User, w["kid"], department_id=w["dep"])
    rt = _tpl_type("SAH", "select_permissions", "manager_approve",
                   "higher_manager_approve", "it_execute")
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="change",
                  request_type_id=rt)
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    zast = api.login("zastK")
    assert _det(api, rid, zast)["next_node_type"] == "higher_manager_approve"
    r = _act(api, rid, zast, "approve")
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "higher_manager_approve"
    # Przełożony zatwierdza (oświadczenie — wysyłka do IT).
    r = _act(api, rid, api.login("kierP"), "approve", declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"


def test_self_select_then_deputy_approve_without_higher_node_is_409(api):
    """Szablon wybór → akceptacja (bez akceptacji wyższej): zastępca nie wyśle
    do IT wniosku, w którym kierownik wybrał uprawnienia dla siebie."""
    w = _world(api)
    _deputy(api, w, "zastK")
    _set(User, w["kid"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="change",
                  request_type_id=_select_approve_type())
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    r = _act(api, rid, api.login("zastK"), "approve", declaration=DECL)
    assert r.status_code == 409, r.text
    assert "przełożony" in r.json()["detail"]
    assert api.node_type(rid, kier) == "manager_approve"


@pytest.mark.parametrize("creator", ["kier", "hr"])
def test_request_for_dept_manager_sent_by_deputy_goes_to_superior(api, creator):
    """Wniosek dla kierownika K (złożony przez niego samego albo przez kadry)
    wysłany przez zastępcę K trafia do akceptacji przełożonego, nie do IT."""
    w = _world(api)
    _deputy(api, w, "zastK")
    _set(User, w["kid"], department_id=w["dep"])
    rid = _create(api, w, token=api.login(creator), worker_user_id=w["kid"],
                  worker_name="Jan Kier", kind="change",
                  request_type_id=api.request_type(w["sup"], "MODIFY"))
    zast = api.login("zastK")
    assert api.node_type(rid, zast) == "select_permissions"
    r = _act(api, rid, zast, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, zast) == "higher_manager_approve"
    # Zastępca K nie zatwierdzi akceptacji wyższej; kierownik P — tak.
    assert _act(api, rid, zast, "approve").status_code == 403
    r = _act(api, rid, api.login("kierP"), "approve", declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, zast) == "it_execute"


def test_request_for_responsible_manager_not_approved_by_his_deputy(api):
    """Komórka K bez kierownika (odpowiada za nią kierownik P). Wniosek dla
    kierownika P wysłany przez zastępcę P nie zalicza akceptacji wyższej —
    zatwierdza dyrektor jednostki."""
    w = _world(api)
    _set(Department, w["dep"], manager_user_id=None)
    _set(User, w["pid_user"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["pid_user"], worker_name="Anna Przełożona",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    zp = api.login("zastP")
    r = _act(api, rid, zp, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, zp) == "higher_manager_approve"
    assert "Dorota Dyrektor" in _det(api, rid, zp)["waiting_for"]
    assert _act(api, rid, zp, "approve").status_code == 403
    r = _act(api, rid, api.login("dyr"), "approve", declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, zp) == "it_execute"


def test_superior_who_took_over_sends_manager_request_to_it(api):
    """Przełożony, który przejął wniosek dla kierownika K, sam jest przełożonym —
    jego wybór zalicza akceptację wyższą automatycznie (bez 409)."""
    w = _world(api)
    _set(User, w["kid"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="change",
                  request_type_id=api.request_type(w["sup"], "MODIFY"))
    _take_over(api, rid, "kierP")
    kp = api.login("kierP")
    assert _det(api, rid, kp)["next_node_type"] == "it_execute"
    r = _act(api, rid, kp, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kp) == "it_execute"


def test_ordinary_worker_request_still_skips_higher_in_single_stage(api):
    """Zwykły pracownik K: wybór kierownika K nadal kieruje wniosek prosto do IT."""
    w = _world(api)
    prac = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, prac, department_id=w["dep"])
    rid = _create(api, w, worker_user_id=prac, worker_name="Paweł Pracownik",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    r = _act(api, rid, kier, "select", items=_items(w), declaration=DECL)
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"


# ---------------------------------------------------------------------------
# 2. Brak osoby uprawnionej — rezerwa superadmina
# ---------------------------------------------------------------------------

def _set_root_email(email):
    with Session(engine) as s:
        root = s.exec(select(User).where(User.username == "root")).one()
        root.email = email
        s.add(root); s.commit()


def _same_manager_world(api):
    """Ta sama osoba `m` kieruje K (dwustopniową) i P, jednostka bez dyrektora."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U2", "U2")
    m = api.mk_user(sup, "m", ["manager"], "M Obie")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    p = api.mk_department(sup, unit, m, name="P")
    k = api.mk_department(sup, unit, m, name="K", parent_dept_id=p)
    # Flaga ustawiona przed walidacją struktury (stara baza) — zapis przez API
    # byłby dziś odrzucony, ale takie komórki mogą istnieć.
    _set(Department, k, requires_higher_approval=True)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, p=p, k=k, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"))


def test_no_possible_higher_approver_falls_back_to_superadmin(api, monkeypatch):
    w = _same_manager_world(api)
    _set_root_email("root@t.local")
    sent = _mails(monkeypatch)
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "X", "unit_id": w["unit"], "department_id": w["k"],
        "request_type_id": w["rtype"], "items": []}).json()["id"]
    mt = api.login("m")
    r = _act(api, rid, mt, "select",
             items=[{"system_id": w["sid"], "permission_id": w["pid"]}])
    assert r.status_code == 200, r.text
    assert api.node_type(rid, mt) == "higher_manager_approve"
    d = _det(api, rid, mt)
    assert d["waiting_for"] == "superadmin — brak osoby uprawnionej w strukturze"
    assert d["can_act"] is False
    assert _det(api, rid, w["sup"])["can_act"] is True
    assert ("workflow_stage", "root@t.local") in sent
    # Superadmin widzi wniosek na pulpicie i może zatwierdzić.
    dash = api.get("/requests/dashboard", token=w["sup"]).json()
    assert rid in [p["request_id"] for p in dash["pending_approvals_list"]]
    r = _act(api, rid, w["sup"], "approve", declaration={**DECL, "declared_by_name": "Super"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, mt) == "it_execute"
    # Na realizacji IT superadmin dalej nie działa.
    assert _det(api, rid, w["sup"])["can_act"] is False


def test_manager_stage_without_anyone_falls_back_to_superadmin(api, monkeypatch):
    """Komórka bez kierownika, bez komórki nadrzędnej, jednostka bez dyrektora —
    wybór uprawnień wykona superadmin; bez adresu e-mail — ostrzeżenie w logu."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U3", "U3")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    k = api.mk_department(sup, unit, None, name="K bez kierownika")
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    _set_root_email(None)
    import services.workflow as wf
    warned: list[str] = []
    monkeypatch.setattr(wf._log, "warning", lambda msg, *a, **k: warned.append(msg % a))
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Y", "unit_id": unit, "department_id": k,
        "request_type_id": api.request_type(sup, "NEW_EMP"), "items": []}).json()["id"]
    assert any(f"#{rid}" in m and "superadmina" in m for m in warned), warned
    d = _det(api, rid, sup)
    assert d["waiting_for"] == "superadmin — brak osoby uprawnionej w strukturze"
    assert d["can_act"] is True
    r = _act(api, rid, sup, "select", items=[{"system_id": sid, "permission_id": pid}],
             declaration={**DECL, "declared_by_name": "Super"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, sup) == "it_execute"


def test_superadmin_still_cannot_act_when_someone_can(api):
    w = _world(api)
    rid = _create(api, w)
    assert _det(api, rid, w["sup"])["can_act"] is False
    assert _act(api, rid, w["sup"], "select", items=_items(w)).status_code == 403


# ---------------------------------------------------------------------------
# 3. Zarchiwizowana / nieaktywna komórka
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fields", [{"archived_at": datetime.utcnow()}, {"is_active": False}])
def test_archived_or_inactive_department_rejects_requests(api, fields):
    w = _world(api)
    _set(Department, w["dep"], **fields)
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Ola", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": []})
    assert r.status_code == 400, r.text
    assert "zlikwidowana" in r.json()["detail"] or "nieaktywna" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Ustanie dla pracownika bez komórki
# ---------------------------------------------------------------------------

def test_orphaned_worker_termination_to_any_live_department(api):
    w = _world(api)
    prac = api.mk_user(w["sup"], "sierota", ["viewer"], "Stefan Sierota")
    _grant_done(prac, w["unit"], w["dep"], w["sid"], w["pid"])
    _set(User, prac, department_id=None)   # odpięty przy likwidacji komórki
    rtype = api.request_type(w["sup"], "REVOKE")
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Stefan Sierota", "worker_user_id": prac, "kind": "revoke",
        "unit_id": w["unit"], "department_id": w["parent"], "request_type_id": rtype,
        "items": []})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["department_id"] == w["parent"]
    assert [(i["permission_id"], i["kind"]) for i in out["items"]] == [(w["pid"], "revoke")]
    # Nadanie (nie ustanie) dla osoby bez komórki — nadal odmowa.
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Stefan Sierota", "worker_user_id": prac, "kind": "change",
        "unit_id": w["unit"], "department_id": w["parent"],
        "request_type_id": api.request_type(w["sup"], "MODIFY"), "items": []})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5. Systemowe odebranie nie jest ustaniem stosunku pracy
# ---------------------------------------------------------------------------

def test_group_delete_revoke_is_not_termination(api):
    w = _world(api)
    sup = w["sup"]
    s = api.post("/systems/", token=sup, json={"name": "KS", "access_only": False,
                                              "all_units": True}).json()
    r = api.post(f"/systems/{s['id']}/permissions/import/commit", token=sup, json={
        "group_name": "G", "items": [{"permission_name": "Odczyt"}]})
    assert r.status_code == 200, r.text
    gp = next(p["id"] for p in api.get(f"/systems/{s['id']}/permissions", token=sup).json()
              if p["group_name"] == "G")
    holder = api.mk_user(sup, "hold", ["viewer"], "Holder")
    _set(User, holder, department_id=w["dep"])
    _grant_done(holder, w["unit"], w["dep"], s["id"], gp)
    rid = _create(api, w, worker_user_id=holder, worker_name="Holder", kind="change",
                  request_type_id=api.request_type(sup, "MODIFY"))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w),
                declaration=DECL).status_code == 200
    assert api.node_type(rid, kier) == "it_execute"
    r = api.post(f"/systems/{s['id']}/permissions/group-delete", token=sup,
                 json={"group_name": "G", "reason": "zły import uprawnień",
                       "password": PW})
    assert r.status_code == 200, r.text
    r = _act(api, rid, api.login("it"), "execute")
    assert r.status_code == 200, r.text


def test_real_termination_still_requires_confirmation(api):
    w = _world(api)
    prac = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, prac, department_id=w["dep"])
    rid = _create(api, w, worker_user_id=prac, worker_name="Paweł Pracownik",
                  kind="change", request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w), declaration=DECL).status_code == 200
    # Zrealizowane ustanie z obiegiem (typ wniosku) po złożeniu wniosku.
    with Session(engine) as s:
        rt = s.exec(select(RequestType).where(RequestType.code == "REVOKE")).one()
        s.add(AccessRequest(worker_name="Paweł Pracownik", worker_user_id=prac,
                            unit_id=w["unit"], department_id=w["dep"], kind="revoke",
                            request_type_id=rt.id, status=RequestStatus.completed,
                            completed_at=datetime.utcnow() + timedelta(seconds=5)))
        s.commit()
    r = _act(api, rid, api.login("it"), "execute")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "WORKER_TERMINATED"


# ---------------------------------------------------------------------------
# 6. Powiadomienia
# ---------------------------------------------------------------------------

def test_completion_mail_goes_to_selector_and_hr_creator(api, monkeypatch):
    w = _world(api)
    sent = _mails(monkeypatch)
    rid = _create(api, w)
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w), declaration=DECL).status_code == 200
    assert _act(api, rid, api.login("it"), "execute").status_code == 200
    done = sorted(to for key, to in sent if key == "request_completed")
    assert done == ["hr@t.local", "kier@t.local"]


def test_helpdesk_subject_contains_request_number(api, monkeypatch):
    import services.email_alerts as mail
    subjects: list[str] = []
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, **kw: subjects.append(subject))
    w = _world(api)
    rid = _create(api, w, worker_name="Ola Nowa")
    assert _act(api, rid, api.login("kier"), "select", items=_items(w),
                declaration=DECL).status_code == 200
    assert f"[SZUP] Nowy wniosek #{rid} o nadanie uprawnień — Ola Nowa" in subjects


def test_superior_created_request_informs_dept_manager(api, monkeypatch):
    w = _world(api)
    sent = _mails(monkeypatch)
    rid = _create(api, w, token=api.login("kierP"))
    assert _det(api, rid, api.login("kierP"))["taken_over_by_name"]
    held = [to for key, to in sent if key == "request_held_by_superior"]
    assert held == ["kier@t.local"]
    # Kierownik K nie dostaje „czeka na Ciebie” — krok wykona przełożony.
    assert ("workflow_stage", "kier@t.local") not in sent


def test_system_rejection_on_force_delete_still_notifies(api, monkeypatch):
    w = _world(api)
    rid = _create(api, w)
    sent = _mails(monkeypatch)
    r = api.post(f"/units/departments/{w['dep']}/force-delete", token=w["sup"],
                 json={"reason": "likwidacja komórki", "password": PW})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(AccessRequest, rid).status == RequestStatus.rejected
    assert ("request_rejected", "hr@t.local") in sent


# ---------------------------------------------------------------------------
# 7. Limity pól wejściowych
# ---------------------------------------------------------------------------

def _post_request(api, w, **body):
    return api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Ola", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": [], **body})


@pytest.mark.parametrize("body", [
    {"worker_name": "x" * 201},
    {"worker_name": "Ola\x00Nowa"},
    {"worker_name": "Ola\nNowa"},
    {"worker_position": "s" * 201},
    {"worker_email": "e" * 195 + "@t.local"},
    {"worker_phone": "1" * 201},
])
def test_request_text_limits(api, body):
    w = _world(api)
    r = _post_request(api, w, **body)
    assert r.status_code == 400, r.text


def test_request_item_limits(api):
    w = _world(api)
    item = {"system_id": w["sid"], "permission_id": w["pid"]}
    r = _post_request(api, w, items=[item, dict(item)])
    assert r.status_code == 400 and "więcej niż raz" in r.json()["detail"]
    r = _post_request(api, w, items=[item] * 501)
    assert r.status_code == 400 and "500" in r.json()["detail"]
    # Pole na granicy limitu jest przyjmowane.
    r = _post_request(api, w, items=[item], worker_name="x" * 200)
    assert r.status_code == 201, r.text


def test_action_comment_limits(api):
    w = _world(api)
    rid = _create(api, w)
    kier = api.login("kier")
    r = _act(api, rid, kier, "reject", comment="x" * 4001)
    assert r.status_code == 400
    r = _act(api, rid, kier, "reject", comment="zły\x07wniosek")
    assert r.status_code == 400
    r = api.post(f"/requests/{rid}/draft", token=kier,
                 json={"items": _items(w), "comment": "x" * 4001})
    assert r.status_code == 400
    r = _act(api, rid, kier, "reject", comment="Powód:\n\tdubel wniosku")
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 8. declaration_required
# ---------------------------------------------------------------------------

def test_declaration_required_flag(api):
    w = _world(api)
    rid = _create(api, w)
    kier = api.login("kier")
    assert _det(api, rid, kier)["declaration_required"] is True
    # Kadry nie działają na kroku — flaga False.
    assert _det(api, rid, api.login("hr"))["declaration_required"] is False
    # Komórka dwustopniowa: wybór kierownika K idzie do akceptacji wyższej.
    _set(Department, w["dep"], requires_higher_approval=True)
    assert _det(api, rid, kier)["declaration_required"] is False
