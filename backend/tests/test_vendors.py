"""E2E: słownik dostawców oprogramowania + umowy serwisowe."""
from __future__ import annotations

from datetime import datetime, timedelta


def _iso(days_from_today: int) -> str:
    """Data w formacie, jaki wysyła <input type="date"> (YYYY-MM-DD)."""
    return (datetime.utcnow().date() + timedelta(days=days_from_today)).isoformat()


def _mk_vendor(api, sup, name="Comarch", **extra):
    r = api.post("/vendors/", token=sup, json={"name": name, **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _add_contract(api, sup, vendor_id, days_to, days_from=-30, **extra):
    r = api.post(f"/vendors/{vendor_id}/contracts", token=sup, json={
        "valid_from": _iso(days_from), "valid_to": _iso(days_to), **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _status(api, sup, vendor_id):
    return [v for v in api.get("/vendors/", token=sup).json()
            if v["id"] == vendor_id][0]


# --- CRUD dostawcy ---------------------------------------------------------

def test_vendor_crud(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup, "Comarch", nip="1234567890",
                   address="Jana Pawła II 39a", postal_code="31-864", city="Kraków",
                   phone="12 111 22 33", email="serwis@comarch.pl")
    assert v["name"] == "Comarch" and v["city"] == "Kraków"
    assert v["status"] == "none", "bez umów status to 'none'"

    r = api.patch(f"/vendors/{v['id']}", token=sup, json={"city": "Warszawa"})
    assert r.status_code == 200 and r.json()["city"] == "Warszawa"

    assert api.delete(f"/vendors/{v['id']}", token=sup).status_code == 204
    assert api.get("/vendors/", token=sup).json() == []


def test_vendor_name_required(api):
    sup = api.setup_superadmin()
    assert api.post("/vendors/", token=sup, json={"name": "   "}).status_code == 400


# --- Status umów -----------------------------------------------------------

def test_status_active_when_any_contract_runs(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup)
    _add_contract(api, sup, v["id"], days_to=-100, days_from=-400)   # stara, wygasła
    _add_contract(api, sup, v["id"], days_to=200)                    # bieżąca
    st = _status(api, sup, v["id"])
    assert st["status"] == "active" and st["contract_count"] == 2
    assert st["days_left"] == 200


def test_contract_ending_today_is_still_active(api):
    """Dzień końcowy liczy się WŁĄCZNIE."""
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup)
    _add_contract(api, sup, v["id"], days_to=0)
    st = _status(api, sup, v["id"])
    assert st["status"] in ("active", "expiring"), st
    assert st["days_left"] == 0


def test_status_expired_and_expiring(api):
    sup = api.setup_superadmin()
    a = _mk_vendor(api, sup, "Wygasly")
    _add_contract(api, sup, a["id"], days_to=-1)
    assert _status(api, sup, a["id"])["status"] == "expired"

    b = _mk_vendor(api, sup, "Konczy")
    _add_contract(api, sup, b["id"], days_to=10)
    st = _status(api, sup, b["id"])
    assert st["status"] == "expiring" and st["days_left"] == 10


def test_contract_period_validated(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup)
    r = api.post(f"/vendors/{v['id']}/contracts", token=sup, json={
        "valid_from": _iso(10), "valid_to": _iso(1)})
    assert r.status_code == 400


def test_contract_crud(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup)
    c = _add_contract(api, sup, v["id"], days_to=30, contract_number="UM/2026/1")
    assert c["contract_number"] == "UM/2026/1"

    lst = api.get(f"/vendors/{v['id']}/contracts", token=sup).json()
    assert len(lst) == 1

    r = api.patch(f"/vendors/contracts/{c['id']}", token=sup,
                  json={"valid_to": _iso(400)})
    assert r.status_code == 200, r.text
    assert _status(api, sup, v["id"])["status"] == "active"

    assert api.delete(f"/vendors/contracts/{c['id']}", token=sup).status_code == 204
    assert _status(api, sup, v["id"])["status"] == "none"


def test_deleting_vendor_removes_its_contracts(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup)
    _add_contract(api, sup, v["id"], days_to=30)
    assert api.delete(f"/vendors/{v['id']}", token=sup).status_code == 204
    # dostawca zniknął — brak osieroconych umów (404 na liście umów)
    assert api.get(f"/vendors/{v['id']}/contracts", token=sup).status_code == 404


# --- Alerty na pulpit IT ---------------------------------------------------

def test_contract_alerts(api):
    sup = api.setup_superadmin()
    ok = _mk_vendor(api, sup, "Aktualny");  _add_contract(api, sup, ok["id"], days_to=300)
    ex = _mk_vendor(api, sup, "Wygasly");   _add_contract(api, sup, ex["id"], days_to=-5)
    so = _mk_vendor(api, sup, "Konczacy");  _add_contract(api, sup, so["id"], days_to=7)
    _mk_vendor(api, sup, "BezUmowy")

    r = api.get("/vendors/contract-alerts", token=sup)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["expired_count"] == 1 and d["expiring_count"] == 1
    assert d["expired"][0]["vendor_name"] == "Wygasly"
    assert d["expiring"][0]["vendor_name"] == "Konczacy"
    # aktualny i bez umowy nie alarmują
    names = {x["vendor_name"] for x in d["expired"] + d["expiring"]}
    assert "Aktualny" not in names and "BezUmowy" not in names


# --- Powiązanie z rejestrem oprogramowania ---------------------------------

def test_system_vendor_link(api):
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup, "Comarch")
    r = api.post("/systems/", token=sup, json={
        "name": "FK", "all_units": True, "vendor_id": v["id"]})
    assert r.status_code in (200, 201), r.text
    assert r.json()["vendor_id"] == v["id"]
    assert r.json()["vendor_name"] == "Comarch"

    sid = r.json()["id"]
    got = [x for x in api.get("/systems/", token=sup).json() if x["id"] == sid][0]
    assert got["vendor_name"] == "Comarch"

    # odpięcie dostawcy
    r2 = api.patch(f"/systems/{sid}", token=sup, json={"vendor_id": None})
    assert r2.status_code == 200 and r2.json()["vendor_id"] is None


def test_system_rejects_unknown_vendor(api):
    sup = api.setup_superadmin()
    r = api.post("/systems/", token=sup, json={
        "name": "FK", "all_units": True, "vendor_id": 9999})
    assert r.status_code == 400 and "dostawca" in r.text.lower()


def test_cannot_delete_vendor_used_by_system(api):
    """Ochrona: dostawca przypisany do programu nie znika po cichu."""
    sup = api.setup_superadmin()
    v = _mk_vendor(api, sup, "Comarch")
    api.post("/systems/", token=sup, json={
        "name": "FK (cuw)", "all_units": True, "vendor_id": v["id"]})

    r = api.delete(f"/vendors/{v['id']}", token=sup)
    assert r.status_code in (400, 409)
    assert "FK (cuw)" in r.text
