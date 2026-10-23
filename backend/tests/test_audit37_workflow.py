"""E2E: poprawki obiegu wniosków z audytu 3.7.

1. realizacja IT z loginem AD — reguły jak w `link-worker` (H1/S2),
2. odmowa pozycji „odebrania” w akcji execute → 400 (H2),
3. wniosek „dla siebie” — akceptacja przełożonego także w komórce
   jednostopniowej (M3, nowa reguła),
4. wersja robocza nie wycieka po utracie kierownika komórki (M1, pkt 10),
5. `release_manager_posts(before=)`, adresaci powiadomień (taker, składający,
   „Oddaj” przez superadmina),
6. walidacja szablonów obiegu i zdarzenia bezpieczeństwa (S5, pkt 3),
7. stare wnioski bez instancji obiegu nie znikają z list IT (code_ops 2),
8. import struktury z AD — bez przenoszenia między jednostkami i cykli (pkt 4),
9. ustanie stosunku pracy i odrzucanie wniosków (M5, M6, M9),
10. błąd zapisu audytu trafia do logu (code_ops 3),
11. limit/offset listy i identyfikatory spoza zakresu (S11, N3),
12. walidacja oświadczenia wnioskującego (N1)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, AuditLog, Department, RequestItem, RequestStatus, RequestType,
    SecurityEvent, User, WorkflowTemplate,
)
from test_audit35_logic import (
    _world, _items, _create, _act, _det, _row, _mails, _stage_to, _take_over,
    _select_approve_type,
)


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_login_rate_limit(api, monkeypatch):
    """Scenariusze logują wiele osób — limiter prób logowania per-IP (10/min)
    zerujemy przed każdym logowaniem."""
    from routers import auth as _auth
    orig = api.login

    def login(username, *a, **k):
        _auth._ip_hits.clear()
        return orig(username, *a, **k)
    monkeypatch.setattr(api, "login", login)


def _set(model, oid, **fields):
    with Session(engine) as s:
        row = s.get(model, oid)
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row); s.commit()


def _worker(api, w, username, dept=None, roles=("viewer",)):
    uid = api.mk_user(w["sup"], username, list(roles), username)
    if dept is not None:
        _set(User, uid, department_id=dept)
    return uid


def _to_it(api, w, **extra):
    """Wniosek kadr dla K → wybór kierownika → realizacja IT."""
    rid = _create(api, w, **extra)
    assert _act(api, rid, api.login("kier"), "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, api.login("it")) == "it_execute"
    return rid


def _grant_to(api, w, uid):
    """Pracownik `uid` (komórka K) dostaje uprawnienie FK/Odczyt."""
    rid = _to_it(api, w, worker_user_id=uid, kind="change",
                 request_type_id=api.request_type(w["sup"], "MODIFY"))
    assert _act(api, rid, api.login("it"), "execute").status_code == 200
    return rid


def _perms(api, w, uid):
    r = api.get(f"/users/{uid}/permissions", token=w["sup"]).json()
    return [p["permission_name"] for p in r["permissions"]]


def _termination(api, w, uid, token=None, **extra):
    r = api.post("/requests/", token=token or api.login("hr"), json={
        "worker_name": "Prac", "worker_user_id": uid, "kind": "revoke",
        "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": api.request_type(w["sup"], "REVOKE"), "items": [], **extra})
    return r


def _graph(*types):
    seq = [("s", "start")] + [(f"n{i}", t) for i, t in enumerate(types)] + [("e", "end")]
    return json.dumps({
        "nodes": [{"id": i, "type": t, "label": t, "props": {}} for i, t in seq],
        "edges": [{"from": seq[k][0], "to": seq[k + 1][0]} for k in range(len(seq) - 1)]})


def _db_type(code, graph_json):
    """Typ wniosku z szablonem wpisanym WPROST do bazy (z pominięciem walidacji API)."""
    with Session(engine) as s:
        tpl = WorkflowTemplate(name=code, graph_json=graph_json)
        s.add(tpl); s.flush()
        rt = RequestType(name=code, code=code, workflow_template_id=tpl.id)
        s.add(rt); s.commit()
        return rt.id, tpl.id


def _security(event_type):
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)).all()


def _audit(action):
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)).all()


# ---------------------------------------------------------------------------
# 1. execute z ad_username — reguły link-worker (H1 / S2)
# ---------------------------------------------------------------------------

def test_execute_cannot_link_request_to_executors_own_account(api):
    w = _world(api)
    rid = _to_it(api, w)
    r = _act(api, rid, api.login("it"), "execute", ad_username="it")
    assert r.status_code == 403, r.text
    assert _row(rid).worker_user_id is None and _perms(api, w, w["it_id"]) == []


def test_execute_rejects_account_from_other_department(api):
    w = _world(api)
    _set(User, w["pid_user"], department_id=w["parent"])
    rid = _to_it(api, w)
    r = _act(api, rid, api.login("it"), "execute", ad_username="kierP")
    assert r.status_code == 409, r.text
    assert _perms(api, w, w["pid_user"]) == []


def test_execute_cannot_relink_request_with_worker(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    b = _worker(api, w, "pracB", w["dep"])
    _grant_to(api, w, a)
    t = _termination(api, w, a).json()["id"]
    assert _act(api, t, api.login("kier"), "select",
                items=[{**_items(w)[0], "kind": "revoke"}]).status_code == 200
    r = _act(api, t, api.login("it"), "execute", ad_username="pracB")
    assert r.status_code == 409, r.text
    assert _row(t).worker_user_id == a
    # Ten sam login co dowiązane konto — w porządku.
    assert _act(api, t, api.login("it"), "execute", ad_username="pracA").status_code == 200
    assert _perms(api, w, a) == [] and _perms(api, w, b) == []


def test_execute_does_not_fill_department_or_give_hr_department(api):
    w = _world(api)
    _set(Department, w["dep"], is_hr=True)
    loose = _worker(api, w, "luzny")                 # konto bez komórki
    rid = _to_it(api, w)
    assert _act(api, rid, api.login("it"), "execute", ad_username="luzny").status_code == 200
    with Session(engine) as s:
        assert s.get(User, loose).department_id is None
    rid2 = _to_it(api, w)
    assert _act(api, rid2, api.login("it"), "execute", ad_username="nowy1").status_code == 200
    with Session(engine) as s:
        ghost = s.exec(select(User).where(User.username == "nowy1")).one()
        assert ghost.department_id is None           # komórka kadrowa = zdolność HR
        assert _row(rid2).worker_user_id == ghost.id
    assert _audit("request.worker_linked")


# ---------------------------------------------------------------------------
# 2. Odmowa pozycji „odebrania” w akcji execute (H2)
# ---------------------------------------------------------------------------

def test_execute_denial_of_revoke_item_rejected(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    _grant_to(api, w, a)
    t = _termination(api, w, a).json()["id"]
    assert _act(api, t, api.login("kier"), "select",
                items=[{**_items(w)[0], "kind": "revoke"}]).status_code == 200
    it = api.login("it")
    iid = _det(api, t, it)["items"][0]["id"]
    r = _act(api, t, it, "execute", denials=[{"item_id": iid, "comment": "nie"}])
    assert r.status_code == 400, r.text
    assert _act(api, t, it, "execute").status_code == 200
    assert _perms(api, w, a) == []


# ---------------------------------------------------------------------------
# 3. Wniosek „dla siebie” — akceptacja przełożonego (nowa reguła)
# ---------------------------------------------------------------------------

def test_manager_self_request_goes_to_superior_not_it(api, monkeypatch):
    w = _world(api)
    _set(User, w["kid"], department_id=w["dep"])
    sent = _mails(monkeypatch)
    kier = api.login("kier")
    r = api.post("/requests/", token=kier, json={
        "worker_name": "Jan Kier", "worker_user_id": w["kid"], "kind": "change",
        "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": api.request_type(w["sup"], "MODIFY"), "items": _items(w)})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["current_node_type"] == "higher_manager_approve"
    assert {"kierP@t.local", "zastP@t.local"} <= set(_stage_to(sent))
    assert "kier@t.local" not in _stage_to(sent)
    assert _act(api, rid, kier, "approve").status_code == 403
    assert "Anna Przełożona" in _det(api, rid, kier)["waiting_for"]
    # Przełożony zatwierdza — dopiero wtedy wniosek idzie do IT (z oświadczeniem).
    assert _act(api, rid, api.login("kierP"), "approve").status_code == 200
    assert api.node_type(rid, kier) == "it_execute"


def test_hr_request_for_manager_requires_superior_approval(api):
    w = _world(api)
    _set(User, w["kid"], department_id=w["dep"])
    rid = _create(api, w, worker_user_id=w["kid"], worker_name="Jan Kier", kind="change",
                  request_type_id=api.request_type(w["sup"], "MODIFY"))
    kier = api.login("kier")
    det = _det(api, rid, kier)
    # Etykieta „Wyślij do akceptacji” — kolejny krok to akceptacja przełożonego.
    assert det["next_node_type"] == "higher_manager_approve"
    # Kadrowa (która nie wykona kroku) widzi zwykłą ścieżkę.
    assert _det(api, rid, api.login("hr"))["next_node_type"] == "it_execute"
    r = _act(api, rid, kier, "select", items=_items(w), declaration=None)
    assert r.status_code == 200, r.text          # bez oświadczenia — nie idzie do IT
    assert api.node_type(rid, kier) == "higher_manager_approve"


def test_unit_director_self_request_routed_to_superadmin(api, monkeypatch):
    w = _world(api)
    top = api.mk_department(w["sup"], w["unit"], w["did"], name="T")
    _set(User, w["did"], department_id=top)
    with Session(engine) as s:
        root = s.exec(select(User).where(User.username == "root")).one()
        root.email = "root@t.local"
        s.add(root); s.commit()
    sent = _mails(monkeypatch)
    dyr = api.login("dyr")
    r = api.post("/requests/", token=dyr, json={
        "worker_name": "Dorota Dyrektor", "worker_user_id": w["did"], "kind": "change",
        "unit_id": w["unit"], "department_id": top,
        "request_type_id": api.request_type(w["sup"], "MODIFY"), "items": _items(w)})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["current_node_type"] == "higher_manager_approve"
    assert "superadmin" in r.json()["waiting_for"]
    assert "root@t.local" in _stage_to(sent) and "dyr@t.local" not in _stage_to(sent)
    assert _act(api, rid, dyr, "approve").status_code == 403
    assert _act(api, rid, w["sup"], "approve").status_code == 200


def test_self_request_in_template_without_higher_stage_needs_superior(api):
    w = _world(api)
    _set(User, w["kid"], department_id=w["dep"])
    kier = api.login("kier")
    r = api.post("/requests/", token=kier, json={
        "worker_name": "Jan Kier", "worker_user_id": w["kid"], "kind": "change",
        "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": _select_approve_type(), "items": _items(w)})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["current_node_type"] == "manager_approve"   # nie poszedł do IT
    assert _act(api, rid, kier, "approve").status_code == 409
    _take_over(api, rid, "kierP")
    assert _act(api, rid, api.login("kierP"), "approve").status_code == 200
    assert api.node_type(rid, kier) == "it_execute"


# ---------------------------------------------------------------------------
# 4. Wersja robocza po utracie kierownika komórki (M1 / pkt 10)
# ---------------------------------------------------------------------------

def test_draft_stays_hidden_after_manager_deactivated(api):
    w = _world(api)
    rid = _create(api, w)
    assert api.post(f"/requests/{rid}/draft", token=api.login("kier"),
                    json={"items": _items(w), "comment": "TAJNE"}).status_code == 200
    _set(User, w["kid"], is_active=False)
    it = api.login("it")
    assert api.get(f"/requests/{rid}", token=it).status_code == 403
    assert rid not in {x["id"] for x in api.get("/requests/", token=it).json()}
    det = _det(api, rid, api.login("kierP"))      # odpowiedzialny przełożony
    assert det["is_draft"] is True and det["manager_comment"] == "TAJNE"


def test_superior_draft_in_dept_without_manager_hidden(api):
    w = _world(api)
    k2 = api.mk_department(w["sup"], w["unit"], None, name="K2", parent_dept_id=w["parent"])
    rid = _create(api, w, department_id=k2)
    assert api.get(f"/requests/{rid}", token=api.login("it")).status_code == 200
    r = api.post(f"/requests/{rid}/draft", token=api.login("kierP"),
                 json={"items": _items(w), "comment": "notatka"})
    assert r.status_code == 200 and r.json()["is_draft"] is True
    assert api.get(f"/requests/{rid}", token=api.login("it")).status_code == 403
    assert api.get(f"/requests/{rid}", token=api.login("hr")).status_code == 200   # twórca


def test_list_visibility_equivalence_with_drafts_and_legacy_rows(api):
    """Rozszerzenie testu równoważności (test_cleanup35_visibility): wersja
    robocza w komórce z nieaktywnym kierownikiem, wniosek bez instancji obiegu
    (sprzed silnika) i wniosek z pustą kolumną typu węzła."""
    from test_cleanup35_visibility import _world as vis_world
    from services.workflow import can_view_request, manager_stage_hidden_clause
    vis_world(api)
    with Session(engine) as s:
        n = s.exec(select(Department).where(Department.name == "N")).one()
        k = s.exec(select(Department).where(Department.name == "K")).one()
        hr = s.exec(select(User).where(User.username == "hr")).one()
        unit, n_id, k_id = n.unit_id, n.id, k.id
        legacy = AccessRequest(worker_name="Stary", unit_id=unit, department_id=k_id,
                               status=RequestStatus.pending_it, created_by_id=hr.id,
                               created_by_name="hr")
        s.add(legacy); s.commit(); legacy_id = legacy.id
    rtype = api.request_type(api.login("root"), "NEW_EMP")
    hr_tok = api.login("hr")
    rid = api.post("/requests/", token=hr_tok, json={
        "worker_name": "Ola", "unit_id": unit, "department_id": n_id,
        "request_type_id": rtype}).json()["id"]
    assert api.post(f"/requests/{rid}/draft", token=api.login("kierP"),
                    json={"comment": "notatka N"}).status_code == 200
    nul = api.post("/requests/", token=hr_tok, json={
        "worker_name": "Ola", "unit_id": unit, "department_id": k_id,
        "request_type_id": rtype}).json()["id"]
    _set(AccessRequest, nul, current_node_type=None)

    for username in ("adm", "it", "itkier", "hr", "kierP", "zastP", "kier", "zastK",
                     "kier2", "dyr", "obcy", "prac"):
        with Session(engine) as s:
            user = s.exec(select(User).where(User.username == username)).one()
            rows = s.exec(select(AccessRequest)).all()
            can = {r.id for r in rows if can_view_request(s, r, user)}
            stmt = select(AccessRequest.id)
            clause = manager_stage_hidden_clause(s, user)
            if clause is not None:
                stmt = stmt.where(clause)
            sql_visible = set(s.exec(stmt).all())
        # Wiersz z pustą kolumną przy aktywnym obiegu: SQL ukrywa go
        # zachowawczo (siatka bezpieczeństwa) — poza tym zbiory są równe.
        assert sql_visible - {nul} == can - {nul}, username
        assert legacy_id in sql_visible, username
        if username in ("it", "adm"):
            assert rid not in can and nul not in sql_visible, username
    listed = {x["id"] for x in api.get("/requests/", token=api.login("it")).json()}
    assert legacy_id in listed and rid not in listed


# ---------------------------------------------------------------------------
# 5. org_sync(before=), adresaci powiadomień
# ---------------------------------------------------------------------------

def test_release_manager_posts_with_before_snapshot_notifies(api, monkeypatch):
    from services.org_sync import release_manager_posts, stage_snapshot_for
    w = _world(api)
    _create(api, w)
    sent = _mails(monkeypatch)
    with Session(engine) as s:
        snap = stage_snapshot_for(s, w["kid"])
        u = s.get(User, w["kid"])
        u.is_active = False
        s.add(u); s.flush()
        assert release_manager_posts(s, u, before=snap)
        s.commit()
    assert {"kierP@t.local", "zastP@t.local"} <= set(_stage_to(sent))


def test_taker_select_does_not_mail_dept_manager(api, monkeypatch):
    w = _world(api)
    rid = _create(api, w, request_type_id=_select_approve_type())
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    assert _act(api, rid, api.login("kierP"), "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, api.login("kierP")) == "manager_approve"
    assert "kier@t.local" not in _stage_to(sent)


def test_creator_who_can_act_gets_no_mail_about_own_request(api, monkeypatch):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    sent = _mails(monkeypatch)
    r = _termination(api, w, a, token=api.login("kier"))
    assert r.status_code == 201, r.text
    assert r.json()["current_node_type"] == "select_permissions"
    assert "kier@t.local" not in _stage_to(sent)


def test_superadmin_cannot_release_and_taker_release_notifies_manager(api, monkeypatch):
    """Superadmin nie działa w obiegu (decyzje 3.9) — „Oddaj” → 403 bez maili;
    oddanie przez przejmującego przypomina kierownikowi komórki o wniosku."""
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    assert api.post(f"/requests/{rid}/release", token=w["sup"]).status_code == 403
    assert sent == []
    assert api.post(f"/requests/{rid}/release", token=api.login("kierP")).status_code == 200
    assert not [x for x in sent if x[0] == "request_take_over_released"]
    assert "kier@t.local" in _stage_to(sent)


# ---------------------------------------------------------------------------
# 6. Szablony obiegu (S5 / pkt 3)
# ---------------------------------------------------------------------------

def test_template_without_it_or_manager_stage_rejected(api):
    w = _world(api)
    root = w["sup"]
    for graph in (_graph(), _graph("select_permissions"), _graph("it_execute"),
                  _graph("it_execute", "select_permissions"),
                  _graph("select_permissions", "it_execute", "higher_manager_approve")):
        r = api.post("/workflow-templates/", token=root, json={"name": "Zły", "graph_json": graph})
        assert r.status_code == 400, (graph, r.text)
    ok = api.post("/workflow-templates/", token=root, json={
        "name": "Dobry", "graph_json": _graph("manager_approve", "it_execute")})
    assert ok.status_code == 201, ok.text
    bad = api.patch(f"/workflow-templates/{ok.json()['id']}", token=root,
                    json={"graph_json": _graph("manager_approve")})
    assert bad.status_code == 400


def test_template_graph_change_emits_high_security_event(api):
    w = _world(api)
    root = w["sup"]
    tid = api.post("/workflow-templates/", token=root, json={
        "name": "T", "graph_json": _graph("select_permissions", "it_execute")}).json()["id"]
    assert api.patch(f"/workflow-templates/{tid}", token=root,
                     json={"graph_json": _graph("manager_approve", "it_execute")}
                     ).status_code == 200
    ev = _security("workflow_template.graph_changed")
    assert ev and ev[-1].severity == "high"
    # Sama zmiana nazwy nie jest zdarzeniem bezpieczeństwa.
    api.patch(f"/workflow-templates/{tid}", token=root, json={"name": "T2"})
    assert len(_security("workflow_template.graph_changed")) == 1


def test_request_type_template_change_audited_and_validated(api):
    w = _world(api)
    root = w["sup"]
    rt = api.request_type(root, "NEW_EMP")
    tid = api.post("/workflow-templates/", token=root, json={
        "name": "Nowy", "graph_json": _graph("select_permissions", "it_execute")}).json()["id"]
    assert api.patch(f"/request-types/{rt}", token=root,
                     json={"workflow_template_id": tid}).status_code == 200
    ev = _security("request_type.template_changed")
    assert ev and ev[-1].severity == "high"
    assert _audit("request_type.template_changed")
    # Szablon wpisany wprost do bazy z pominięciem walidacji — nie do przypięcia.
    _rt2, bad_tpl = _db_type("NOIT", _graph("select_permissions"))
    r = api.patch(f"/request-types/{rt}", token=root, json={"workflow_template_id": bad_tpl})
    assert r.status_code == 400, r.text


def test_request_with_invalid_db_template_rejected(api):
    w = _world(api)
    for code, graph in (("NOIT", _graph("select_permissions")), ("ITONLY", _graph("it_execute"))):
        rt, _tpl = _db_type(code, graph)
        r = api.post("/requests/", token=api.login("hr"), json={
            "worker_name": "X", "unit_id": w["unit"], "department_id": w["dep"],
            "request_type_id": rt, "items": _items(w)})
        assert r.status_code == 400, (code, r.text)


# ---------------------------------------------------------------------------
# 7. Stare wnioski bez instancji obiegu (code_ops 2)
# ---------------------------------------------------------------------------

def test_legacy_request_without_instance_visible_to_it(api):
    w = _world(api)
    with Session(engine) as s:
        legacy = AccessRequest(worker_name="Stary", unit_id=w["unit"], department_id=w["dep"],
                               status=RequestStatus.pending_it, created_by_name="kadry")
        s.add(legacy); s.commit(); lid = legacy.id
    for user in ("it", "kierP"):
        listed = {x["id"] for x in api.get("/requests/", token=api.login(user)).json()}
        assert lid in listed, user
    # Wniosek w toku z aktywnym obiegiem i pustą kolumną — nadal ukryty.
    rid = _create(api, w)
    _set(AccessRequest, rid, current_node_type=None)
    assert rid not in {x["id"] for x in api.get("/requests/", token=api.login("it")).json()}


# ---------------------------------------------------------------------------
# 8. Import struktury z AD (pkt 4)
# ---------------------------------------------------------------------------

def test_ldap_import_skips_cross_unit_move_and_cycle(api):
    w = _world(api)
    sup = w["sup"]
    u2 = api.mk_unit(sup, "U2", "U2")
    d2 = api.mk_department(sup, u2, None, name="D2")
    r = api.post("/units/ldap/import", token=sup, json={"items": [{
        "unit_name": "U", "map_to_unit_id": w["unit"], "departments": [
            {"name": "P", "map_to_dept_id": w["parent"], "children": [
                {"name": "K", "map_to_dept_id": w["dep"], "children": [
                    {"name": "D2", "map_to_dept_id": d2, "children": []},
                    {"name": "P", "map_to_dept_id": w["parent"], "children": []}]}]}]}]})
    assert r.status_code == 200, r.text
    details = "\n".join(r.json()["details"])
    assert "innej jednostki" in details and "cykl" in details
    with Session(engine) as s:
        d = s.get(Department, d2)
        assert (d.unit_id, d.parent_dept_id) == (u2, None)
        assert s.get(Department, w["parent"]).parent_dept_id is None
        assert s.get(Department, w["dep"]).parent_dept_id == w["parent"]


# ---------------------------------------------------------------------------
# 9. Ustanie stosunku pracy i odrzucanie (M5, M6, M9)
# ---------------------------------------------------------------------------

def test_termination_prefilled_and_cannot_be_emptied_silently(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    _grant_to(api, w, a)
    r = _termination(api, w, a)
    assert r.status_code == 201, r.text
    t = r.json()["id"]
    assert [(i["permission_name"], i["kind"]) for i in r.json()["items"]] == [("Odczyt", "revoke")]
    kier = api.login("kier")
    sel = _act(api, t, kier, "select", items=[])
    assert sel.status_code == 400 and "nadal ma uprawnienia" in sel.json()["detail"]
    # Wysłanie z pozycjami z kadr — po realizacji pracownik nie ma nic.
    assert _act(api, t, kier, "select",
                items=[{**_items(w)[0], "kind": "revoke"}]).status_code == 200
    assert _act(api, t, api.login("it"), "execute").status_code == 200
    assert _perms(api, w, a) == []


def test_empty_termination_requires_explicit_confirmation(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    _grant_to(api, w, a)
    t2 = _termination(api, w, a).json()["id"]
    kier = api.login("kier")
    with Session(engine) as s:   # kadry wyczyściły pozycje (np. przez stare API)
        for it in s.exec(select(RequestItem).where(RequestItem.request_id == t2)).all():
            s.delete(it)
        s.commit()
    assert _act(api, t2, kier, "select", items=[]).status_code == 400
    assert _act(api, t2, kier, "select", items=[], allow_empty=True).status_code == 200


def test_only_one_active_termination_per_worker(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    assert _termination(api, w, a).status_code == 201
    second = _termination(api, w, a)
    assert second.status_code == 409, second.text


def test_grant_after_completed_termination_requires_confirmation(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    chg = _to_it(api, w, worker_user_id=a, kind="change",
                 request_type_id=api.request_type(w["sup"], "MODIFY"))
    _grant_to(api, w, a)
    t = _termination(api, w, a).json()["id"]
    assert _act(api, t, api.login("kier"), "select",
                items=[{**_items(w)[0], "kind": "revoke"}]).status_code == 200
    it = api.login("it")
    assert _act(api, t, it, "execute").status_code == 200
    r = _act(api, chg, it, "execute")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "WORKER_TERMINATED"
    assert _perms(api, w, a) == []
    assert _act(api, chg, it, "execute", confirm_after_termination=True).status_code == 200
    assert _perms(api, w, a) == ["Odczyt"]
    assert _audit("request.executed_after_termination")


def test_grant_for_inactive_worker_requires_confirmation(api):
    w = _world(api)
    a = _worker(api, w, "pracA", w["dep"])
    rid = _to_it(api, w, worker_user_id=a, kind="change",
                 request_type_id=api.request_type(w["sup"], "MODIFY"))
    _set(User, a, is_active=False)
    assert _act(api, rid, api.login("it"), "execute").status_code == 409


def test_reject_requires_comment_for_everyone(api):
    w = _world(api)
    rid = _create(api, w)
    kier = api.login("kier")
    assert _act(api, rid, kier, "reject").status_code == 400
    assert _act(api, rid, kier, "reject", comment="   ").status_code == 400
    rid2 = _to_it(api, w)
    it = api.login("it")
    assert _act(api, rid2, it, "reject").status_code == 400
    assert _act(api, rid2, it, "reject", comment="Brak licencji").status_code == 200


def test_it_cannot_reject_after_fulfilling_items(api):
    w = _world(api)
    rid = _to_it(api, w)
    it = api.login("it")
    iid = _det(api, rid, it)["items"][0]["id"]
    assert api.post(f"/requests/{rid}/items/{iid}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 200
    r = _act(api, rid, it, "reject", comment="Jednak nie")
    assert r.status_code == 409 and "zrealizowana" in r.json()["detail"]
    assert _row(rid).status == RequestStatus.pending_it


# ---------------------------------------------------------------------------
# 10. Błąd zapisu audytu nie jest połykany po cichu (code_ops 3)
# ---------------------------------------------------------------------------

def test_audit_write_failure_is_logged(api, monkeypatch):
    import routers.requests as req_router
    import services.audit as audit
    w = _world(api)
    rid = _create(api, w)
    logged: list[str] = []
    monkeypatch.setattr(req_router._log, "exception",
                        lambda msg, *a, **k: logged.append(msg))

    def boom(*a, **k):
        raise RuntimeError("baza audytu niedostępna")
    monkeypatch.setattr(audit, "record_event", boom)
    assert api.post(f"/requests/{rid}/take-over", token=api.login("kierP")).status_code == 200
    assert logged == [req_router.AUDIT_WRITE_FAILED_MSG]


# ---------------------------------------------------------------------------
# 11. limit/offset i identyfikatory spoza zakresu (S11, N3)
# ---------------------------------------------------------------------------

def test_list_limit_offset_and_huge_ids(api):
    w = _world(api)
    it = api.login("it")
    assert api.get("/requests/?limit=-1", token=it).status_code == 422
    assert api.get("/requests/?limit=0", token=it).status_code == 422
    assert api.get("/requests/?offset=-1", token=it).status_code == 422
    huge = 2 ** 63
    for path in (f"/requests/{huge}", f"/requests/{huge}/workflow",
                 f"/requests/{huge}/workflow/verify"):
        assert api.get(path, token=it).status_code == 404, path
    assert api.post(f"/requests/{huge}/take-over", token=it).status_code == 404
    rid = _to_it(api, w)
    r = api.post(f"/requests/{rid}/items/{huge}/deny", token=it, json={"denied": True})
    assert r.status_code == 404
    r = _act(api, rid, it, "execute", denials=[{"item_id": huge}])
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 12. Oświadczenie wnioskującego (N1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decl", [
    {"declared_by_name": "Jan", "declared_date": "jutro albo 2099-13-45"},
    {"declared_by_name": "Jan", "declared_date": "2026-02-30"},
    {"declared_by_name": "Jan", "declared_date": (date.today() + timedelta(days=5)).isoformat()},
    {"declared_by_name": "Jan", "declared_date": "1990-01-01"},
    {"declared_by_name": "J" * 201, "declared_date": date.today().isoformat()},
    {"declared_by_name": "Jan\nKowalski", "declared_date": date.today().isoformat()},
])
def test_invalid_declaration_rejected(api, decl):
    w = _world(api)
    rid = _create(api, w)
    r = _act(api, rid, api.login("kier"), "select", items=_items(w), declaration=decl)
    assert r.status_code == 400, r.text
    assert api.node_type(rid, api.login("kier")) == "select_permissions"


def test_valid_declaration_accepted_and_trimmed(api):
    from models import PermissionDeclaration
    w = _world(api)
    rid = _create(api, w)
    r = _act(api, rid, api.login("kier"), "select", items=_items(w),
             declaration={"declared_by_name": "  Jan Kier  ",
                          "declared_date": datetime.now().date().isoformat()})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        dec = s.exec(select(PermissionDeclaration)
                     .where(PermissionDeclaration.request_id == rid)).one()
        assert dec.declared_by_name == "Jan Kier"
