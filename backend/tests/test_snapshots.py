"""E2E: nocne migawki stanu upoważnień (historia „kto co miał danego dnia")."""
from __future__ import annotations

import re

from sqlmodel import Session, select

from database import engine
from models import PermissionSnapshot
from services.snapshots import create_snapshot, unpack


def _world(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="W", requires_higher_approval=False)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, sid=sid, pid=pid,
                hr=api.login("hr"), kier=api.login("kier"), it=api.login("it"))


def _grant(api, w, perm_name="Odczyt"):
    """Nadaj uprawnienie NOWEMU pracownikowi (pełny obieg do końca)."""
    r = api.mk_system_perm(w["sup"], "FK", perm_name) if perm_name != "Odczyt" else (w["sid"], w["pid"])
    sid, pid = r
    rid = api.post("/requests/", token=w["hr"], json={
        "worker_name": "Prac", "unit_id": w["unit"], "department_id": w["dep"],
        "items": [], "request_type_id": api.request_type(w["sup"], "NEW_EMP"),
    }).json()["id"]
    api.post(f"/requests/{rid}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}]})
    api.post(f"/requests/{rid}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "prac"})
    return rid


def test_snapshot_captures_effective_permissions(api):
    w = _world(api)
    _grant(api, w)

    r = api.post("/snapshots/run", token=w["sup"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", body["snapshot_date"])
    assert body["person_count"] == 1 and body["permission_count"] == 1
    assert len(body["content_sha256"]) == 64

    date = body["snapshot_date"]
    d = api.get(f"/snapshots/{date}", token=w["it"]).json()
    assert d["rows"][0]["worker_name"] == "Prac"
    assert d["rows"][0]["system_name"] == "FK"
    assert d["rows"][0]["permission_name"] == "Odczyt"
    # nadanie miało oświadczenie (conftest wstrzykuje) → kod jest w migawce
    assert d["rows"][0]["reference_code"]


def test_snapshot_is_immutable_after_later_revoke(api):
    """Sedno wymogu: po odebraniu uprawnienia migawka SPRZED nadal je pokazuje."""
    w = _world(api)
    _grant(api, w)

    # migawka „wczoraj" — ręcznie na konkretną datę
    with Session(engine) as s:
        snap = create_snapshot(s, generated_by="test", for_date="2026-07-20")
    assert snap.permission_count == 1
    worker = [r["worker_user_id"] for r in unpack(snap)["rows"]][0]

    # dziś: odbierz uprawnienie
    rid = api.post("/requests/", token=w["hr"], json={
        "worker_name": "Prac", "worker_user_id": worker,
        "unit_id": w["unit"], "department_id": w["dep"], "items": [], "kind": "revoke",
        "request_type_id": api.request_type(w["sup"], "REVOKE"),
    }).json()["id"]
    api.post(f"/requests/{rid}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "revoke"}]})
    api.post(f"/requests/{rid}/workflow/action", token=w["it"], json={"action": "execute"})

    # stan bieżący: pracownik już NIE ma uprawnienia
    eff = api.get(f"/users/{worker}/permissions", token=w["sup"]).json()
    assert eff["permissions"] == []

    # migawka historyczna: WCIĄŻ pokazuje, że tego dnia miał
    d = api.get("/snapshots/2026-07-20", token=w["it"]).json()
    assert len(d["rows"]) == 1
    assert d["rows"][0]["permission_name"] == "Odczyt"

    # a migawka „na dziś" — już pusta
    api.post("/snapshots/run", token=w["sup"])
    today = api.get("/snapshots", token=w["it"]).json()["items"][0]["snapshot_date"]
    if today != "2026-07-20":
        assert api.get(f"/snapshots/{today}", token=w["it"]).json()["rows"] == []


def test_snapshot_idempotent_per_day(api):
    w = _world(api)
    _grant(api, w)
    d1 = api.post("/snapshots/run", token=w["sup"]).json()["snapshot_date"]
    d2 = api.post("/snapshots/run", token=w["sup"]).json()["snapshot_date"]
    assert d1 == d2
    with Session(engine) as s:
        assert len(s.exec(select(PermissionSnapshot)).all()) == 1


def test_snapshot_content_hash_covers_data(api):
    """Suma kontrolna zależy od zawartości — zmiana stanu zmienia hash."""
    w = _world(api)
    with Session(engine) as s:
        empty = create_snapshot(s, generated_by="t", for_date="2026-01-01")
    _grant(api, w)
    with Session(engine) as s:
        full = create_snapshot(s, generated_by="t", for_date="2026-01-02")
    assert empty.content_sha256 != full.content_sha256
    assert empty.permission_count == 0 and full.permission_count == 1


def test_snapshot_csv_export(api):
    w = _world(api)
    _grant(api, w)
    date = api.post("/snapshots/run", token=w["sup"]).json()["snapshot_date"]
    r = api.get(f"/snapshots/{date}.csv", token=w["it"])
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "Prac" in r.text and "Kod oświadczenia" in r.text


def test_snapshots_require_it_staff(api):
    w = _world(api)
    assert api.get("/snapshots", token=w["kier"]).status_code == 403
    # generowanie ręczne — tylko admin (kierownik/IT nie)
    assert api.post("/snapshots/run", token=w["it"]).status_code == 403


def test_snapshot_schedule_is_configurable(api):
    """Superadmin zmienia porę/włącznik migawki w ustawieniach; scheduler czyta bazę."""
    sup = api.setup_superadmin()

    # domyślne 23:50, włączony
    s = api.get("/settings/app", token=sup).json()
    assert s["snapshot_enabled"] is True
    assert s["snapshot_hour"] == 23 and s["snapshot_minute"] == 50

    # zmiana pory + wyłączenie
    r = api.put("/settings/app", token=sup, json={
        "test_mode": False, "snapshot_enabled": False,
        "snapshot_hour": 2, "snapshot_minute": 15})
    assert r.status_code == 200, r.text
    assert r.json()["snapshot_hour"] == 2 and r.json()["snapshot_minute"] == 15
    assert r.json()["snapshot_enabled"] is False

    # scheduler czyta tę samą konfigurację z bazy
    from services.scheduler import _read_schedule, _seconds_until_next_run
    enabled, hour, minute = _read_schedule()
    assert (enabled, hour, minute) == (False, 2, 15)

    # walidacja zakresu (24 → przycięte do 23)
    r = api.put("/settings/app", token=sup, json={
        "test_mode": False, "snapshot_hour": 99, "snapshot_minute": 200})
    assert r.json()["snapshot_hour"] == 23 and r.json()["snapshot_minute"] == 59

    from datetime import datetime
    d = _seconds_until_next_run(datetime(2026, 7, 23, 10, 0, 0), 2, 15)
    assert 0 < d <= 24 * 3600
