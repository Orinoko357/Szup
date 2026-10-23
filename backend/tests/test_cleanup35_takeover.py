"""E2E: przejęcie wniosku, oddanie i przekazanie w IT (porządki 3.5).

- wyścig dwóch przełożonych: przegrany `claim_take_over` → 409 i brak śladów,
- `can_release` / „Oddaj” dla superadmina i poza etapem kierownika,
- walidacje `POST /requests/{id}/assign` (etap, ukryty etap roboczy, adresat)."""
from __future__ import annotations

from sqlmodel import Session, select

from database import engine
from models import AccessRequest, RequestEvent, User


def _world(api, two_stage=False):
    """Jednostka U: komórka P (kierownik `kierP`, zastępca `zastP`), pod nią K
    (kierownik `kier`). Dyrektor jednostki `dyr`, IT, kierownik IT, HR."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    zid = api.mk_user(sup, "zastP", ["manager"], "Zenon Zastępca")
    did = api.mk_user(sup, "dyr", ["manager"], "Dorota Dyrektor")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "itkier", ["manager", "it_staff"], "Kierownik IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    assert api.post(f"/units/departments/{parent}/deputies", token=sup,
                    json={"user_id": zid}).status_code == 201
    assert api.patch(f"/units/{unit}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"), pid_user=pid_user, did=did)


def _items(w):
    return [{"system_id": w["sid"], "permission_id": w["pid"]}]


def _create(api, w, token, **extra):
    r = api.post("/requests/", token=token, json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": _items(w), **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _det(api, rid, token):
    return api.get(f"/requests/{rid}", token=token).json()


def _event_actions(rid):
    with Session(engine) as s:
        return [e.action for e in s.exec(
            select(RequestEvent).where(RequestEvent.request_id == rid)
            .order_by(RequestEvent.id)).all()]


# ---------------------------------------------------------------------------
# Wyścig przejęcia
# ---------------------------------------------------------------------------

def test_take_over_race_loser_gets_409_and_leaves_no_trace(api, monkeypatch):
    """Dwóch przełożonych naraz: zastępca P przejmuje wniosek w chwili, gdy
    dyrektor jest już po walidacji `can_take_over`. Warunkowy UPDATE dyrektora
    nie trafia w wiersz → 409, przejęcie zostaje przy zastępcy."""
    import services.workflow as wf
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    zast, dyr = api.login("zastP"), api.login("dyr")
    assert _det(api, rid, dyr)["can_take_over"] is True

    real_claim = wf.claim_take_over
    calls = []

    def racing_claim(session, request, user, *, expected_taker_id, expected_node_id):
        # Konkurent zapisuje swoje przejęcie w osobnej transakcji tuż przed nami.
        if not calls:
            with Session(engine) as other:
                rival = other.exec(select(User).where(User.username == "zastP")).one()
                won = real_claim(other, other.get(AccessRequest, request.id), rival,
                                 expected_taker_id=None, expected_node_id=expected_node_id)
                other.commit()
                assert won is True
        calls.append(user.username)
        return real_claim(session, request, user, expected_taker_id=expected_taker_id,
                          expected_node_id=expected_node_id)

    monkeypatch.setattr(wf, "claim_take_over", racing_claim)
    r = api.post(f"/requests/{rid}/take-over", token=dyr)
    assert r.status_code == 409, r.text
    assert calls == ["dyr"]
    with Session(engine) as s:
        row = s.get(AccessRequest, rid)
        assert row.taken_over_by_name == "Zenon Zastępca"
    # Przegrany nie zostawia zdarzenia w historii wniosku.
    assert _event_actions(rid) == []
    monkeypatch.setattr(wf, "claim_take_over", real_claim)

    # Dyrektor stoi wyżej niż zastępca P — może przejąć ponownie (już bez wyścigu).
    assert _det(api, rid, zast)["can_take_over"] is False
    r = api.post(f"/requests/{rid}/take-over", token=dyr)
    assert r.status_code == 200, r.text
    assert r.json()["taken_over_by_name"] == "Dorota Dyrektor"
    assert _event_actions(rid) == ["take_over"]


def test_take_over_after_workflow_moved_on_is_409(api):
    """Odczytany węzeł jest już nieaktualny (kierownik zdążył wysłać) → 409."""
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": _items(w)}).status_code == 200
    r = api.post(f"/requests/{rid}/take-over", token=api.login("kierP"))
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# can_release / „Oddaj”
# ---------------------------------------------------------------------------

def test_superadmin_can_release_foreign_take_over(api):
    from services.workflow import can_release
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    kierP = api.login("kierP")
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200

    assert _det(api, rid, kierP)["can_release"] is True
    assert _det(api, rid, w["sup"])["can_release"] is True
    # Zastępca P (przełożony, ale nie przejmujący) nie oddaje cudzego przejęcia.
    zast = api.login("zastP")
    assert _det(api, rid, zast)["can_release"] is False
    assert api.post(f"/requests/{rid}/release", token=zast).status_code == 403
    with Session(engine) as s:
        root = s.exec(select(User).where(User.username == "root")).one()
        assert can_release(s, s.get(AccessRequest, rid), root) is True

    r = api.post(f"/requests/{rid}/release", token=w["sup"])
    assert r.status_code == 200, r.text
    assert r.json()["taken_over_by_id"] is None
    events = api.get(f"/requests/{rid}/workflow", token=w["sup"]).json()["events"]
    assert [e["action"] for e in events] == ["take_over", "release"]
    assert events[1]["note"] == "Zwolniono przejęcie: Anna Przełożona"
    # Nic do oddania → 409.
    assert api.post(f"/requests/{rid}/release", token=w["sup"]).status_code == 409


def test_release_not_possible_outside_manager_stage(api):
    from services.workflow import can_release
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    kierP = api.login("kierP")
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    # Przejmujący wysyła krok kierownika → realizacja IT; przejęcie zostaje w historii.
    assert api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "select", "items": _items(w)}).status_code == 200
    det = _det(api, rid, kierP)
    assert det["current_node_type"] == "it_execute"
    assert det["taken_over_by_id"] == w["pid_user"]
    assert det["can_release"] is False and det["manager_stage"] is False
    assert _det(api, rid, w["sup"])["can_release"] is False
    with Session(engine) as s:
        r = s.get(AccessRequest, rid)
        for name in ("root", "kierP"):
            u = s.exec(select(User).where(User.username == name)).one()
            assert can_release(s, r, u) is False, name
    assert api.post(f"/requests/{rid}/release", token=kierP).status_code == 409
    assert api.post(f"/requests/{rid}/release", token=w["sup"]).status_code == 409

    # Po zakończeniu obiegu — 409 (brak aktywnego kroku).
    assert api.post(f"/requests/{rid}/workflow/action", token=api.login("it"),
                    json={"action": "execute"}).status_code == 200
    assert api.post(f"/requests/{rid}/release", token=kierP).status_code == 409


# ---------------------------------------------------------------------------
# Przekazanie w IT (assign)
# ---------------------------------------------------------------------------

def test_assign_validations(api):
    w = _world(api, two_stage=True)
    kier, itk, it = api.login("kier"), api.login("itkier"), api.login("it")
    it_id = api.get("/auth/me", token=it).json()["id"]

    # Ukryta wersja robocza kierownika → 403 (IT jej „nie widzi”).
    draft = _create(api, w, kier, draft=True)
    r = api.post(f"/requests/{draft}/assign", token=itk, json={"user_id": it_id})
    assert r.status_code == 403
    assert "kierownika komórki" in r.json()["detail"]

    # Wniosek widoczny, ale na akceptacji wyższej (nie pending_it) → 409.
    higher = _create(api, w, kier)
    assert _det(api, higher, itk)["status"] == "pending_manager"
    assert api.post(f"/requests/{higher}/assign", token=itk,
                    json={"user_id": it_id}).status_code == 409

    # Po akceptacji wyższej — realizacja IT: walidacja adresata.
    assert api.post(f"/requests/{higher}/workflow/action", token=api.login("kierP"),
                    json={"action": "approve"}).status_code == 200
    assert _det(api, higher, itk)["status"] == "pending_it"
    # Zwykły pracownik IT (bez roli kierownika) nie przekazuje.
    assert api.post(f"/requests/{higher}/assign", token=it,
                    json={"user_id": it_id}).status_code == 403
    kier_id = api.get("/auth/me", token=kier).json()["id"]
    assert api.post(f"/requests/{higher}/assign", token=itk,
                    json={"user_id": kier_id}).status_code == 400
    assert api.post(f"/requests/{higher}/assign", token=itk,
                    json={"user_id": 999999}).status_code == 400
    r = api.post(f"/requests/{higher}/assign", token=itk, json={"user_id": it_id})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to_user_id"] == it_id
    assert r.json()["waiting_for"] == "IT: IT"
    # Zdjęcie przypisania.
    r = api.post(f"/requests/{higher}/assign", token=itk, json={"user_id": None})
    assert r.status_code == 200 and r.json()["assigned_to_user_id"] is None
    # Nieaktywny pracownik IT → 400.
    with Session(engine) as s:
        u = s.get(User, it_id)
        u.is_active = False
        s.add(u); s.commit()
    assert api.post(f"/requests/{higher}/assign", token=itk,
                    json={"user_id": it_id}).status_code == 400
    # Nieistniejący wniosek → 404.
    assert api.post("/requests/999999/assign", token=itk,
                    json={"user_id": None}).status_code == 404
