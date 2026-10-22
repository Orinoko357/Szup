"""E2E/jednostkowe: poprawki logiki z audytu 3.2 (execute bez częściowych zapisów,
brak ścieżki legacy, after_commit, reguła przełożonego, adresaci powiadomień)."""
from __future__ import annotations

import threading

from sqlmodel import Session, select

from database import engine
from models import RequestItem, User


def _world(api, two_stage=False):
    """Kierownik komórki K (opcjonalnie 2-stopniowej pod nadrzędną P), IT, HR."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = None
    if two_stage:
        pid_user = api.mk_user(sup, "kierP", ["manager"], "Kier Nadrzędny")
        parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K",
                            requires_higher_approval=two_stage, parent_dept_id=parent)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    sid2, pid2 = api.mk_system_perm(sup, "Kadry", "Zapis")
    rtype = api.request_type(sup, "NEW_EMP")
    return dict(sup=sup, unit=unit, kid=kid, dep=dep, parent=parent,
                sid=sid, pid=pid, sid2=sid2, pid2=pid2, rtype=rtype)


def _new_request(api, w, items=None, token=None):
    r = api.post("/requests/", token=token or api.login("hr"), json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "items": items or [], "request_type_id": w["rtype"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _items(rid):
    with Session(engine) as s:
        return s.exec(select(RequestItem).where(RequestItem.request_id == rid)).all()


def _user_exists(username):
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == username)).first() is not None


# --- 1. execute: walidacja przed jakimkolwiek zapisem ------------------------

def test_execute_by_non_actor_leaves_no_added_items_nor_ghost_account(api):
    w = _world(api)
    rid = _new_request(api, w)
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]}).status_code == 200
    assert api.node_type(rid, kier) == "it_execute"

    # Kierownik (ma dostęp do wniosku, ale nie jest IT) próbuje „zrealizować".
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "execute", "ad_username": "widmo", "comment": "dokładam",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"]}]})
    assert r.status_code == 403, r.text
    assert [(i.system_id, i.permission_id) for i in _items(rid)] == [(w["sid"], w["pid"])]
    assert not _user_exists("widmo")


def test_execute_on_wrong_node_leaves_nothing(api):
    w = _world(api)
    rid = _new_request(api, w)     # stoi na wyborze uprawnień
    r = api.post(f"/requests/{rid}/workflow/action", token=api.login("it"), json={
        "action": "execute", "ad_username": "widmo2", "comment": "x",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"]}]})
    assert r.status_code in (400, 403), r.text
    assert _items(rid) == []
    assert not _user_exists("widmo2")


# --- 2. stara ścieżka tworzenia wniosku ---------------------------------------

def test_create_without_request_type_is_rejected(api):
    w = _world(api)
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Bez Typu", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 400
    assert "typ wniosku" in r.json()["detail"].lower()
    assert api.get("/requests/", token=w["sup"]).json() == []


# --- after_commit -------------------------------------------------------------

def test_after_commit_rollback_clears_jobs_and_commit_runs_them():
    from services.after_commit import defer, pending_jobs

    called = []
    done = threading.Event()

    def job(tag):
        called.append(tag)
        done.set()

    with Session(engine) as s:
        defer(s, job, tag="po-rollbacku")
        assert len(pending_jobs(s)) == 1
        s.rollback()
        assert pending_jobs(s) == []

        defer(s, job, tag="po-commicie")
        s.commit()
    assert done.wait(5)
    assert called == ["po-commicie"]


def test_after_commit_job_failure_is_logged():
    import logging
    from services.after_commit import defer

    logged = threading.Event()
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)
            logged.set()

    log = logging.getLogger("szup.after_commit")
    h = _H(level=logging.ERROR)
    log.addHandler(h)
    try:
        def bad():
            raise RuntimeError("smtp padł")

        with Session(engine) as s:
            defer(s, bad)
            s.commit()
        assert logged.wait(5)
    finally:
        log.removeHandler(h)
    assert records[0].exc_info and "smtp padł" in str(records[0].exc_info[1])


# --- reguła przełożonego ------------------------------------------------------

def test_superior_can_do_both_manager_steps_and_own_manager_cannot_higher(api):
    w = _world(api, two_stage=True)
    rid = _new_request(api, w)
    kier, kierP = api.login("kier"), api.login("kierP")

    # Przełożony (kierownik komórki nadrzędnej) wykonuje krok wyboru podległej komórki.
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kierP) == "higher_manager_approve"

    # Kierownik samej komórki NIE może zatwierdzić akceptacji wyższej…
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={"action": "approve"})
    assert r.status_code == 403
    # …a przełożony może (także drugi stopień — decyzja biznesowa).
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kierP) == "it_execute"


def test_two_stage_manager_can_only_forward_own_request_up(api):
    """Kierownik komórki z akceptacją wyższą: własny wniosek tylko przekazuje
    wyżej — wybór zalicza się automatycznie, akceptacji wyższej sam nie wykona."""
    w = _world(api, two_stage=True)
    kier, kierP = api.login("kier"), api.login("kierP")
    r = api.post("/requests/", token=kier, json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"],
        "department_id": w["dep"], "request_type_id": w["rtype"],
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert api.node_type(rid, kier) == "higher_manager_approve"
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={"action": "approve"})
    assert r.status_code == 403
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kierP) == "it_execute"


def test_unit_director_can_do_every_step_for_subordinate_departments(api):
    """Dyrektor jednostki może wszystko dla podległych komórek (oba stopnie)."""
    w = _world(api, two_stage=True)
    did = api.mk_user(w["sup"], "dyr", ["manager"], "Dyrektor")
    assert api.patch(f"/units/{w['unit']}", token=w["sup"],
                     json={"manager_user_id": did}).status_code == 200
    rid = _new_request(api, w)
    dyr = api.login("dyr")
    r = api.post(f"/requests/{rid}/workflow/action", token=dyr, json={
        "action": "select", "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, dyr) == "higher_manager_approve"
    r = api.post(f"/requests/{rid}/workflow/action", token=dyr, json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, dyr) == "it_execute"


# --- pusty wybór nie kasuje pozycji kadr --------------------------------------

def test_empty_select_does_not_wipe_hr_items(api):
    w = _world(api)
    # HR podpowiada pozycję (sam nie może wykonać wyboru → wniosek czeka na kierownika)
    rid = _new_request(api, w, items=[{"system_id": w["sid"], "permission_id": w["pid"]}])
    kier = api.login("kier")
    assert api.node_type(rid, kier) == "select_permissions"

    r = api.post(f"/requests/{rid}/workflow/action", token=kier,
                 json={"action": "select", "items": []})
    assert r.status_code == 400
    assert len(_items(rid)) == 1
    assert api.node_type(rid, kier) == "select_permissions"

    # Świadome potwierdzenie pustego wyboru nadal działa.
    r = api.post(f"/requests/{rid}/workflow/action", token=kier,
                 json={"action": "select", "items": [], "allow_empty": True})
    assert r.status_code == 200, r.text
    assert _items(rid) == []


# --- get_request / lista bez scope zwracają węzeł i can_act -------------------

def test_get_request_and_unscoped_list_expose_node_and_can_act(api):
    w = _world(api)
    rid = _new_request(api, w)
    kier, it = api.login("kier"), api.login("it")
    det = api.get(f"/requests/{rid}", token=kier).json()
    assert det["current_node_type"] == "select_permissions" and det["can_act"] is True
    det_it = api.get(f"/requests/{rid}", token=it).json()
    assert det_it["current_node_type"] == "select_permissions" and det_it["can_act"] is False
    row = next(x for x in api.get("/requests/", token=it).json() if x["id"] == rid)
    assert row["current_node_type"] == "select_permissions" and row["can_act"] is False


# --- powiadomienia ------------------------------------------------------------

def _capture_jobs(monkeypatch):
    import services.after_commit as ac
    jobs = []
    monkeypatch.setattr(ac, "_submit", lambda fn, kwargs: jobs.append((fn.__name__, kwargs)))
    return jobs


def test_no_select_mail_when_manager_submits_with_items(api, monkeypatch):
    w = _world(api)
    kier = api.login("kier")
    jobs = _capture_jobs(monkeypatch)
    rid = _new_request(api, w, token=kier,
                       items=[{"system_id": w["sid"], "permission_id": w["pid"]}])
    assert api.node_type(rid, kier) == "it_execute"
    stage = [kw for name, kw in jobs if name == "notify_workflow_stage"]
    assert not any(kw["node_type"] == "select_permissions" for kw in stage), stage
    assert any(name == "notify_helpdesk_new_request" for name, _ in jobs)


def test_higher_approval_without_manager_up_the_chain_notifies_unit_director(api, monkeypatch):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    did = api.mk_user(sup, "dyr", ["manager"], "Dyrektor Jednostki")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    assert api.patch(f"/units/{unit}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    # Komórka 2-stopniowa, której komórka nadrzędna (najwyższego poziomu) traci
    # kierownika (np. synchronizacja z AD) — w łańcuchu wyżej nie ma nikogo.
    # API nie pozwala tego skonfigurować wprost, więc zdejmujemy go w bazie.
    oid = api.mk_user(sup, "odszedl", ["manager"], "Były Kierownik")
    top = api.mk_department(sup, unit, oid, name="Top")
    dep = api.mk_department(sup, unit, kid, name="K", requires_higher_approval=True,
                            parent_dept_id=top)
    from models import Department
    with Session(engine) as s:
        d = s.get(Department, top); d.manager_user_id = None; s.add(d); s.commit()
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "X", "unit_id": unit, "department_id": dep, "items": [],
        "request_type_id": rtype}).json()["id"]
    jobs = _capture_jobs(monkeypatch)
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": [{"system_id": sid, "permission_id": pid}]}
    ).status_code == 200
    assert api.node_type(rid, kier) == "higher_manager_approve"
    to = [kw["to_address"] for name, kw in jobs
          if name == "notify_workflow_stage" and kw["node_type"] == "higher_manager_approve"]
    assert to == ["dyr@t.local"]
    det = api.get(f"/requests/{rid}", token=sup).json()
    assert "Dyrektor Jednostki" in (det["waiting_for"] or "")
    # Dyrektor może zatwierdzić (reguła przełożonego).
    assert api.post(f"/requests/{rid}/workflow/action", token=api.login("dyr"),
                    json={"action": "approve"}).status_code == 200


def test_deputy_of_department_without_manager_is_notified(api, monkeypatch):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kidP = api.mk_user(sup, "kierP", ["manager"], "Kier Nadrzędny")
    zid = api.mk_user(sup, "zast", ["manager"], "Zastępca Komórki")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, kidP, name="P")
    dep = api.mk_department(sup, unit, None, name="BezKier", parent_dept_id=parent)
    assert api.post(f"/units/departments/{dep}/deputies", token=sup,
                    json={"user_id": zid}).status_code == 201
    rtype = api.request_type(sup, "NEW_EMP")
    jobs = _capture_jobs(monkeypatch)
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "X", "unit_id": unit, "department_id": dep, "items": [],
        "request_type_id": rtype}).json()["id"]
    to = {kw["to_address"] for name, kw in jobs
          if name == "notify_workflow_stage" and kw["node_type"] == "select_permissions"}
    assert to == {"kierP@t.local", "zast@t.local"}
    det = api.get(f"/requests/{rid}", token=sup).json()
    assert "Zastępca Komórki" in (det["waiting_for"] or "")
