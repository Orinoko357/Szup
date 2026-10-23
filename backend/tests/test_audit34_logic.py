"""E2E: poprawki z audytu logiki 3.4 — cykl życia przejęcia, historia etapu
kierownika, assign/link-worker, filtr widoczności listy w SQL, wniosek składany
przez przełożonego, notatka kierownika, puste wersje robocze, szablony
z akceptacją kierownika, zgodność jednostki z komórką i nieaktywny kierownik."""
from __future__ import annotations

import json

from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, AuditLog, Department, RequestType, User,
    WorkflowTemplate,
)


def _world(api, two_stage=False):
    """Jednostka U: komórka P (kierownik `kierP`, zastępca `zastP`), pod nią K
    (kierownik `kier`). Dyrektor jednostki `dyr`, IT, kierownik IT, admin, HR."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    zid = api.mk_user(sup, "zastP", ["manager"], "Zenon Zastępca")
    did = api.mk_user(sup, "dyr", ["manager"], "Dorota Dyrektor")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "itkier", ["manager", "it_staff"], "Kierownik IT")
    api.mk_user(sup, "adm", ["admin"], "Admin")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    assert api.post(f"/units/departments/{parent}/deputies", token=sup,
                    json={"user_id": zid}).status_code == 201
    assert api.patch(f"/units/{unit}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    rtype = api.request_type(sup, "NEW_EMP")
    return dict(sup=sup, unit=unit, dep=dep, parent=parent, sid=sid, pid=pid,
                rtype=rtype, kid=kid, pid_user=pid_user, zid=zid, did=did)


def _item(w):
    return [{"system_id": w["sid"], "permission_id": w["pid"]}]


def _create(api, w, token, items=None, **extra):
    body = {"worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
            "request_type_id": w["rtype"], "items": items or [], **extra}
    return api.post("/requests/", token=token, json=body)


def _hr_request(api, w, items=None):
    r = _create(api, w, api.login("hr"), items=items)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _det(api, rid, token):
    return api.get(f"/requests/{rid}", token=token).json()


def _events(api, rid, token):
    return api.get(f"/requests/{rid}/workflow", token=token).json()["events"]


def _capture_jobs(monkeypatch):
    import services.after_commit as ac
    jobs = []
    monkeypatch.setattr(ac, "_submit", lambda fn, kwargs: jobs.append((fn.__name__, kwargs)))
    return jobs


# ---------------------------------------------------------------------------
# 1. Cykl życia przejęcia
# ---------------------------------------------------------------------------

def test_deactivated_taker_is_released_and_manager_regains(api, monkeypatch):
    w = _world(api)
    rid = _hr_request(api, w)
    kierP = api.login("kierP")
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    kier = api.login("kier")
    assert _det(api, rid, kier)["can_act"] is False

    jobs = _capture_jobs(monkeypatch)
    r = api.patch(f"/users/{w['pid_user']}", token=w["sup"], json={"is_active": False})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(AccessRequest, rid).taken_over_by_id is None
    # Kierownik komórki odzyskuje wniosek (i dostaje przypomnienie o etapie).
    assert any(n == "notify_workflow_stage" and kw["to_address"] == "kier@t.local"
               for n, kw in jobs)
    det = _det(api, rid, kier)
    assert det["can_act"] is True and det["taken_over_by_id"] is None
    assert api.post(f"/requests/{rid}/draft", token=kier, json={"items": _item(w)}
                    ).status_code == 200
    ev = _events(api, rid, kier)
    assert [e["action"] for e in ev] == ["take_over", "release", "draft"]
    assert ev[1]["actor_name"].startswith("SZUP")


def test_taker_who_lost_post_is_ignored_without_cleanup(api):
    """Przejmujący przestał być przełożonym (zmiana kierownika P bez dezaktywacji)
    — przejęcie wygasa: kierownik komórki działa, nowy przełożony może przejąć."""
    w = _world(api)
    rid = _hr_request(api, w)
    assert api.post(f"/requests/{rid}/take-over", token=api.login("kierP")).status_code == 200
    nowy = api.mk_user(w["sup"], "nowyP", ["manager"], "Nowy Przełożony")
    with Session(engine) as s:
        d = s.get(Department, w["parent"]); d.manager_user_id = nowy; s.add(d); s.commit()

    kier = api.login("kier")
    det = _det(api, rid, kier)
    assert det["can_act"] is True
    assert det["taken_over_by_id"] is None and det["taken_over_by_name"] is None
    nowyP = api.login("nowyP")
    assert _det(api, rid, nowyP)["can_take_over"] is True
    assert api.post(f"/requests/{rid}/take-over", token=nowyP).status_code == 200
    assert _det(api, rid, kier)["can_act"] is False


def test_retake_by_superior_above_current_taker(api, monkeypatch):
    w = _world(api)
    rid = _hr_request(api, w)
    zastP, kierP, dyr = api.login("zastP"), api.login("kierP"), api.login("dyr")

    assert api.post(f"/requests/{rid}/take-over", token=zastP).status_code == 200
    # Kierownik P stoi wyżej niż jego zastępca → może przejąć ponownie.
    assert _det(api, rid, kierP)["can_take_over"] is True
    jobs = _capture_jobs(monkeypatch)
    r = api.post(f"/requests/{rid}/take-over", token=kierP)
    assert r.status_code == 200, r.text
    assert r.json()["taken_over_by_name"] == "Anna Przełożona"
    # Poprzednio przejmujący dostaje informację.
    assert any(n == "notify_request_taken_over" and kw["to_address"] == "zastP@t.local"
               for n, kw in jobs)
    # Zastępca nie odbierze wniosku swojemu kierownikowi.
    assert api.post(f"/requests/{rid}/take-over", token=zastP).status_code == 409
    assert _det(api, rid, zastP)["can_act"] is False
    # Dyrektor jednostki stoi ponad wszystkimi komórkami.
    assert api.post(f"/requests/{rid}/take-over", token=dyr).status_code == 200
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 409
    assert _det(api, rid, dyr)["can_act"] is True

    ev = _events(api, rid, dyr)
    assert [e["action"] for e in ev] == ["take_over"] * 3
    assert ev[1]["note"] == "Przejęcie od: Zenon Zastępca"
    assert ev[2]["actor_name"] == "Dorota Dyrektor" and ev[2]["at"]


def test_release_returns_request_to_department_manager(api):
    w = _world(api)
    rid = _hr_request(api, w)
    kier, kierP, zastP = api.login("kier"), api.login("kierP"), api.login("zastP")

    assert api.post(f"/requests/{rid}/release", token=kierP).status_code == 409  # nieprzejęty
    out = api.post(f"/requests/{rid}/take-over", token=kierP).json()
    assert out["can_release"] is True
    assert _det(api, rid, kier)["can_release"] is False
    # Tylko przejmujący.
    assert api.post(f"/requests/{rid}/release", token=kier).status_code == 403
    assert api.post(f"/requests/{rid}/release", token=zastP).status_code == 403

    r = api.post(f"/requests/{rid}/release", token=kierP)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["taken_over_by_id"] is None and out["can_release"] is False
    assert out["can_take_over"] is True
    assert _det(api, rid, kier)["can_act"] is True

    # Superadmin nie działa w obiegu — cudzego przejęcia nie zwolni.
    assert api.post(f"/requests/{rid}/take-over", token=zastP).status_code == 200
    assert api.post(f"/requests/{rid}/release", token=w["sup"]).status_code == 403
    r = api.post(f"/requests/{rid}/release", token=zastP)
    assert r.status_code == 200, r.text
    ev = _events(api, rid, kier)
    assert [e["action"] for e in ev] == ["take_over", "release", "take_over", "release"]
    with Session(engine) as s:
        assert s.exec(select(AuditLog).where(
            AuditLog.action == "request.take_over_released")).first()

    # Po wysłaniu (poza etapem kierownika) oddać już nie można.
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    assert api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "select", "items": _item(w)}).status_code == 200
    assert api.post(f"/requests/{rid}/release", token=kierP).status_code == 409


def test_take_over_and_draft_are_conditional(api):
    """Ochrona przed wyścigiem: przejęcie to warunkowy UPDATE (na odczytanym
    przejmującym i węźle), wersja robocza sprawdza `expected_node_id`."""
    from services.workflow import claim_take_over
    w = _world(api)
    rid = _hr_request(api, w)
    with Session(engine) as s:
        r = s.get(AccessRequest, rid)
        u = s.get(User, w["pid_user"])
        node_id = api.get(f"/requests/{rid}/workflow", token=w["sup"]).json()["current_node_id"]
        # Węzeł zdążył się zmienić → brak zapisu.
        assert claim_take_over(s, r, u, expected_taker_id=None, expected_node_id="inny") is False
        # Ktoś inny przejął w międzyczasie (odczytany stan „nieprzejęty” jest nieaktualny).
        assert claim_take_over(s, r, u, expected_taker_id=None, expected_node_id=node_id) is True
        z = s.get(User, w["zid"])
        assert claim_take_over(s, r, z, expected_taker_id=None, expected_node_id=node_id) is False
        s.commit()
        assert s.get(AccessRequest, rid).taken_over_by_id == w["pid_user"]

    kierP = api.login("kierP")
    det = _det(api, rid, kierP)
    assert api.post(f"/requests/{rid}/draft", token=kierP, json={
        "items": _item(w), "expected_node_id": "stary-wezel"}).status_code == 409
    assert api.post(f"/requests/{rid}/draft", token=kierP, json={
        "items": _item(w), "expected_node_id": det["current_node_id"]}).status_code == 200


# ---------------------------------------------------------------------------
# 2–3. Historia, assign i link-worker
# ---------------------------------------------------------------------------

def test_assign_and_link_worker_respect_visibility_and_rules(api):
    w = _world(api)
    kier, itk, it = api.login("kier"), api.login("itkier"), api.login("it")
    draft = _create(api, w, kier, items=_item(w), draft=True).json()["id"]
    assert api.post(f"/requests/{draft}/assign", token=itk, json={"user_id": None}
                    ).status_code == 403
    assert api.post(f"/requests/{draft}/link-worker", token=it,
                    json={"ad_username": "ola.nowa"}).status_code == 403

    # Wniosek w realizacji IT — przypisanie dozwolone, z wpisem w dzienniku.
    rid = _create(api, w, kier, items=_item(w)).json()["id"]
    assert _det(api, rid, it)["current_node_type"] == "it_execute"
    it_id = api.get("/auth/me", token=it).json()["id"]
    r = api.post(f"/requests/{rid}/assign", token=itk, json={"user_id": it_id})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to_user_id"] == it_id
    with Session(engine) as s:
        row = s.exec(select(AuditLog).where(AuditLog.action == "request.assigned")).first()
        assert json.loads(row.details)["new_assigned_to_user_id"] == it_id

    # Wniosek nie w realizacji IT (np. u kierownika, widoczny) → 409.
    nomgr = api.mk_department(w["sup"], w["unit"], None, name="B", parent_dept_id=w["parent"])
    other = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "X", "unit_id": w["unit"], "department_id": nomgr,
        "request_type_id": w["rtype"], "items": []}).json()["id"]
    assert api.post(f"/requests/{other}/assign", token=itk, json={"user_id": None}
                    ).status_code == 409

    # link-worker: walidacja loginu, bez uzupełniania komórki istniejącego konta.
    assert api.post(f"/requests/{rid}/link-worker", token=it,
                    json={"ad_username": "zły login!"}).status_code == 400
    ex = api.mk_user(w["sup"], "ola.nowa", ["viewer"], "Ola Nowa")
    r = api.post(f"/requests/{rid}/link-worker", token=it,
                 json={"ad_username": "DOMENA\\Ola.Nowa"})
    assert r.status_code == 200, r.text
    assert r.json()["worker_user_id"] == ex
    with Session(engine) as s:
        assert s.get(User, ex).department_id is None
        row = s.exec(select(AuditLog).where(AuditLog.action == "request.worker_linked")).first()
        assert json.loads(row.details) == {"old_worker_user_id": None,
                                           "new_worker_user_id": ex,
                                           "ad_username": "ola.nowa"}
    # Wniosek z dowiązanym kontem — przepięcie niedozwolone.
    assert api.post(f"/requests/{rid}/link-worker", token=it,
                    json={"ad_username": "inny"}).status_code == 409


# ---------------------------------------------------------------------------
# 4. Filtr widoczności w SQL (LIMIT/OFFSET)
# ---------------------------------------------------------------------------

def test_list_limit_counts_only_visible_rows(api):
    from services.workflow import can_view_request
    w = _world(api)
    hr, kier = api.login("hr"), api.login("kier")
    nomgr = api.mk_department(w["sup"], w["unit"], None, name="B", parent_dept_id=w["parent"])
    visible = api.post("/requests/", token=hr, json={
        "worker_name": "Widoczny", "unit_id": w["unit"], "department_id": nomgr,
        "request_type_id": w["rtype"], "items": []}).json()["id"]
    hidden = [_create(api, w, kier, items=_item(w), draft=True).json()["id"] for _ in range(3)]

    it, adm = api.login("it"), api.login("adm")
    for tok in (it, adm):
        rows = api.get("/requests/", token=tok, params={"limit": 1}).json()
        assert [x["id"] for x in rows] == [visible]
        assert api.get("/requests/", token=tok, params={"limit": 1, "offset": 1}).json() == []

    # Lista zgadza się z `can_view_request` (jedyne źródło prawdy dla rekordu):
    # IT i admin widzą wszystko poza ukrytym etapem kierownika, pozostali —
    # podzbiór widocznych.
    all_ids = [visible, *hidden]
    from routers import auth as _auth
    for name in ("it", "adm", "hr", "kier", "kierP", "zastP", "dyr", "itkier"):
        _auth._ip_hits.clear()   # limiter prób logowania per IP
        listed = {x["id"] for x in api.get("/requests/", token=api.login(name)).json()}
        with Session(engine) as s:
            u = s.exec(select(User).where(User.username == name)).first()
            can = {rid for rid in all_ids if can_view_request(s, s.get(AccessRequest, rid), u)}
        assert listed <= can, name
        if name in ("it", "adm"):
            assert listed == can == {visible}, name
    assert {x["id"] for x in api.get("/requests/", token=kier).json()} >= set(hidden)


def test_taken_over_request_still_listed_for_manager_and_superiors(api):
    w = _world(api)
    rid = _hr_request(api, w)
    assert api.post(f"/requests/{rid}/take-over", token=api.login("kierP")).status_code == 200
    for name in ("kier", "zastP", "dyr"):
        rows = api.get("/requests/", token=api.login(name),
                       params={"scope": "manager", "active": True}).json()
        row = next(x for x in rows if x["id"] == rid)
        assert row["manager_stage"] is True and row["can_act"] is False
        assert row["taken_over_by_name"] == "Anna Przełożona"
    assert rid not in {x["id"] for x in api.get("/requests/", token=api.login("it")).json()}


# ---------------------------------------------------------------------------
# 5. Wniosek składany przez przełożonego
# ---------------------------------------------------------------------------

def test_superior_creating_request_takes_it_over(api, monkeypatch):
    w = _world(api)
    kierP = api.login("kierP")
    jobs = _capture_jobs(monkeypatch)
    r = _create(api, w, kierP, items=_item(w), draft=True)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["is_draft"] is True and out["can_act"] is True
    assert out["taken_over_by_name"] == "Anna Przełożona"
    assert not [kw for n, kw in jobs if n == "notify_workflow_stage"]
    det = _det(api, out["id"], api.login("kier"))
    assert det["can_act"] is False and det["taken_over_by_name"] == "Anna Przełożona"
    assert [e["action"] for e in _events(api, out["id"], kierP)] == ["take_over", "draft"]

    # Bez wersji roboczej — automatyczny wybór, wniosek idzie od razu do IT.
    r = _create(api, w, kierP, items=_item(w))
    assert r.status_code == 201, r.text
    assert r.json()["current_node_type"] == "it_execute"


# ---------------------------------------------------------------------------
# 6–7. Notatka kierownika i puste wersje robocze
# ---------------------------------------------------------------------------

def test_send_replaces_draft_note_and_clears_draft_flag(api):
    w = _world(api)
    rid = _hr_request(api, w, items=_item(w))
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/draft", token=kier, json={
        "items": _item(w), "comment": "Do uzupełnienia jutro"}).status_code == 200
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": _item(w)}).status_code == 200
    det = _det(api, rid, api.login("it"))
    assert det["manager_comment"] is None and det["draft_saved_at"] is None

    rid = _hr_request(api, w, items=_item(w))
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": _item(w), "comment": "Pilne"}).status_code == 200
    assert _det(api, rid, kier)["manager_comment"] == "Pilne"


def test_empty_draft_then_empty_select_requires_allow_empty(api):
    w = _world(api)
    rid = _hr_request(api, w)
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/draft", token=kier, json={"items": []}).status_code == 200
    r = api.post(f"/requests/{rid}/workflow/action", token=kier,
                 json={"action": "select", "items": []})
    assert r.status_code == 400
    assert api.node_type(rid, kier) == "select_permissions"
    r = api.post(f"/requests/{rid}/workflow/action", token=kier,
                 json={"action": "select", "items": [], "allow_empty": True})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 8. Szablon z akceptacją kierownika (manager_approve)
# ---------------------------------------------------------------------------

def _approve_type(w) -> int:
    graph = {"nodes": [
        {"id": "s", "type": "start", "label": "Start", "props": {}},
        {"id": "a", "type": "manager_approve", "label": "Akceptacja", "props": {}},
        {"id": "i", "type": "it_execute", "label": "IT", "props": {}},
        {"id": "e", "type": "end", "label": "Koniec", "props": {}}],
        "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "i"}, {"from": "i", "to": "e"}]}
    with Session(engine) as s:
        tpl = WorkflowTemplate(name="Akceptacja", graph_json=json.dumps(graph))
        s.add(tpl); s.flush()
        rt = RequestType(name="Akceptacja", code="APPR", workflow_template_id=tpl.id)
        s.add(rt); s.commit()
        return rt.id


def test_manager_approve_template_draft_and_auto_approve(api):
    w = _world(api)
    w["rtype"] = _approve_type(w)
    rid = _hr_request(api, w, items=_item(w))
    kier = api.login("kier")
    assert api.node_type(rid, kier) == "manager_approve"
    r = api.post(f"/requests/{rid}/draft", token=kier, json={"comment": "Sprawdzę"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["is_draft"] is True and out["manager_comment"] == "Sprawdzę"
    assert len(out["items"]) == 1 and out["next_node_type"] == "it_execute"
    assert api.post(f"/requests/{rid}/workflow/action", token=kier,
                    json={"action": "approve"}).status_code == 200
    assert api.node_type(rid, kier) == "it_execute"

    # Kierownik składa wniosek sam — akceptacja zaliczona automatycznie.
    r = _create(api, w, kier, items=_item(w))
    assert r.status_code == 201, r.text
    assert r.json()["current_node_type"] == "it_execute"
    # …albo zapisuje go roboczo.
    r = _create(api, w, kier, items=_item(w), draft=True)
    assert r.status_code == 201, r.text
    assert r.json()["current_node_type"] == "manager_approve" and r.json()["is_draft"]


# ---------------------------------------------------------------------------
# 9. next_node_type
# ---------------------------------------------------------------------------

def test_next_node_type_follows_engine_skip_logic(api):
    w = _world(api)
    rid = _hr_request(api, w)
    assert _det(api, rid, api.login("kier"))["next_node_type"] == "it_execute"
    with Session(engine) as s:
        d = s.get(Department, w["dep"]); d.requires_higher_approval = True; s.add(d); s.commit()
    assert _det(api, rid, api.login("kier"))["next_node_type"] == "higher_manager_approve"


# ---------------------------------------------------------------------------
# 10–11. Jednostka komórki i nieaktywny kierownik
# ---------------------------------------------------------------------------

def test_create_rejects_department_from_other_unit(api):
    w = _world(api)
    u2 = api.mk_unit(w["sup"], "U2", "U2")
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "X", "unit_id": u2, "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": []})
    assert r.status_code == 400
    assert "jednostki" in r.json()["detail"]


def test_inactive_manager_falls_back_up_the_chain(api, monkeypatch):
    from services.permissions import effective_manager_dept
    w = _world(api)
    with Session(engine) as s:
        u = s.get(User, w["kid"]); u.is_active = False; s.add(u); s.commit()
        assert effective_manager_dept(s, s.get(Department, w["dep"])).id == w["parent"]
    jobs = _capture_jobs(monkeypatch)
    rid = _hr_request(api, w)
    to = {kw["to_address"] for n, kw in jobs
          if n == "notify_workflow_stage" and kw["node_type"] == "select_permissions"}
    assert to == {"kierP@t.local", "zastP@t.local"}
    det = _det(api, rid, w["sup"])
    assert "Jan Kier" not in (det["waiting_for"] or "")
    assert "Anna Przełożona" in det["waiting_for"] or "Zenon" in det["waiting_for"]
    # Bez aktywnego kierownika nie ma etapu roboczego — przełożony działa od razu.
    assert det["manager_stage"] is False
    assert _det(api, rid, api.login("kierP"))["can_act"] is True


# ---------------------------------------------------------------------------
# 12–13. Szablony powiadomień i SMTP
# ---------------------------------------------------------------------------

def test_taken_over_and_name_change_mails_use_templates(monkeypatch):
    import services.email_alerts as mail
    from services.notifications import EVENTS
    sent = []
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, **kw: sent.append((to, subject, body)))
    mail.notify_request_taken_over("k@t.local", 7, "Ola", "K", "Anna")
    mail.notify_name_change_requested("Jan Nowak", "Jan Kowalski")
    assert sent[0][1] == "[SZUP] Wniosek #7 przejęty przez przełożonego"
    assert "Anna" in sent[0][2] and "requests?tab=handle&open=7" in sent[0][2]
    assert sent[1][1] == "[SZUP] Nowy wniosek o zmianę nazwiska"
    assert "Jan Kowalski" in sent[1][2] and "tab=names" in sent[1][2]
    assert {"request_taken_over", "name_change_requested"} <= set(EVENTS)


def test_smtp_auth_without_tls_is_refused(monkeypatch):
    import types
    import pytest
    import services.email_alerts as mail
    cfg = types.SimpleNamespace(enabled=True, smtp_host="smtp.t.local", smtp_port=25,
                                smtp_user="svc", smtp_password_enc=None, use_tls=False,
                                from_address="szup@t.local", to_address="",
                                sender_as_actor=False)
    monkeypatch.setattr(mail, "_get_settings", lambda: cfg)

    def _no_connect(*a, **kw):
        raise AssertionError("nie wolno łączyć się z SMTP")
    monkeypatch.setattr(mail.smtplib, "SMTP", _no_connect)
    with pytest.raises(RuntimeError):
        mail._send("x@t.local", "Test", "Treść", raise_errors=True)
    mail._send("x@t.local", "Test", "Treść")   # best-effort: bez wyjątku, bez wysyłki
