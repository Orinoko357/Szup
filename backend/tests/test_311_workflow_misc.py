"""Poprawki obiegu 3.11 (agent A) — kontrakty i drobniejsze ustalenia:
/users/my-workers (landing_node_type, will_take_over), declaration_required,
mail „wniosek prowadzi przełożony” do zastępców, współbieżność wersji
roboczej (DRAFT_CHANGED), dowiązanie systemowych odebrań, wyrocznia
istnienia, zdarzenia domenowe w dzienniku, dostęp do uprawnień pracownika
(B6), podpisy HMAC kroków obiegu."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, AuditLog, RequestItem, RequestStatus, User, WorkflowInstance,
    WorkflowStep,
)
from test_audit35_logic import _act, _create, _det, _items, _take_over, _world
from test_310_workflow import DECL, _deputy, _set


# ---------------------------------------------------------------------------
# /users/my-workers — landing_node_type i will_take_over (kontrakt #5)
# ---------------------------------------------------------------------------

def test_my_workers_landing_matches_server(api):
    w = _world(api)
    zk = _deputy(api, w, "zastK")
    _set(User, zk, department_id=w["dep"])
    prac = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    _set(User, prac, department_id=w["dep"])
    _set(User, w["kid"], department_id=w["dep"])
    kier = api.login("kier")
    rows = {r["id"]: r for r in api.get("/users/my-workers", token=kier).json()}
    assert rows[prac]["landing_node_type"] == "it_execute"
    assert rows[prac]["will_take_over"] is False
    # Wniosek dla zastępcy K trafia do akceptacji przełożonego (NISKA 1).
    assert rows[zk]["landing_node_type"] == "higher_manager_approve"
    # Własny wiersz kierownika — „dla siebie” → przełożony.
    assert rows[w["kid"]]["is_self"] is True
    assert rows[w["kid"]]["landing_node_type"] == "higher_manager_approve"
    # Serwer składa wniosek tam, gdzie zapowiedział podgląd.
    r = api.post("/requests/", token=kier, json={
        "worker_name": "Zast", "worker_user_id": zk, "unit_id": w["unit"],
        "department_id": w["dep"], "kind": "change",
        "request_type_id": api.request_type(w["sup"], "MODIFY"), "items": _items(w)})
    assert r.status_code == 201, r.text
    assert api.node_type(r.json()["id"], kier) == "higher_manager_approve"
    # Przełożony (kierownik P) — przejmie wniosek i od razu wyśle do IT.
    rows = {r["id"]: r for r in api.get("/users/my-workers", token=api.login("kierP")).json()}
    assert rows[prac]["will_take_over"] is True
    assert rows[prac]["landing_node_type"] == "it_execute"
    assert rows[w["kid"]]["will_take_over"] is True
    assert rows[w["kid"]]["landing_node_type"] == "it_execute"


# ---------------------------------------------------------------------------
# declaration_required — odmówione pozycje się nie liczą (NISKA 2)
# ---------------------------------------------------------------------------

def test_higher_approval_with_all_grants_denied_needs_no_declaration(api):
    w = _world(api, two_stage=True)
    rid = _create(api, w)
    assert _act(api, rid, api.login("kier"), "select", items=_items(w)).status_code == 200
    kp = api.login("kierP")
    d = _det(api, rid, kp)
    assert d["declaration_required"] is True
    item_id = d["items"][0]["id"]
    r = api.post(f"/requests/{rid}/items/{item_id}/deny", token=kp,
                 json={"denied": True, "comment": "nie"})
    assert r.status_code == 200, r.text
    assert _det(api, rid, kp)["declaration_required"] is False
    r = _act(api, rid, kp, "approve", declaration=None)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Mail „wniosek prowadzi przełożony” — także do zastępców (NISKA 6)
# ---------------------------------------------------------------------------

def test_held_by_superior_mail_goes_to_deputies(api, monkeypatch):
    import services.email_alerts as mail
    w = _world(api)
    _deputy(api, w, "zastK")
    _set(User, w["kid"], email=None)       # kierownik bez adresu — zastępca i tak wie
    sent = []
    monkeypatch.setattr(mail, "_send_event",
                        lambda key, to, ctx, **kw: sent.append((key, to)))
    r = api.post("/requests/", token=api.login("kierP"), json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": [], "draft": True})
    assert r.status_code == 201, r.text
    held = sorted(to for key, to in sent if key == "request_held_by_superior")
    assert held == ["zastK@t.local"]


# ---------------------------------------------------------------------------
# Współbieżność wersji roboczej (kontrakt #3)
# ---------------------------------------------------------------------------

def test_draft_changed_conflict(api):
    w = _world(api)
    _deputy(api, w, "zastK")
    rid = _create(api, w)
    kier, zast = api.login("kier"), api.login("zastK")
    assert _det(api, rid, kier)["draft_saved_at"] is None
    # Kierownik zapisuje wersję roboczą, widząc „brak wersji”.
    r = api.post(f"/requests/{rid}/draft", token=kier,
                 json={"items": _items(w), "expected_draft_saved_at": None})
    assert r.status_code == 200, r.text
    stamp = r.json()["draft_saved_at"]
    assert stamp
    # Zastępca otworzył wniosek wcześniej (bez wersji) — jego zapis i wysyłka: 409.
    r = api.post(f"/requests/{rid}/draft", token=zast,
                 json={"items": [], "allow_empty": True, "expected_draft_saved_at": None})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DRAFT_CHANGED"
    r = _act(api, rid, zast, "select", items=_items(w), expected_draft_saved_at=None)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DRAFT_CHANGED"
    # Ze świeżym znacznikiem — wysyłka przechodzi (także z sufiksem „Z”).
    r = _act(api, rid, zast, "select", items=_items(w), expected_draft_saved_at=stamp + "Z")
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"
    # Bez pola — zachowanie jak dotąd (bez kontroli wersji).
    rid2 = _create(api, w)
    assert api.post(f"/requests/{rid2}/draft", token=kier,
                    json={"items": _items(w)}).status_code == 200
    assert _act(api, rid2, zast, "select", items=_items(w)).status_code == 200


# ---------------------------------------------------------------------------
# Dowiązanie konta — systemowe odebrania (N-3, N-6), wyrocznia istnienia (N-4)
# ---------------------------------------------------------------------------

def _system_revoke_for_unlinked(w):
    now = datetime.utcnow()
    with Session(engine) as s:
        g = AccessRequest(worker_name="Bez Konta", unit_id=w["unit"], department_id=w["dep"],
                          kind="grant", status=RequestStatus.completed, created_at=now,
                          completed_at=now, request_type_id=w["rtype"])
        s.add(g); s.flush()
        rv = AccessRequest(worker_name="Bez Konta", unit_id=w["unit"], department_id=w["dep"],
                           kind="revoke", status=RequestStatus.completed, created_at=now,
                           completed_at=now,
                           manager_comment="[SYSTEM] Usunięcie grupy uprawnień „G”: test")
        s.add(rv); s.flush()
        s.add(RequestItem(request_id=g.id, system_id=w["sid"], permission_id=w["pid"],
                          kind="grant", fulfilled=True, revoked_by_request_id=rv.id))
        s.add(RequestItem(request_id=rv.id, system_id=w["sid"], permission_id=w["pid"],
                          kind="revoke", fulfilled=True))
        s.commit()
        return g.id, rv.id


def test_system_revoke_link_only_through_source(api):
    w = _world(api)
    other = api.mk_user(w["sup"], "druga", ["viewer"], "Druga Osoba")
    _set(User, other, department_id=w["dep"])
    src, rev = _system_revoke_for_unlinked(w)
    it = api.login("it")
    r = api.post(f"/requests/{rev}/link-worker", token=it, json={"ad_username": "druga"})
    assert r.status_code == 409, r.text
    r = api.post(f"/requests/{src}/link-worker", token=it, json={"ad_username": "zlec"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        zid = s.exec(select(User).where(User.username == "zlec")).one().id
        assert s.get(AccessRequest, rev).worker_user_id == zid
    out = api.get(f"/users/{zid}/permissions", token=w["sup"]).json()
    assert out["permissions"] == []
    assert {h["id"] for h in out["requests"]} == {src, rev}


def test_foreign_request_is_404_like_missing(api):
    w = _world(api)
    rid = _create(api, w)
    api.mk_user(w["sup"], "zwykly", ["viewer"], "Zwykły")
    t = api.login("zwykly")
    a = api.get(f"/requests/{rid}", token=t)
    b = api.get("/requests/99999", token=t)
    assert a.status_code == b.status_code == 404
    assert a.json()["detail"] == b.json()["detail"]
    # Kierownik spoza zakresu — też 404.
    assert api.get(f"/requests/{rid}", token=api.login("kierX")).status_code == 404
    # IT widzi wnioski w toku, ale wersja robocza u kierownika — 403 (bez zmian).
    assert api.post(f"/requests/{rid}/draft", token=api.login("kier"),
                    json={"items": _items(w)}).status_code == 200
    assert api.get(f"/requests/{rid}", token=api.login("it")).status_code == 403
    # Superadmin i twórca — bez zmian.
    assert api.get(f"/requests/{rid}", token=w["sup"]).status_code == 200
    assert api.get(f"/requests/{rid}", token=api.login("hr")).status_code == 200


# ---------------------------------------------------------------------------
# Zdarzenia domenowe w dzienniku audytu (N6 z 3.9)
# ---------------------------------------------------------------------------

def _audit(action):
    with Session(engine) as s:
        return [(a.target_id, a.username) for a in s.exec(
            select(AuditLog).where(AuditLog.action == action)).all()]


def test_domain_audit_events(api):
    w = _world(api)
    rid = _create(api, w)
    rid2 = _create(api, w)
    assert (str(rid), "hr") in _audit("request.created")
    kier = api.login("kier")
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    assert _act(api, rid, api.login("it"), "execute").status_code == 200
    assert (str(rid), "it") in _audit("request.completed")
    assert _act(api, rid2, kier, "reject", comment="niepotrzebne").status_code == 200
    assert (str(rid2), "kier") in _audit("request.rejected")


# ---------------------------------------------------------------------------
# B6 — GET /users/{id}/permissions wymaga relacji albo roli
# ---------------------------------------------------------------------------

def test_user_permissions_requires_relation(api):
    w = _world(api)
    prac = api.mk_user(w["sup"], "prac", ["viewer"], "Paweł Pracownik")
    inny = api.mk_user(w["sup"], "inny", ["viewer"], "Inny Pracownik")
    _set(User, prac, department_id=w["dep"])
    _set(User, inny, department_id=w["dep"])
    path = f"/users/{prac}/permissions"
    assert api.get(path, token=api.login("inny")).status_code == 403
    assert api.get(path, token=api.login("kierX")).status_code == 403
    for who in ("prac", "kier", "kierP", "dyr", "hr", "it"):
        assert api.get(path, token=api.login(who)).status_code == 200, who
    assert api.get(path, token=w["sup"]).status_code == 200
    assert api.get(f"/users/{2 ** 63}/permissions", token=w["sup"]).status_code == 404


# ---------------------------------------------------------------------------
# Łańcuch podpisów — HMAC-SHA256 z wersją, stare podpisy sha256 nadal ważne
# ---------------------------------------------------------------------------

def _chain(rid):
    with Session(engine) as s:
        inst = s.exec(select(WorkflowInstance).where(WorkflowInstance.request_id == rid)).one()
        return inst.id, s.exec(select(WorkflowStep).where(WorkflowStep.instance_id == inst.id)
                               .order_by(WorkflowStep.step_index)).all()


def _verify(api, rid, token):
    return api.get(f"/requests/{rid}/workflow/verify", token=token).json()["chain_valid"]


def _data(st):
    return {"step_index": st.step_index, "node_id": st.node_id, "node_type": st.node_type,
            "action": getattr(st.action, "value", st.action),
            "actor_user_id": st.actor_user_id, "payload": st.payload, "comment": st.comment,
            "created_at": st.created_at.isoformat() if st.created_at else None}


def test_new_steps_signed_with_hmac(api):
    from services.workflow import SIGN_PREFIX_HMAC
    w = _world(api)
    rid = _create(api, w)
    _iid, steps = _chain(rid)
    assert steps and all(st.signature.startswith(SIGN_PREFIX_HMAC) for st in steps)
    assert _verify(api, rid, w["sup"]) is True
    with Session(engine) as s:
        st = s.get(WorkflowStep, steps[-1].id)
        st.comment = "podmieniony"
        s.add(st); s.commit()
    assert _verify(api, rid, w["sup"]) is False


def test_legacy_sha256_chain_still_valid(api):
    from services.workflow import _sign_legacy
    w = _world(api)
    rid = _create(api, w)
    _iid, steps = _chain(rid)
    # Przepisz łańcuch na podpisy sprzed 3.11 (sha256 bez przedrostka).
    with Session(engine) as s:
        prev = None
        for st in steps:
            row = s.get(WorkflowStep, st.id)
            row.prev_signature = prev
            row.signature = _sign_legacy(prev, _data(row))
            prev = row.signature
            s.add(row)
        s.commit()
    assert _verify(api, rid, w["sup"]) is True
    # Kolejny krok dopisany już HMAC-iem — łańcuch mieszany jest ważny.
    assert _act(api, rid, api.login("kier"), "select", items=_items(w)).status_code == 200
    _iid, steps = _chain(rid)
    assert not steps[0].signature.startswith("hmac1:")
    assert steps[-1].signature.startswith("hmac1:")
    assert _verify(api, rid, w["sup"]) is True
    # Manipulacja starym krokiem nadal wykrywana.
    with Session(engine) as s:
        row = s.get(WorkflowStep, steps[0].id)
        row.comment = "zmiana"
        s.add(row); s.commit()
    assert _verify(api, rid, w["sup"]) is False


def test_execute_unlinked_system_revoke_ignores_ad_login(api):
    """IT realizuje systemowe odebranie posiadacza bez konta — login AD nie
    przepina wniosku na wskazane konto (N-3); konto przyjdzie z wnioskiem nadania."""
    import json as _json
    from models import WorkflowTemplate
    from services.workflow import start_instance
    w = _world(api)
    other = api.mk_user(w["sup"], "druga", ["viewer"], "Druga Osoba")
    _set(User, other, department_id=w["dep"])
    g = {"nodes": [{"id": "s", "type": "start", "label": "s", "props": {}},
                   {"id": "i", "type": "it_execute", "label": "IT", "props": {}},
                   {"id": "e", "type": "end", "label": "e", "props": {}}],
         "edges": [{"from": "s", "to": "i"}, {"from": "i", "to": "e"}]}
    with Session(engine) as s:
        tpl = WorkflowTemplate(name="[SYSTEM] test", graph_json=_json.dumps(g), is_active=False)
        s.add(tpl); s.flush()
        rv = AccessRequest(worker_name="Bez Konta", unit_id=w["unit"], department_id=w["dep"],
                           kind="revoke", status=RequestStatus.pending_it,
                           manager_comment="[SYSTEM] Usunięcie grupy uprawnień „G”: test")
        s.add(rv); s.flush()
        s.add(RequestItem(request_id=rv.id, system_id=w["sid"], permission_id=w["pid"],
                          kind="revoke"))
        start_instance(s, rv, tpl)
        s.commit()
        rid = rv.id
    it = api.login("it")
    assert _det(api, rid, it)["is_system"] is True
    r = _act(api, rid, it, "execute", ad_username="druga")
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(AccessRequest, rid).worker_user_id is None
        assert s.get(AccessRequest, rid).status == RequestStatus.completed
