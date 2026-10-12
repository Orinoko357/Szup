"""E2E: kopiowanie definicji uprawnień między programami."""
from __future__ import annotations

# Uprawnienie z kontrolką opisową — wzorzec kopiowany między programami.
SCOPE_PERM = {"permission_name": "Zakres uprawnień", "input_type": "textarea",
              "input_required": True, "description": "Moduły lub rejestry"}


def _own_perms(api, sup, sid):
    """Uprawnienia programu bez pozycji syntetycznej „Uprawnienia administratora"
    — ta jest niezależna od kopiowanej definicji."""
    return [p for p in api.get(f"/systems/{sid}/permissions", token=sup).json()
            if not p["is_admin_option"]]


def test_copy_carries_input_controls(api):
    """Główny scenariusz: programy dodane bez poziomów → kopiujemy wzorzec.

    Kopia musi zabrać ze sobą KONTROLKĘ uprawnienia, nie samą nazwę —
    inaczej wzorzec zamieniłby się w płaską listę checkboxów.
    """
    sup = api.setup_superadmin()
    src = api.post("/systems/", token=sup, json={
        "name": "FK", "all_units": True}).json()["id"]
    api.post(f"/systems/{src}/permissions", token=sup, json=SCOPE_PERM)
    dst = api.post("/systems/", token=sup, json={
        "name": "Kadry", "all_units": True}).json()["id"]

    r = api.post(f"/systems/{dst}/copy-permissions", token=sup,
                 json={"source_system_id": src})
    assert r.status_code == 200, r.text
    assert r.json()["permissions_copied"] == 1

    got = _own_perms(api, sup, dst)
    assert len(got) == 1
    assert got[0]["permission_name"] == "Zakres uprawnień"
    assert got[0]["input_type"] == "textarea"
    assert got[0]["input_required"] is True


def test_copy_permission_list(api):
    """Gdy źródło ma listę predefiniowaną — kopiujemy pozycje listy."""
    sup = api.setup_superadmin()
    src = api.post("/systems/", token=sup, json={"name": "SrcLista", "all_units": True}).json()["id"]
    for n in ("Odczyt", "Zapis"):
        api.post(f"/systems/{src}/permissions", token=sup, json={"permission_name": n})
    dst = api.post("/systems/", token=sup, json={"name": "DstLista", "all_units": True}).json()["id"]

    r = api.post(f"/systems/{dst}/copy-permissions", token=sup,
                 json={"source_system_id": src})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "list" and r.json()["permissions_copied"] == 2
    names = {p["permission_name"] for p in _own_perms(api, sup, dst)}
    assert names == {"Odczyt", "Zapis"}


def test_copy_is_idempotent(api):
    """Powtórne kopiowanie listy nie duplikuje pozycji."""
    sup = api.setup_superadmin()
    src = api.post("/systems/", token=sup, json={"name": "S", "all_units": True}).json()["id"]
    api.post(f"/systems/{src}/permissions", token=sup, json={"permission_name": "Odczyt"})
    dst = api.post("/systems/", token=sup, json={"name": "D", "all_units": True}).json()["id"]

    api.post(f"/systems/{dst}/copy-permissions", token=sup, json={"source_system_id": src})
    r2 = api.post(f"/systems/{dst}/copy-permissions", token=sup, json={"source_system_id": src})
    assert r2.status_code == 200
    assert r2.json()["permissions_copied"] == 0
    assert len(_own_perms(api, sup, dst)) == 1


