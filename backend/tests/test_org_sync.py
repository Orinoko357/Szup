"""E2E: synchronizacja struktury ↔ rola „manager" (bez podwójnej roboty)."""
from __future__ import annotations


def _base(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "Urząd", "U")
    return sup, unit


def test_setting_department_manager_grants_manager_role(api):
    """Struktura → rola: wskazanie kierownika komórki nadaje rolę „manager"."""
    sup, unit = _base(api)
    uid = api.mk_user(sup, "nowak", ["viewer"], "Jan Nowak")
    api.mk_department(sup, unit, uid, name="Wydział A")

    u = api.get(f"/users/{uid}", token=sup)
    roles = (u.json() if u.status_code == 200 else
             next(x for x in api.get("/users/", token=sup).json() if x["id"] == uid))["roles"]
    assert "manager" in roles


def test_assigning_manager_role_and_department_makes_him_manager(api):
    """Rola → struktura: user z rolą „manager" w komórce BEZ kierownika obejmuje ją."""
    sup, unit = _base(api)
    dept = api.mk_department(sup, unit, None, name="Wydział B")
    uid = api.mk_user(sup, "kowal", ["manager"], "Ewa Kowal")
    # przypisz do komórki
    r = api.patch(f"/users/{uid}", token=sup, json={"department_id": dept})
    assert r.status_code == 200, r.text

    depts = api.get("/units/departments/all", token=sup).json()
    d = next(x for x in depts if x["id"] == dept)
    assert d["manager_user_id"] == uid


def test_existing_manager_is_not_silently_replaced(api):
    """Komórka z obsadzonym stanowiskiem NIE zmienia kierownika po cichu."""
    sup, unit = _base(api)
    first = api.mk_user(sup, "pierwszy", ["manager"], "Pierwszy Kier")
    dept = api.mk_department(sup, unit, first, name="Wydział C")
    second = api.mk_user(sup, "drugi", ["manager"], "Drugi Kier")

    api.patch(f"/users/{second}", token=sup, json={"department_id": dept})
    depts = api.get("/units/departments/all", token=sup).json()
    d = next(x for x in depts if x["id"] == dept)
    assert d["manager_user_id"] == first, "kierownik nie może zostać podmieniony po cichu"


def test_revoking_manager_role_releases_post(api):
    """Odebranie roli „manager" zwalnia stanowisko w strukturze."""
    sup, unit = _base(api)
    uid = api.mk_user(sup, "szef", ["manager"], "Szef")
    dept = api.mk_department(sup, unit, uid, name="Wydział D")

    r = api.patch(f"/users/{uid}", token=sup, json={"roles": ["viewer"]})
    assert r.status_code == 200, r.text
    depts = api.get("/units/departments/all", token=sup).json()
    d = next(x for x in depts if x["id"] == dept)
    assert d["manager_user_id"] is None


def test_changing_department_manager_moves_role(api):
    """Zmiana kierownika: nowy dostaje rolę, poprzedni ją traci (nic nie prowadzi)."""
    sup, unit = _base(api)
    old = api.mk_user(sup, "stary", ["viewer"], "Stary")
    new = api.mk_user(sup, "nowy", ["viewer"], "Nowy")
    dept = api.mk_department(sup, unit, old, name="Wydział E")

    r = api.patch(f"/units/departments/{dept}", token=sup, json={"manager_user_id": new})
    assert r.status_code == 200, r.text

    users = {x["id"]: x for x in api.get("/users/", token=sup).json()}
    assert "manager" in users[new]["roles"]
    assert "manager" not in users[old]["roles"]


def test_deputy_gets_manager_role_and_keeps_it_while_deputy(api):
    """Zastępca też działa w obiegu → dostaje rolę i traci ją dopiero po odpięciu."""
    sup, unit = _base(api)
    kier = api.mk_user(sup, "kier", ["manager"], "Kier")
    dept = api.mk_department(sup, unit, kier, name="Wydział F")
    zast = api.mk_user(sup, "zast", ["viewer"], "Zastępca")

    r = api.post(f"/units/departments/{dept}/deputies", token=sup, json={"user_id": zast})
    assert r.status_code in (200, 201), r.text
    users = {x["id"]: x for x in api.get("/users/", token=sup).json()}
    assert "manager" in users[zast]["roles"]

    dep_id = r.json()["id"]
    assert api.delete(f"/units/departments/deputies/{dep_id}", token=sup).status_code == 204
    users = {x["id"]: x for x in api.get("/users/", token=sup).json()}
    assert "manager" not in users[zast]["roles"]


def test_occupied_post_returns_warning(api):
    """Zajęte stanowisko → zapis się udaje, ale wraca czytelny komunikat."""
    sup, unit = _base(api)
    first = api.mk_user(sup, "szefa", ["manager"], "Anna Szefowa")
    dept = api.mk_department(sup, unit, first, name="Wydział G")
    second = api.mk_user(sup, "drugi2", ["manager"], "Drugi Kier")

    r = api.patch(f"/users/{second}", token=sup, json={"department_id": dept})
    assert r.status_code == 200, r.text
    w = r.json().get("warning")
    assert w, "oczekiwano komunikatu o zajętym stanowisku"
    assert "Wydział G" in w and "Anna Szefowa" in w


def test_free_post_has_no_warning(api):
    """Wolne stanowisko → brak ostrzeżenia, obejmuje komórkę."""
    sup, unit = _base(api)
    dept = api.mk_department(sup, unit, None, name="Wydział H")
    uid = api.mk_user(sup, "wolny", ["manager"], "Wolny Kier")
    r = api.patch(f"/users/{uid}", token=sup, json={"department_id": dept})
    assert r.status_code == 200
    assert not r.json().get("warning")
