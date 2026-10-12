"""E2E: „Uprawnienia administratora" dostępne przy każdym oprogramowaniu.

Pozycja jest syntetyczna — utrzymuje ją router wg flagi `admin_option`, tak samo
jak „Dostęp" przy systemach access-only. Sprawdzamy, że:
  - powstaje domyślnie i nie miesza się ze zwykłą listą uprawnień,
  - nie blokuje trybu „tylko dostęp" ani pól wnioskodawcy,
  - nie liczy się do „program ma uprawnienia" (filtr „bez uprawnień"),
  - nie da się jej podrobić, przemianować ani skasować ręcznie,
  - znika po wyłączeniu flagi i wraca po ponownym włączeniu.
"""
from __future__ import annotations

ADMIN = "Uprawnienia administratora"


def _mk(api, sup, name, **extra):
    r = api.post("/systems/", token=sup, json={"name": name, "all_units": True, **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _perms(api, sup, sid):
    return api.get(f"/systems/{sid}/permissions", token=sup).json()


def _admin(api, sup, sid):
    return next((p for p in _perms(api, sup, sid) if p["is_admin_option"]), None)


def test_created_by_default_and_not_counted(api):
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program A")
    assert s["admin_option"] is True

    p = _admin(api, sup, s["id"])
    assert p is not None and p["permission_name"] == ADMIN

    # Sama obecność „super uprawnień" nie czyni programu skonfigurowanym —
    # inaczej filtr „bez uprawnień" przestałby cokolwiek pokazywać.
    row = next(x for x in api.get("/systems/", token=sup).json() if x["id"] == s["id"])
    assert row["permission_count"] == 0


def test_sorted_last(api):
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program B")
    for name in ("Zapis", "Odczyt"):
        api.post(f"/systems/{s['id']}/permissions", token=sup,
                 json={"permission_name": name})
    names = [p["permission_name"] for p in _perms(api, sup, s["id"])]
    assert names[-1] == ADMIN


def test_coexists_with_access_only(api):
    """Tryb „tylko dostęp" ma działać mimo obecnej pozycji administratora."""
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program C")
    r = api.patch(f"/systems/{s['id']}", token=sup, json={"access_only": True})
    assert r.status_code == 200, r.text
    assert {p["permission_name"] for p in _perms(api, sup, s["id"])} == {"Dostęp", ADMIN}


def test_coexists_with_custom_fields(api):
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program D")
    r = api.patch(f"/systems/{s['id']}", token=sup, json={
        "custom_fields": [{"label": "Moduły", "type": "text", "required": True}]})
    assert r.status_code == 200, r.text
    assert _admin(api, sup, s["id"]) is not None


def test_name_is_reserved(api):
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program E")

    # nie da się utworzyć ręcznie…
    r = api.post(f"/systems/{s['id']}/permissions", token=sup,
                 json={"permission_name": ADMIN})
    assert r.status_code == 400

    p = _admin(api, sup, s["id"])
    # …ani przemianować…
    r = api.patch(f"/systems/permissions/{p['id']}", token=sup,
                  json={"permission_name": "Cokolwiek"})
    assert r.status_code == 400
    # …ani skasować, dopóki opcja jest włączona.
    r = api.delete(f"/systems/permissions/{p['id']}", token=sup)
    assert r.status_code == 400


def test_toggle_off_and_on(api):
    sup = api.setup_superadmin()
    s = _mk(api, sup, "Program F")
    assert _admin(api, sup, s["id"]) is not None

    r = api.patch(f"/systems/{s['id']}", token=sup, json={"admin_option": False})
    assert r.status_code == 200, r.text
    assert r.json()["admin_option"] is False
    assert _admin(api, sup, s["id"]) is None

    api.patch(f"/systems/{s['id']}", token=sup, json={"admin_option": True})
    assert _admin(api, sup, s["id"]) is not None


def test_copy_permissions_ignores_admin_position(api):
    """Kopiowanie definicji nie przenosi pozycji syntetycznych."""
    sup = api.setup_superadmin()
    src = _mk(api, sup, "Wzorzec")
    api.post(f"/systems/{src['id']}/permissions", token=sup,
             json={"permission_name": "Odczyt"})
    dst = _mk(api, sup, "Cel")

    r = api.post(f"/systems/{dst['id']}/copy-permissions", token=sup,
                 json={"source_system_id": src["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["permissions_copied"] == 1

    names = [p["permission_name"] for p in _perms(api, sup, dst["id"])]
    assert names.count(ADMIN) == 1      # nie zdublowana kopiowaniem
    assert "Odczyt" in names
