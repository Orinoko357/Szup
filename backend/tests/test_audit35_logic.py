"""E2E: poprawki logiki obiegu z audytu 3.5.

1. akceptacja wyższa — kierownik/zastępca własnej komórki dostaje 403 (także
   gdy jest zastępcą komórki nadrzędnej); wyjątek dyrektora jednostki zostaje,
2. zmiana struktury w trakcie obiegu (kierownik / podległość / dyrektor
   jednostki / zastępca) — nieważne przejęcie zwolnione ze zdarzeniem i mailem,
   „uśpione” przejęcie nie ożywa,
3. sprawca przejścia nie dostaje maila „czeka na Ciebie”,
4. akceptacja po wyborze bez uwag nie kasuje uwag z wyboru,
5. odrzucenie na etapie kierownika — powiadomienie kierownika komórki,
   notatka robocza nie wycieka,
6. „Oddaj” — warunkowy zapis (wyścig → 409, bez historii i maili),
7. link-worker — własne konto, konto z innej komórki, komórka kadrowa,
   zdarzenie bezpieczeństwa,
8. wygasłe przejęcie znika z bazy po wyjściu z etapu kierownika."""
from __future__ import annotations

import json

from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, Department, RequestEvent, RequestType, SecurityEvent, User,
    WorkflowTemplate,
)


# ---------------------------------------------------------------------------
# Wspólny świat i helpery
# ---------------------------------------------------------------------------

