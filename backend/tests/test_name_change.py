"""E2E: samodzielny wniosek pracownika o zmianę nazwiska (pracownik → IT)."""
from __future__ import annotations

from sqlmodel import Session, select

from database import engine
from models import User


def _world(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jkowalska", ["viewer"], "Joanna Kowalska")
    api.mk_user(sup, "it", ["it_staff"], "Iga IT")
    api.mk_user(sup, "kier", ["manager"], "Kier")
    return dict(sup=sup, emp=api.login("jkowalska"), it=api.login("it"),
                kier=api.login("kier"))


def test_employee_requests_own_name_change(api):
    w = _world(api)
    r = api.post("/name-changes", token=w["emp"],
                 json={"requested_full_name": "Joanna Nowak"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["requested_full_name"] == "Joanna Nowak"

    # własne zgłoszenia widoczne
    mine = api.get("/name-changes/mine", token=w["emp"]).json()
    assert len(mine) == 1

    # jeden aktywny na raz
    dup = api.post("/name-changes", token=w["emp"],
                   json={"requested_full_name": "Joanna X"})
    assert dup.status_code == 400

    # takie samo jak obecne → odrzucone
    api2 = api.post("/name-changes", token=w["emp"],
                    json={"requested_full_name": "Joanna Kowalska"})
    assert api2.status_code == 400


def test_it_applies_name_change_without_login_change(api):
    w = _world(api)
    rid = api.post("/name-changes", token=w["emp"],
                   json={"requested_full_name": "Joanna Nowak"}).json()["id"]

    r = api.post(f"/name-changes/{rid}/resolve", token=w["it"],
                 json={"action": "apply"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["username_changed"] is False

    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == "jkowalska")).first()
        assert u.full_name == "Joanna Nowak"     # nazwisko zmienione
        assert u.username == "jkowalska"          # login bez zmian


def test_it_applies_with_optional_login_change(api):
    w = _world(api)
    rid = api.post("/name-changes", token=w["emp"],
                   json={"requested_full_name": "Joanna Nowak"}).json()["id"]

    r = api.post(f"/name-changes/{rid}/resolve", token=w["it"],
                 json={"action": "apply", "new_username": "jnowak"})
    assert r.status_code == 200, r.text
    assert r.json()["username_changed"] is True
    assert r.json()["old_username"] == "jkowalska"
    assert r.json()["new_username"] == "jnowak"

    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == "jnowak")).first()
        assert u and u.full_name == "Joanna Nowak"

    # stary token (sub=stary login) już nie działa; nowy login działa dalej
    assert api.get("/name-changes/mine", token=w["emp"]).status_code == 401
    emp2 = api.login("jnowak")
    assert api.get("/name-changes/mine", token=emp2).json()[0]["status"] == "done"


def test_login_change_rejects_taken_username(api):
    w = _world(api)
    rid = api.post("/name-changes", token=w["emp"],
                   json={"requested_full_name": "Joanna Nowak"}).json()["id"]
    # login „kier" jest już zajęty
    r = api.post(f"/name-changes/{rid}/resolve", token=w["it"],
                 json={"action": "apply", "new_username": "kier"})
    assert r.status_code == 400 and "zaj" in r.text.lower()


def test_it_can_reject(api):
    w = _world(api)
    rid = api.post("/name-changes", token=w["emp"],
                   json={"requested_full_name": "Joanna Nowak"}).json()["id"]
    r = api.post(f"/name-changes/{rid}/resolve", token=w["it"],
                 json={"action": "reject", "comment": "brak dokumentu"})
    assert r.json()["status"] == "rejected"
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == "jkowalska")).first()
        assert u.full_name == "Joanna Kowalska"    # bez zmian
    # po rozpatrzeniu nie da się ponownie
    assert api.post(f"/name-changes/{rid}/resolve", token=w["it"],
                    json={"action": "apply"}).status_code == 400


def test_queue_requires_it_staff(api):
    w = _world(api)
    api.post("/name-changes", token=w["emp"],
             json={"requested_full_name": "Joanna Nowak"})
    # kierownik/pracownik nie widzą kolejki IT ani nie rozpatrują
    assert api.get("/name-changes", token=w["kier"]).status_code == 403
    assert api.get("/name-changes", token=w["emp"]).status_code == 403
