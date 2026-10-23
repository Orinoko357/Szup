"""Audyt 3.9: (1) samoprzydział przez późne dowiązanie konta — wniosek złożony
bez wskazania konta nie może zostać dowiązany do konta osoby, która go złożyła
lub wybrała w nim uprawnienia (bez akceptacji innej osoby); (3) uprawnienie
usunięte lub wygaszone nie może zostać ponownie nadane."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from database import engine
from models import SystemPermission, User
from tests.test_logic_fixes import _world


def _manager_files_without_worker(api, w):
    kier = api.login("kier")
    r = api.post("/requests/", token=kier, json={
        "worker_name": "Nowy Pracownik", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"],
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert api.node_type(rid, kier) == "it_execute"
    return rid


def test_execute_cannot_link_to_request_maker(api):
    w = _world(api)
    rid = _manager_files_without_worker(api, w)
    with Session(engine) as s:                      # konto kierownika w komórce wniosku
        u = s.get(User, w["kid"]); u.department_id = w["dep"]; s.add(u); s.commit()
    it = api.login("it")
    r = api.post(f"/requests/{rid}/workflow/action", token=it,
                 json={"action": "execute", "ad_username": "kier"})
    assert r.status_code == 409, r.text
    assert "dla siebie" in r.text
    # Nowe konto (inny login) — dozwolone.
    r = api.post(f"/requests/{rid}/workflow/action", token=it,
                 json={"action": "execute", "ad_username": "nowyprac"})
    assert r.status_code == 200, r.text


def test_link_worker_after_completion_cannot_target_maker(api):
    w = _world(api)
    rid = _manager_files_without_worker(api, w)
    it = api.login("it")
    assert api.post(f"/requests/{rid}/workflow/action", token=it,
                    json={"action": "execute"}).status_code == 200
    with Session(engine) as s:
        u = s.get(User, w["kid"]); u.department_id = w["dep"]; s.add(u); s.commit()
    r = api.post(f"/requests/{rid}/link-worker", token=it, json={"ad_username": "kier"})
    assert r.status_code == 409, r.text


def _delete_perm(pid):
    with Session(engine) as s:
        p = s.get(SystemPermission, pid)
        p.deleted_at = datetime.utcnow(); p.deleted_reason = "test"; p.is_active = False
        s.add(p); s.commit()


def test_deleted_permission_cannot_be_granted(api):
    w = _world(api)
    _delete_perm(w["pid"])
    kier = api.login("kier")
    r = api.post("/requests/", token=kier, json={
        "worker_name": "X", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"],
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 400, r.text
    assert "usunięte" in r.text


def test_deleted_permission_not_reselectable_in_flight(api):
    w = _world(api)
    hr = api.login("hr")
    r = api.post("/requests/", token=hr, json={
        "worker_name": "Ola", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": []})
    rid = r.json()["id"]
    _delete_perm(w["pid"])
    kier = api.login("kier")
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 400, r.text
    r = api.post(f"/requests/{rid}/draft", token=kier, json={
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}]})
    assert r.status_code == 400, r.text