def _world(api, two_stage=False):
    """Jednostka U: komórka P (kierownik `kierP`, zastępca `zastP`), pod nią K
    (kierownik `kier`). Dyrektor jednostki `dyr`, IT, HR, zapasowy kierownik
    `kierX` (bez stanowiska)."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    zid = api.mk_user(sup, "zastP", ["manager"], "Zenon Zastępca")
    did = api.mk_user(sup, "dyr", ["manager"], "Dorota Dyrektor")
    xid = api.mk_user(sup, "kierX", ["manager"], "Xawery Nowy")
    it_id = api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    assert api.post(f"/units/departments/{parent}/deputies", token=sup,
                    json={"user_id": zid}).status_code == 201
    assert api.patch(f"/units/{unit}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, parent=parent, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"), kid=kid, pid_user=pid_user,
                zid=zid, did=did, xid=xid, it_id=it_id)


def _items(w):
    return [{"system_id": w["sid"], "permission_id": w["pid"]}]


def _create(api, w, token=None, **extra):
    body = {"worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
            "request_type_id": w["rtype"], "items": [], **extra}
    r = api.post("/requests/", token=token or api.login("hr"), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _act(api, rid, token, action, **extra):
    return api.post(f"/requests/{rid}/workflow/action", token=token,
                    json={"action": action, **extra})


def _det(api, rid, token):
    return api.get(f"/requests/{rid}", token=token).json()


def _row(rid) -> AccessRequest:
    with Session(engine) as s:
        return s.get(AccessRequest, rid)


def _events(rid):
    with Session(engine) as s:
        return [(e.action, e.actor_name, e.note) for e in s.exec(
            select(RequestEvent).where(RequestEvent.request_id == rid)
            .order_by(RequestEvent.id)).all()]


def _mails(monkeypatch):
    """Przechwyć powiadomienia: lista (klucz zdarzenia, adresat)."""
    import services.email_alerts as mail
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mail, "_send_event",
                        lambda key, to, ctx, **kw: sent.append((key, to)))
    return sent


def _stage_to(sent):
    return [to for key, to in sent if key == "workflow_stage"]


def _take_over(api, rid, username):
    r = api.post(f"/requests/{rid}/take-over", token=api.login(username))
    assert r.status_code == 200, r.text
    return r.json()


def _select_approve_type() -> int:
    """Obieg: wybór uprawnień → akceptacja kierownika → IT."""
    graph = {"nodes": [
        {"id": "s", "type": "start", "label": "Start", "props": {}},
        {"id": "w", "type": "select_permissions", "label": "Wybór", "props": {}},
        {"id": "a", "type": "manager_approve", "label": "Akceptacja", "props": {}},
        {"id": "i", "type": "it_execute", "label": "IT", "props": {}},
        {"id": "e", "type": "end", "label": "Koniec", "props": {}}],
        "edges": [{"from": "s", "to": "w"}, {"from": "w", "to": "a"},
                  {"from": "a", "to": "i"}, {"from": "i", "to": "e"}]}
    with Session(engine) as s:
        tpl = WorkflowTemplate(name="Wybór+akceptacja", graph_json=json.dumps(graph))
        s.add(tpl); s.flush()
        rt = RequestType(name="Wybór+akceptacja", code="SELAPP", workflow_template_id=tpl.id)
        s.add(rt); s.commit()
        return rt.id


# ---------------------------------------------------------------------------
# 1. Akceptacja wyższa — nie „sam u siebie”
# ---------------------------------------------------------------------------

def test_dept_manager_who_is_parent_deputy_cannot_do_higher_approval(api, monkeypatch):
    w = _world(api, two_stage=True)
    # Kierownik K jest też zastępcą kierownika komórki nadrzędnej P.
    assert api.post(f"/units/departments/{w['parent']}/deputies", token=w["sup"],
                    json={"user_id": w["kid"]}).status_code == 201
    rid = _create(api, w)
    kier = api.login("kier")
    sent = _mails(monkeypatch)
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, kier) == "higher_manager_approve"
    # Nie dostaje też „czeka na Ciebie” dla akceptacji wyższej.
    assert "kier@t.local" not in _stage_to(sent)
    assert {"kierP@t.local", "zastP@t.local"} <= set(_stage_to(sent))

    r = _act(api, rid, kier, "approve")
    assert r.status_code == 403, r.text
    assert "własnej komórki" in r.json()["detail"]
    assert _det(api, rid, kier)["can_act"] is False
    assert _act(api, rid, api.login("kierP"), "approve").status_code == 200
    assert api.node_type(rid, kier) == "it_execute"


def test_unit_director_managing_own_dept_keeps_higher_approval_exception(api):
    w = _world(api, two_stage=True)
    # Dyrektor jednostki kieruje też komórką K — wyjątek: akceptację wyższą wykona.
    assert api.patch(f"/units/departments/{w['dep']}", token=w["sup"],
                     json={"manager_user_id": w["did"]}).status_code == 200
    rid = _create(api, w)
    dyr = api.login("dyr")
    assert _act(api, rid, dyr, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, dyr) == "higher_manager_approve"
    r = _act(api, rid, dyr, "approve")
    assert r.status_code == 200, r.text
    assert api.node_type(rid, dyr) == "it_execute"


# ---------------------------------------------------------------------------
# 2. Zmiana struktury w trakcie obiegu
# ---------------------------------------------------------------------------

def _assert_auto_released(rid, sent):
    row = _row(rid)
    assert row.taken_over_by_id is None and row.taken_over_by_name is None
    ev = _events(rid)
    assert ev[-1][0] == "release" and ev[-1][1] == "SZUP (automatycznie)"
    assert "straciło ważność" in ev[-1][2]
    # Kierownik komórki odzyskuje wniosek i dostaje powiadomienie o etapie.
    assert "kier@t.local" in _stage_to(sent)


def test_parent_manager_change_clears_stale_take_over(api, monkeypatch):
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    r = api.patch(f"/units/departments/{w['parent']}", token=w["sup"],
                  json={"manager_user_id": w["xid"]})
    assert r.status_code == 200, r.text
    _assert_auto_released(rid, sent)
    assert _det(api, rid, api.login("kier"))["can_act"] is True


def test_parent_move_clears_stale_take_over(api, monkeypatch):
    w = _world(api)
    other = api.mk_department(w["sup"], w["unit"], w["xid"], name="Q")
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    r = api.patch(f"/units/departments/{w['dep']}", token=w["sup"],
                  json={"parent_dept_id": other})
    assert r.status_code == 200, r.text
    _assert_auto_released(rid, sent)
    # Nowy przełożony (kierownik Q) może przejąć, dawny już nie.
    assert _det(api, rid, api.login("kierX"))["can_take_over"] is True


def test_unit_director_change_clears_stale_take_over(api, monkeypatch):
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "dyr")
    sent = _mails(monkeypatch)
    r = api.patch(f"/units/{w['unit']}", token=w["sup"], json={"manager_user_id": w["xid"]})
    assert r.status_code == 200, r.text
    _assert_auto_released(rid, sent)


def test_deputy_removal_clears_take_over_of_that_deputy(api, monkeypatch):
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "zastP")
    deputies = api.get(f"/units/departments/{w['parent']}/deputies", token=w["sup"]).json()
    dep_row = next(d for d in deputies if d["user_id"] == w["zid"])
    sent = _mails(monkeypatch)
    assert api.delete(f"/units/departments/deputies/{dep_row['id']}",
                      token=w["sup"]).status_code == 204
    _assert_auto_released(rid, sent)


def test_valid_take_over_survives_unrelated_structure_change(api, monkeypatch):
    """Zmiana kierownika komórki nadrzędnej nie rusza przejęcia dyrektora."""
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "dyr")
    sent = _mails(monkeypatch)
    assert api.patch(f"/units/departments/{w['parent']}", token=w["sup"],
                     json={"manager_user_id": w["xid"]}).status_code == 200
    assert _row(rid).taken_over_by_name == "Dorota Dyrektor"
    assert _stage_to(sent) == []


def test_zombie_take_over_does_not_revive(api):
    """Przełożony traci stanowisko (przejęcie zwolnione), potem je odzyskuje —
    przejęcie NIE wraca, kierownik komórki dalej działa."""
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    assert api.patch(f"/units/departments/{w['parent']}", token=w["sup"],
                     json={"manager_user_id": w["xid"]}).status_code == 200
    assert api.patch(f"/units/departments/{w['parent']}", token=w["sup"],
                     json={"manager_user_id": w["pid_user"]}).status_code == 200
    assert _row(rid).taken_over_by_id is None
    assert _det(api, rid, api.login("kier"))["can_act"] is True


def test_legacy_stale_take_over_is_cleared_when_post_regained(api):
    """Przejęcie, które było nieważne już przed zmianą (np. dane sprzed
    poprawki), nie ożywa po przywróceniu stanowiska — zmiana struktury je
    sprząta."""
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    with Session(engine) as s:   # zmiana z pominięciem API → „uśpione” przejęcie
        p = s.get(Department, w["parent"]); p.manager_user_id = w["xid"]; s.add(p); s.commit()
    assert _row(rid).taken_over_by_id == w["pid_user"]
    assert api.patch(f"/units/departments/{w['parent']}", token=w["sup"],
                     json={"manager_user_id": w["pid_user"]}).status_code == 200
    assert _row(rid).taken_over_by_id is None
    assert _events(rid)[-1][:2] == ("release", "SZUP (automatycznie)")


# ---------------------------------------------------------------------------
# 3. Sprawca przejścia nie dostaje maila o własnym kroku
# ---------------------------------------------------------------------------

def test_taker_sending_two_stage_request_gets_no_self_mail(api, monkeypatch):
    w = _world(api, two_stage=True)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    kierP = api.login("kierP")
    assert _act(api, rid, kierP, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, kierP) == "higher_manager_approve"
    assert "kierP@t.local" not in _stage_to(sent)
    assert "zastP@t.local" in _stage_to(sent)
    # Krok zostaje (bez auto-akceptacji) — przejmujący wykonuje go sam.
    assert _det(api, rid, kierP)["can_act"] is True
    assert _act(api, rid, kierP, "approve").status_code == 200


# ---------------------------------------------------------------------------
# 4. Akceptacja po wyborze bez uwag
# ---------------------------------------------------------------------------

def test_approve_without_comment_keeps_select_note(api):
    w = _world(api)
    w["rtype"] = _select_approve_type()
    kier = api.login("kier")
    rid = _create(api, w)
    assert _act(api, rid, kier, "select", items=_items(w),
                comment="Uwagi z wyboru").status_code == 200
    assert api.node_type(rid, kier) == "manager_approve"
    # Notatka robocza na akceptacji nie może wyciec do IT.
    assert api.post(f"/requests/{rid}/draft", token=kier,
                    json={"comment": "Robocza"}).status_code == 200
    assert _act(api, rid, kier, "approve").status_code == 200
    assert _row(rid).manager_comment == "Uwagi z wyboru"

    rid2 = _create(api, w)
    assert _act(api, rid2, kier, "select", items=_items(w), comment="Stare").status_code == 200
    assert _act(api, rid2, kier, "approve", comment="  Nowe  ").status_code == 200
    assert _row(rid2).manager_comment == "Nowe"


# ---------------------------------------------------------------------------
# 5. Odrzucenie na etapie kierownika
# ---------------------------------------------------------------------------

def test_reject_by_taker_notifies_dept_circle_and_hides_draft_note(api, monkeypatch):
    w = _world(api)
    kier = api.login("kier")
    rid = _create(api, w)
    assert api.post(f"/requests/{rid}/draft", token=kier,
                    json={"comment": "Tajna notatka"}).status_code == 200
    _take_over(api, rid, "kierP")
    sent = _mails(monkeypatch)
    assert _act(api, rid, api.login("kierP"), "reject", comment="Nie teraz").status_code == 200
    rejected_to = {to for key, to in sent if key == "request_rejected"}
    assert {"hr@t.local", "kier@t.local"} <= rejected_to
    assert "kierP@t.local" not in rejected_to
    assert _row(rid).manager_comment == "Nie teraz"
    # IT widzi odrzucony wniosek — bez notatki roboczej.
    assert _det(api, rid, api.login("it"))["manager_comment"] == "Nie teraz"

    rid2 = _create(api, w)
    assert api.post(f"/requests/{rid2}/draft", token=kier,
                    json={"comment": "Tajna notatka"}).status_code == 200
    assert _act(api, rid2, kier, "reject").status_code == 200
    assert _row(rid2).manager_comment is None


# ---------------------------------------------------------------------------
# 6. „Oddaj” — warunkowy zapis
# ---------------------------------------------------------------------------

def test_release_race_with_re_take_over_is_409(api, monkeypatch):
    import services.workflow as wf
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    real_unclaim = wf.unclaim_take_over

    def racing_unclaim(session, request, *, expected_taker_id, expected_node_id):
        # Dyrektor (wyżej) przejmuje wniosek w osobnej transakcji tuż przed nami.
        with Session(engine) as other:
            dyr = other.exec(select(User).where(User.username == "dyr")).one()
            assert wf.claim_take_over(other, other.get(AccessRequest, request.id), dyr,
                                      expected_taker_id=expected_taker_id,
                                      expected_node_id=expected_node_id)
            other.commit()
        return real_unclaim(session, request, expected_taker_id=expected_taker_id,
                            expected_node_id=expected_node_id)

    monkeypatch.setattr(wf, "unclaim_take_over", racing_unclaim)
    sent = _mails(monkeypatch)
    r = api.post(f"/requests/{rid}/release", token=api.login("kierP"))
    assert r.status_code == 409, r.text
    assert _row(rid).taken_over_by_name == "Dorota Dyrektor"
    assert [e[0] for e in _events(rid)] == ["take_over"]   # brak „release”
    assert _stage_to(sent) == []


def test_unclaim_take_over_is_conditional(api):
    from services.workflow import instance_of, unclaim_take_over
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    with Session(engine) as s:
        r = s.get(AccessRequest, rid)
        node_id = instance_of(s, r).current_node_id
        # Nieaktualny odczyt (inny przejmujący / inny węzeł) → brak zmian.
        assert unclaim_take_over(s, r, expected_taker_id=w["did"],
                                 expected_node_id=node_id) is False
        assert unclaim_take_over(s, r, expected_taker_id=w["pid_user"],
                                 expected_node_id="inny") is False
        assert r.taken_over_by_id == w["pid_user"]
        assert unclaim_take_over(s, r, expected_taker_id=w["pid_user"],
                                 expected_node_id=node_id) is True
        assert r.taken_over_by_id is None
        s.commit()
    # Normalne „Oddaj” po fakcie — nic do oddania.
    assert api.post(f"/requests/{rid}/release",
                    token=api.login("kierP")).status_code == 409


# ---------------------------------------------------------------------------
# 7. link-worker
# ---------------------------------------------------------------------------

def _it_request(api, w, dept_id=None):
    """Wniosek w realizacji IT (bez dowiązanego konta)."""
    rid = _create(api, w, **({"department_id": dept_id} if dept_id else {}))
    kier = api.login("kier")
    if api.node_type(rid, kier) == "select_permissions":
        assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    return rid


def test_link_worker_rules(api):
    w = _world(api)
    it = api.login("it")
    rid = _it_request(api, w)
    # Własne konto — 403.
    r = api.post(f"/requests/{rid}/link-worker", token=it, json={"ad_username": "IT"})
    assert r.status_code == 403, r.text
    assert "własnego konta" in r.json()["detail"]
    # Konto z innej komórki — 409 z wyjaśnieniem.
    stranger = api.mk_user(w["sup"], "obcy", ["viewer"], "Obcy")
    with Session(engine) as s:
        u = s.get(User, stranger); u.department_id = w["parent"]; s.add(u); s.commit()
    r = api.post(f"/requests/{rid}/link-worker", token=it, json={"ad_username": "obcy"})
    assert r.status_code == 409, r.text
    assert "innej komórki" in r.json()["detail"]
    assert _row(rid).worker_user_id is None
    # Konto z tej samej komórki — OK; wniosek w toku → bez zdarzenia bezpieczeństwa.
    same = api.mk_user(w["sup"], "ola.nowa", ["viewer"], "Ola Nowa")
    with Session(engine) as s:
        u = s.get(User, same); u.department_id = w["dep"]; s.add(u); s.commit()
    r = api.post(f"/requests/{rid}/link-worker", token=it, json={"ad_username": "ola.nowa"})
    assert r.status_code == 200, r.text
    assert r.json()["worker_user_id"] == same
    with Session(engine) as s:
        assert not s.exec(select(SecurityEvent).where(
            SecurityEvent.event_type == "request.worker_linked")).all()


def test_link_worker_ghost_skips_hr_department(api):
    w = _world(api)
    hr_dept = api.mk_department(w["sup"], w["unit"], None, name="Kadry")
    assert api.patch(f"/units/departments/{hr_dept}", token=w["sup"],
                     json={"is_hr": True}).status_code == 200
    rid = _create(api, w, department_id=hr_dept)
    r = api.post(f"/requests/{rid}/link-worker", token=api.login("it"),
                 json={"ad_username": "nowy.kadrowy"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        ghost = s.exec(select(User).where(User.username == "nowy.kadrowy")).one()
        assert ghost.department_id is None
        assert r.json()["worker_user_id"] == ghost.id


def test_link_worker_on_completed_request_emits_security_event(api):
    w = _world(api)
    it = api.login("it")
    rid = _it_request(api, w)
    assert _act(api, rid, it, "execute").status_code == 200
    assert _row(rid).status == "completed"
    r = api.post(f"/requests/{rid}/link-worker", token=it, json={"ad_username": "pozny.wpis"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        ev = s.exec(select(SecurityEvent).where(
            SecurityEvent.event_type == "request.worker_linked")).one()
        assert ev.severity == "medium"
        assert json.loads(ev.details)["request_id"] == rid


# ---------------------------------------------------------------------------
# 8. Wygasłe przejęcie po wyjściu z etapu kierownika
# ---------------------------------------------------------------------------

def test_expired_take_over_is_cleared_after_send(api):
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    with Session(engine) as s:   # przejęcie wygasa z pominięciem porządków API
        p = s.get(Department, w["parent"]); p.manager_user_id = w["xid"]; s.add(p); s.commit()
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    row = _row(rid)
    assert row.taken_over_by_id is None and row.taken_over_by_name is None
    assert _det(api, rid, api.login("it"))["taken_over_by_name"] is None


def test_valid_take_over_is_kept_after_send(api):
    w = _world(api)
    rid = _create(api, w)
    _take_over(api, rid, "kierP")
    assert _act(api, rid, api.login("kierP"), "select", items=_items(w)).status_code == 200
    assert _row(rid).taken_over_by_name == "Anna Przełożona"
