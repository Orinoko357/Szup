"""E2E: IT dokłada uprawnienia na etapie realizacji (z uzasadnieniem)."""
from __future__ import annotations

# Uprawnienie, które IT dokłada — z wymaganą kontrolką opisową.
EXTRA_PERM = {"permission_name": "Zakres uprawnień", "input_type": "textarea",
              "input_required": True, "description": "Moduły lub rejestry"}


def _world(api, extra_perm=None):
    """Wniosek doprowadzony do kroku realizacji IT, z jedną pozycją kierownika."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    api.mk_user(sup, "it", ["it_staff"], "Iga IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")

    # system zatwierdzony przez kierownika (prosta lista uprawnień)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    # system, który IT dołoży — z uprawnieniem wymagającym uzupełnienia
    r2 = api.post("/systems/", token=sup, json={"name": "Zalezny", "all_units": True})
    sid2 = r2.json()["id"]
    pid2 = api.post(f"/systems/{sid2}/permissions", token=sup,
                    json=extra_perm if extra_perm is not None else EXTRA_PERM
                    ).json()["id"]

    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Agata Młot", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    # kierownik wybiera swoją pozycję → wniosek trafia do IT
    api.post(f"/requests/{rid}/workflow/action", token=api.login("kier"), json={
        "action": "select",
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}]})

    return dict(sup=sup, rid=rid, it=api.login("it"),
                sid=sid, pid=pid, sid2=sid2, pid2=pid2)


def test_it_adds_permission_with_justification(api):
    """Główny scenariusz: IT dokłada pozycję, uzasadnia, wniosek się realizuje."""
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot",
        "comment": "Moduł FK wymaga dostępu do systemu zależnego.",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"],
                         "kind": "grant",
                         "custom_values": {"Zakres uprawnień": "Rejestr VAT"}}]})
    assert r.status_code == 200, r.text

    det = api.get(f"/requests/{w['rid']}", token=w["sup"]).json()
    assert det["status"] == "completed"
    by_perm = {i["permission_id"]: i for i in det["items"]}
    assert len(by_perm) == 2, "powinny być 2 pozycje: kierownika + IT"

    # pozycja kierownika bez proweniencji, pozycja IT z podpisem autora
    assert by_perm[w["pid"]]["added_by_name"] is None
    it_item = by_perm[w["pid2"]]
    assert it_item["added_by_name"] == "Iga IT"
    assert it_item["custom_values"]["Zakres uprawnień"] == "Rejestr VAT"

    # dodane uprawnienie trafia do efektywnych uprawnień pracownika
    worker = det["worker_user_id"]
    eff = api.get(f"/users/{worker}/permissions", token=w["sup"]).json()
    assert {p["permission_id"] for p in eff["permissions"]} == {w["pid"], w["pid2"]}


def test_added_permission_requires_justification(api):
    """Bez uzasadnienia nie da się dołożyć uprawnień."""
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot", "comment": "   ",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"],
                         "kind": "grant",
                         "custom_values": {"Zakres uprawnień": "X"}}]})
    assert r.status_code == 400 and "uzasadnieni" in r.text.lower()


def test_added_permission_enforces_required_fields(api):
    """Pola obowiązkowe działają tak samo jak u kierownika."""
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot", "comment": "Powód",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"],
                         "kind": "grant"}]})
    assert r.status_code == 400 and "Zakres uprawnień" in r.text


def test_cannot_add_duplicate_of_existing_item(api):
    """Pozycja już obecna we wniosku nie może zostać zdublowana."""
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot", "comment": "Powód",
        "added_items": [{"system_id": w["sid"], "permission_id": w["pid"],
                         "kind": "grant"}]})
    assert r.status_code == 400 and "już na wniosku" in r.text


def test_plain_execute_without_additions_still_works(api):
    """Regresja: realizacja bez dodatków — komentarz nadal opcjonalny."""
    w = _world(api)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot"})
    assert r.status_code == 200, r.text
    det = api.get(f"/requests/{w['rid']}", token=w["sup"]).json()
    assert det["status"] == "completed" and len(det["items"]) == 1


def test_audit_trail_records_additions_and_chain_stays_valid(api):
    """Dodatki i uzasadnienie trafiają do podpisanego kroku obiegu."""
    w = _world(api)
    api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot",
        "comment": "Zależność modułu FK.",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"],
                         "kind": "grant",
                         "custom_values": {"Zakres uprawnień": "Rejestr VAT"}}]})

    wf = api.get(f"/requests/{w['rid']}/workflow", token=w["sup"]).json()
    step = [s for s in wf["steps"] if s["action"] == "execute"][0]
    assert "Zależność modułu FK." in (step["comment"] or "")
    assert "added_items" in (step["payload"] or "")
    assert "Rejestr VAT" in (step["payload"] or "")

    # łańcuch podpisów nadal spójny
    v = api.get(f"/requests/{w['rid']}/workflow/verify", token=w["sup"]).json()
    assert v.get("chain_valid") is True, v


def test_failed_validation_does_not_create_ghost_worker(api):
    """Błąd walidacji nie może zostawić utworzonego konta-widma."""
    w = _world(api)
    before = len(api.get("/users/", token=w["sup"]).json())
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "nowy.duch", "comment": "Powód",
        "added_items": [{"system_id": w["sid2"], "permission_id": w["pid2"],
                         "kind": "grant"}]})   # brak pola obowiązkowego → 400
    assert r.status_code == 400
    after = len(api.get("/users/", token=w["sup"]).json())
    assert after == before, "konto pracownika nie powinno powstać przy błędzie"


def test_stale_node_id_blocks_execute(api):
    """Optymistyczna kontrola współbieżności działa też na kroku IT."""
    w = _world(api)
    # lista wniosków podaje current_node_id — front odsyła je jako expected_node_id
    lst = api.get("/requests/", token=w["it"], params={"status": "pending_it"}).json()
    row = [x for x in lst if x["id"] == w["rid"]][0]
    assert row["current_node_id"], "lista musi podawać current_node_id"

    # pierwsza realizacja przechodzi
    ok = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "ad_username": "amlot",
        "expected_node_id": row["current_node_id"]})
    assert ok.status_code == 200, ok.text

    # druga, z tym samym (już nieaktualnym) węzłem → 409
    again = api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"], json={
        "action": "execute", "expected_node_id": row["current_node_id"]})
    assert again.status_code == 409, again.text
