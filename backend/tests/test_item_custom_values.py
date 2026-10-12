"""E2E: uprawnienia z kontrolką (lista wyboru / pole do wpisania).

Kontrolka jest cechą POJEDYNCZEGO uprawnienia, nie całego oprogramowania —
obok pozycji z importu (zwykłe checkboxy) stoją pozycje dodane ręcznie przez
IT, które doprecyzowuje się listą albo tekstem.
"""
from __future__ import annotations


def _world(api, perm):
    """Świat testowy: program + JEDNO uprawnienie o zadanej kontrolce."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid = api.post("/systems/", token=sup, json={
        "name": "FK", "access_only": False, "all_units": True}).json()["id"]
    r = api.post(f"/systems/{sid}/permissions", token=sup, json=perm)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    rtype = api.request_type(sup, "NEW_EMP")
    hr, kier, it = api.login("hr"), api.login("kier"), api.login("it")
    rid = api.post("/requests/", token=hr, json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    return dict(sup=sup, rid=rid, kier=kier, it=it, sid=sid, pid=pid)


SCOPE_PERM = {"permission_name": "Zakres uprawnień", "input_type": "textarea",
              "input_required": True, "description": "Rejestry lub moduły"}


def test_required_input_blocks_selection(api):
    w = _world(api, SCOPE_PERM)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 400
    assert "Zakres uprawnień" in r.text


def test_filled_value_is_saved_and_visible(api):
    w = _world(api, SCOPE_PERM)
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Zakres uprawnień": "Rejestr VAT, moduł KP"}}]})
    assert r.status_code == 200, r.text
    det = api.get(f"/requests/{w['rid']}", token=w["it"]).json()
    item = det["items"][0]
    assert item["custom_values"]["Zakres uprawnień"] == "Rejestr VAT, moduł KP"
    # definicja kontrolki też wraca — front renderuje z niej formularz
    assert item["input"]["type"] == "textarea"
    assert item["input"]["required"] is True


def test_plain_permission_has_no_input(api):
    """Pozycja bez kontrolki (np. z importu) to zwykły checkbox."""
    w = _world(api, {"permission_name": "001 - MiPBP"})
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200, r.text
    item = api.get(f"/requests/{w['rid']}", token=w["it"]).json()["items"][0]
    assert item["input"]["type"] == "none"
    assert item["custom_values"] == {}


def test_select_rejects_value_outside_options(api):
    w = _world(api, {"permission_name": "Poziom", "input_type": "select",
                     "input_required": True, "options": ["Odczyt", "Zapis"]})
    bad = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Poziom": "Admin"}}]})
    assert bad.status_code == 400 and "Poziom" in bad.text

    ok = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Poziom": "Odczyt"}}]})
    assert ok.status_code == 200, ok.text


def test_radio_behaves_like_select(api):
    """Radio i lista rozwijana różnią się tylko prezentacją."""
    w = _world(api, {"permission_name": "Poziom", "input_type": "radio",
                     "input_required": True, "options": ["Odczyt", "Zapis"]})
    bad = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Poziom": "Admin"}}]})
    assert bad.status_code == 400


def test_optional_input_can_be_empty(api):
    w = _world(api, {"permission_name": "Uwagi", "input_type": "text"})
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200, r.text


def test_options_required_for_choice_types(api):
    """Lista wyboru bez opcji jest nie do wypełnienia — odrzucamy od razu."""
    sup = api.setup_superadmin()
    sid = api.post("/systems/", token=sup,
                   json={"name": "X", "all_units": True}).json()["id"]
    r = api.post(f"/systems/{sid}/permissions", token=sup,
                 json={"permission_name": "Poziom", "input_type": "select"})
    assert r.status_code == 400


def _complete_grant(api, w, values):
    """Zrealizuj wniosek do końca, tworząc pracownika z uprawnieniem."""
    api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": values}]})
    api.post(f"/requests/{w['rid']}/workflow/action", token=w["it"],
             json={"action": "execute", "ad_username": "pworker"})
    det = api.get(f"/requests/{w['rid']}", token=w["sup"]).json()
    return det["worker_user_id"]


def test_change_request_new_permission_requires_value(api):
    """Zmiana uprawnień: nadanie NOWEJ pozycji obecnemu pracownikowi
    też wymaga wypełnienia jej kontrolki."""
    w = _world(api, SCOPE_PERM)
    worker = _complete_grant(api, w, {"Zakres uprawnień": "Rejestr VAT"})
    assert worker

    # drugie uprawnienie w tym samym programie — też z wymaganą kontrolką
    p2 = api.post(f"/systems/{w['sid']}/permissions", token=w["sup"], json={
        "permission_name": "Moduły", "input_type": "multiselect",
        "input_required": True, "options": ["KP", "KW", "VAT"]}).json()["id"]

    unit = api.get("/units/", token=w["sup"]).json()[0]["id"]
    dep = api.get("/units/departments/all", token=w["sup"]).json()[0]["id"]
    rtype = api.request_type(w["sup"], "MODIFY")
    rid2 = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep, "items": [],
        "request_type_id": rtype, "kind": "change", "worker_user_id": worker,
    }).json()["id"]

    bad = api.post(f"/requests/{rid2}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": p2, "kind": "grant"}]})
    assert bad.status_code == 400 and "Moduły" in bad.text

    ok = api.post(f"/requests/{rid2}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": p2, "kind": "grant",
                   "custom_values": {"Moduły": "KP, VAT"}}]})
    assert ok.status_code == 200, ok.text
    det = api.get(f"/requests/{rid2}", token=w["it"]).json()
    got = {i["permission_id"]: i["custom_values"] for i in det["items"]}
    assert got[p2]["Moduły"] == "KP, VAT"


def test_scope_of_held_permission_can_be_updated(api):
    """Zmiana SAMEJ wartości już posiadanego uprawnienia (bez odbierania)."""
    w = _world(api, SCOPE_PERM)
    worker = _complete_grant(api, w, {"Zakres uprawnień": "Rejestr VAT"})

    eff = api.get(f"/users/{worker}/permissions", token=w["sup"]).json()
    assert eff["permissions"][0]["custom_values"]["Zakres uprawnień"] == "Rejestr VAT"

    unit = api.get("/units/", token=w["sup"]).json()[0]["id"]
    dep = api.get("/units/departments/all", token=w["sup"]).json()[0]["id"]
    rtype = api.request_type(w["sup"], "MODIFY")
    rid2 = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep, "items": [],
        "request_type_id": rtype, "kind": "change", "worker_user_id": worker,
    }).json()["id"]

    api.post(f"/requests/{rid2}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant",
                   "custom_values": {"Zakres uprawnień": "Rejestr VAT, moduł KP"}}]})
    api.post(f"/requests/{rid2}/workflow/action", token=w["it"],
             json={"action": "execute"})

    eff2 = api.get(f"/users/{worker}/permissions", token=w["sup"]).json()
    perms = eff2["permissions"]
    assert len(perms) == 1, "uprawnienie nie powinno się zdublować"
    assert perms[0]["custom_values"]["Zakres uprawnień"] == "Rejestr VAT, moduł KP"