def test_copy_blocked_when_target_permission_used_in_request(api):
    """Historia wniosków chroniona — nie kasujemy użytych uprawnień."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")

    dst = api.post("/systems/", token=sup, json={"name": "Uzywany", "all_units": True}).json()["id"]
    pid = api.post(f"/systems/{dst}/permissions", token=sup,
                   json={"permission_name": "Odczyt"}).json()["id"]
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    api.post(f"/requests/{rid}/workflow/action", token=api.login("kier"), json={
        "action": "select",
        "items": [{"system_id": dst, "permission_id": pid, "kind": "grant"}]})

    src = api.post("/systems/", token=sup, json={
        "name": "Wzorzec", "all_units": True}).json()["id"]
    api.post(f"/systems/{src}/permissions", token=sup, json=SCOPE_PERM)
    r = api.post(f"/systems/{dst}/copy-permissions", token=sup,
                 json={"source_system_id": src})
    # Kopiowanie DOKŁADA pozycje, nie kasuje istniejących — użyte we wnioskach
    # „Odczyt" zostaje nietknięte i nie blokuje operacji.
    assert r.status_code == 200, r.text
    names = {p["permission_name"] for p in _own_perms(api, sup, dst)}
    assert names == {"Odczyt", "Zakres uprawnień"}


def test_cannot_copy_from_itself(api):
    sup = api.setup_superadmin()
    sid = api.post("/systems/", token=sup, json={
        "name": "X", "all_units": True}).json()["id"]
    r = api.post(f"/systems/{sid}/copy-permissions", token=sup,
                 json={"source_system_id": sid})
    assert r.status_code == 400


def test_set_default_definition(api):
    """„Ustaw domyślne" na istniejącym programie bez poziomów uprawnień."""
    sup = api.setup_superadmin()
    sid = api.post("/systems/", token=sup, json={
        "name": "BezPoziomow", "all_units": True}).json()["id"]

    r = api.post(f"/systems/{sid}/copy-permissions", token=sup,
                 json={"use_default": True})
    assert r.status_code == 200, r.text
    assert r.json()["permissions_copied"] == 1

    got = _own_perms(api, sup, sid)
    assert len(got) == 1
    p = got[0]
    assert p["permission_name"] == "Zakres uprawnień"
    assert p["input_type"] == "textarea" and p["input_required"] is True
    assert "moduły lub rejestry" in (p["description"] or "")


def test_set_default_keeps_existing_permissions(api):
    """„Ustaw domyślne" DOKŁADA pozycję, nie kasuje historii wniosków."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid = api.post("/systems/", token=sup, json={"name": "Uzyw", "all_units": True}).json()["id"]
    pid = api.post(f"/systems/{sid}/permissions", token=sup,
                   json={"permission_name": "Odczyt"}).json()["id"]
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    api.post(f"/requests/{rid}/workflow/action", token=api.login("kier"), json={
        "action": "select",
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}]})

    r = api.post(f"/systems/{sid}/copy-permissions", token=sup, json={"use_default": True})
    assert r.status_code == 200, r.text
    names = {p["permission_name"] for p in _own_perms(api, sup, sid)}
    assert names == {"Odczyt", "Zakres uprawnień"}


def test_copy_requires_source_or_default(api):
    sup = api.setup_superadmin()
    sid = api.post("/systems/", token=sup, json={"name": "Y", "all_units": True}).json()["id"]
    r = api.post(f"/systems/{sid}/copy-permissions", token=sup, json={})
    assert r.status_code == 400


def test_permission_count_exposed_for_filtering(api):
    """Lista programów zwraca liczbę realnych uprawnień — front filtruje po niej
    programy „bez ustawionych uprawnień"."""
    sup = api.setup_superadmin()
    # 1) nieskonfigurowany
    a = api.post("/systems/", token=sup, json={"name": "Goly", "all_units": True}).json()["id"]
    # 2) z listą uprawnień
    b = api.post("/systems/", token=sup, json={"name": "ZLista", "all_units": True}).json()["id"]
    api.post(f"/systems/{b}/permissions", token=sup, json={"permission_name": "Odczyt"})
    # 3) tylko dostęp — syntetyczne „Dostęp" NIE liczy się jako uprawnienie
    c = api.post("/systems/", token=sup, json={
        "name": "TylkoDostep", "access_only": True, "all_units": True}).json()["id"]

    by_id = {x["id"]: x for x in api.get("/systems/", token=sup).json()}
    assert by_id[a]["permission_count"] == 0 and by_id[a]["access_only"] is False
    assert by_id[b]["permission_count"] == 1
    assert by_id[c]["permission_count"] == 0 and by_id[c]["access_only"] is True


def test_access_only_requires_empty_permission_list(api):
    """„Tylko dostęp" i lista uprawnień wykluczają się — to nadal obowiązuje."""
    sup = api.setup_superadmin()
    sid = api.post("/systems/", token=sup, json={
        "name": "ZLista", "all_units": True}).json()["id"]
    api.post(f"/systems/{sid}/permissions", token=sup, json=SCOPE_PERM)

    r = api.patch(f"/systems/{sid}", token=sup, json={"access_only": True})
    assert r.status_code == 400
