"""E2E: kolejność programów na wniosku + „domyślnie zaznaczone"."""
from __future__ import annotations


def _mk(api, sup, name, **extra):
    r = api.post("/systems/", token=sup, json={
        "name": name, "all_units": True, **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_numbered_first_then_alphabetical(api):
    """Ponumerowane rosnąco, reszta alfabetycznie ZA nimi."""
    sup = api.setup_superadmin()
    _mk(api, sup, "Zebra")                       # bez numeru
    _mk(api, sup, "Alfa")                        # bez numeru
    _mk(api, sup, "Trzeci", display_order=3)
    _mk(api, sup, "Pierwszy", display_order=1)

    names = [s["name"] for s in api.get("/systems/", token=sup).json()]
    assert names == ["Pierwszy", "Trzeci", "Alfa", "Zebra"], names


def test_duplicate_order_is_rejected(api):
    """Zajęty numer blokuje zapis — z nazwą kolidującego programu."""
    sup = api.setup_superadmin()
    _mk(api, sup, "Poczta", display_order=1)
    r = api.post("/systems/", token=sup, json={
        "name": "Portal", "all_units": True, "display_order": 1})
    assert r.status_code == 400
    assert "Poczta" in r.text and "1" in r.text


def test_keeping_own_order_is_not_a_conflict(api):
    """Zapis programu z jego własnym, niezmienionym numerem przechodzi."""
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Poczta", display_order=2)
    r = api.patch(f"/systems/{s['id']}", token=sup,
                  json={"display_order": 2, "description": "opis"})
    assert r.status_code == 200, r.text
    assert r.json()["display_order"] == 2


def test_order_must_be_positive(api):
    sup = api.setup_superadmin()
    r = api.post("/systems/", token=sup, json={
        "name": "Zly", "all_units": True, "display_order": 0})
    assert r.status_code == 400


def test_order_can_be_cleared(api):
    """Wyczyszczenie numeru przenosi program do części alfabetycznej."""
    sup = api.setup_superadmin()
    _mk(api, sup, "Alfa")
    s = _mk(api, sup, "Zebra", display_order=1)
    assert [x["name"] for x in api.get("/systems/", token=sup).json()] == ["Zebra", "Alfa"]

    r = api.patch(f"/systems/{s['id']}", token=sup, json={"display_order": None})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in api.get("/systems/", token=sup).json()] == ["Alfa", "Zebra"]


def test_default_checked_roundtrip(api):
    """Flaga „domyślnie zaznaczone" przechodzi przez create i update."""
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Portal", default_checked=True)
    assert s["default_checked"] is True

    got = [x for x in api.get("/systems/", token=sup).json() if x["id"] == s["id"]][0]
    assert got["default_checked"] is True

    r = api.patch(f"/systems/{s['id']}", token=sup, json={"default_checked": False})
    assert r.status_code == 200 and r.json()["default_checked"] is False


def test_defaults_when_not_specified(api):
    """Bez podania pól: brak numeru, niezaznaczone — zgodnie z dotychczasowym zachowaniem."""
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Zwykly")
    assert s["display_order"] is None and s["default_checked"] is False
