"""E2E: oświadczenie wnioskującego + rejestr nadanych uprawnień.

Oświadczenie jest wymagane w chwili, gdy akcja kieruje wniosek do realizacji
IT (`it_execute`) i wniosek NADAJE uprawnienia:
  - wydział 1-stopniowy → `select` kierownika (higher pomijany),
  - wydział 2-stopniowy → `approve` kierownika II stopnia.
Czyste odebranie/ustanie — bez oświadczenia. Brak oświadczenia → 428.

W tych testach pomijamy auto-wstrzykiwanie z conftest (Api.post), podając klucz
`declaration` jawnie — także `None`, gdy sprawdzamy bramkę 428.
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

from database import engine
from models import PermissionDeclaration

CODE_RE = re.compile(r"^[A-Za-z0-9]+-\d{8}-\d{6}-[A-Z2-9]{8}$")
DECL = {"declared_by_name": "Jan Kowalski", "declared_date": "2026-07-23"}


def _base(api, two_stage=False):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="W",
                            requires_higher_approval=two_stage)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, kid=kid, dep=dep, sid=sid, pid=pid,
                hr=api.login("hr"), kier=api.login("kier"), it=api.login("it"))


def _new_request(api, b, kind="grant"):
    return api.post("/requests/", token=b["hr"], json={
        "worker_name": "Pracownik", "unit_id": b["unit"], "department_id": b["dep"],
        "items": [], "kind": kind,
        "request_type_id": api.request_type(b["sup"], "NEW_EMP"),
    }).json()["id"]


def _decl_rows():
    with Session(engine) as s:
        return s.exec(select(PermissionDeclaration)).all()


def test_single_stage_select_requires_declaration(api):
    b = _base(api)
    rid = _new_request(api, b)
    items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]

    # bez oświadczenia → 428 z treścią
    r = api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
                 json={"action": "select", "items": items, "declaration": None})
    assert r.status_code == 428
    det = r.json()["detail"]
    assert det["code"] == "DECLARATION_REQUIRED"
    assert "oświadcz" in det["declaration_text"].lower()

    # z oświadczeniem → 200, wniosek w IT, zapis oświadczenia
    r = api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
                 json={"action": "select", "items": items, "declaration": DECL})
    assert r.status_code == 200, r.text
    assert api.get(f"/requests/{rid}", token=b["sup"]).json()["status"] == "pending_it"

    rows = _decl_rows()
    assert len(rows) == 1
    d = rows[0]
    assert d.request_id == rid
    assert d.declared_by_name == "Jan Kowalski"
    assert d.declared_by_login == "kier"
    assert CODE_RE.match(d.reference_code), d.reference_code
    # treść zamrożona = aktualny szablon
    assert "OŚWIADCZENIE WNIOSKUJĄCEGO" in d.declaration_text


def test_two_stage_declaration_at_higher_manager(api):
    """W 2-stopniu select I stopnia NIE wymaga oświadczenia (ląduje na higher),
    a approve II stopnia — wymaga (ląduje na it_execute)."""
    b = _base(api)
    boss = api.mk_user(b["sup"], "boss", ["manager"], "Boss")
    bt = api.login("boss")
    parent = api.mk_department(b["sup"], b["unit"], boss,
                               requires_higher_approval=False, name="Nadrzędny")
    child = api.mk_department(b["sup"], b["unit"], b["kid"],
                              requires_higher_approval=True, name="Referat",
                              parent_dept_id=parent)
    rid = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Pracownik", "unit_id": b["unit"], "department_id": child,
        "items": [], "request_type_id": api.request_type(b["sup"], "NEW_EMP"),
    }).json()["id"]
    items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]

    # select I stopnia — bez oświadczenia, przechodzi (ląduje na higher_manager_approve)
    r = api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
                 json={"action": "select", "items": items, "declaration": None})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, bt) == "higher_manager_approve"
    assert _decl_rows() == []

    # approve kier. nadrzędnego — bez oświadczenia → 428
    r = api.post(f"/requests/{rid}/workflow/action", token=bt,
                 json={"action": "approve", "declaration": None})
    assert r.status_code == 428

    # z oświadczeniem → 200 i wniosek w IT
    r = api.post(f"/requests/{rid}/workflow/action", token=bt,
                 json={"action": "approve", "declaration": DECL})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, b["it"]) == "it_execute"
    rows = _decl_rows()
    assert len(rows) == 1 and rows[0].declared_by_login == "boss"


def test_pure_revoke_needs_no_declaration(api):
    """Odebranie/ustanie nie nadaje niczego → brak oświadczenia."""
    b = _base(api)
    items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]

    # 1) najpierw nadaj (tworzy pracownika) — z oświadczeniem
    rid = _new_request(api, b)
    api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
             json={"action": "select", "items": items, "declaration": DECL})
    api.post(f"/requests/{rid}/workflow/action", token=b["it"],
             json={"action": "execute", "ad_username": "prac"})
    worker = api.get(f"/requests/{rid}", token=b["sup"]).json()["worker_user_id"]
    assert worker
    before = len(_decl_rows())

    # 2) teraz odbierz — bez oświadczenia, bo nic nie nadaje
    rid2 = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Pracownik", "worker_user_id": worker,
        "unit_id": b["unit"], "department_id": b["dep"], "items": [], "kind": "revoke",
        "request_type_id": api.request_type(b["sup"], "REVOKE"),
    }).json()["id"]
    r = api.post(f"/requests/{rid2}/workflow/action", token=b["kier"],
                 json={"action": "select",
                       "items": [{"system_id": b["sid"], "permission_id": b["pid"],
                                  "kind": "revoke"}],
                       "declaration": None})
    assert r.status_code == 200, r.text
    assert len(_decl_rows()) == before   # nic nowego


def test_autoselect_on_create_requires_declaration(api):
    """Kierownik składa wniosek z pozycjami (auto-select) w 1-stopniu →
    ląduje wprost na IT → oświadczenie wymagane."""
    b = _base(api)
    body = {
        "worker_name": "Nowy", "unit_id": b["unit"], "department_id": b["dep"],
        "items": [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}],
        "request_type_id": api.request_type(b["sup"], "NEW_EMP"),
    }
    r = api.post("/requests/", token=b["kier"], json={**body, "declaration": None})
    assert r.status_code == 428

    r = api.post("/requests/", token=b["kier"], json={**body, "declaration": DECL})
    assert r.status_code in (200, 201), r.text
    assert len(_decl_rows()) == 1


def test_reference_codes_are_unique(api):
    b = _base(api)
    codes = set()
    for _ in range(3):
        rid = _new_request(api, b)
        items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]
        api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
                 json={"action": "select", "items": items, "declaration": DECL})
    for d in _decl_rows():
        codes.add(d.reference_code)
    assert len(codes) == 3


def test_declaration_text_edit_is_not_retroactive(api):
    b = _base(api)
    rid = _new_request(api, b)
    items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]
    api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
             json={"action": "select", "items": items, "declaration": DECL})
    old_text = _decl_rows()[0].declaration_text

    # zmiana szablonu w ustawieniach
    r = api.put("/settings/app", token=b["sup"],
                json={"test_mode": False, "declaration_text": "ZUPEŁNIE NOWA TREŚĆ"})
    assert r.status_code == 200
    assert api.get("/settings/app", token=b["sup"]).json()["declaration_text"] == "ZUPEŁNIE NOWA TREŚĆ"

    # już zapisane oświadczenie ma STARĄ treść
    assert _decl_rows()[0].declaration_text == old_text
    assert "ZUPEŁNIE NOWA" not in old_text


def test_registry_lists_grant_with_declaration(api):
    b = _base(api)
    rid = _new_request(api, b)
    items = [{"system_id": b["sid"], "permission_id": b["pid"], "kind": "grant"}]
    api.post(f"/requests/{rid}/workflow/action", token=b["kier"],
             json={"action": "select", "items": items, "declaration": DECL})
    # rejestr pokazuje tylko pozycje zrealizowane — IT wykonuje wniosek
    r = api.post(f"/requests/{rid}/workflow/action", token=b["it"],
                 json={"action": "execute", "ad_username": "nowy"})
    assert r.status_code == 200, r.text

    reg = api.get("/registry/granted", token=b["it"]).json()
    assert reg["total"] >= 1
    row = next(x for x in reg["items"] if x["request_id"] == rid)
    assert row["permission_name"] == "Odczyt"
    assert row["declared_by_name"] == "Jan Kowalski"
    assert CODE_RE.match(row["reference_code"])

    csv = api.get("/registry/granted.csv", token=b["it"])
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["content-type"]
    assert "Jan Kowalski" in csv.text


def test_registry_requires_it_staff(api):
    b = _base(api)
    r = api.get("/registry/granted", token=b["kier"])
    assert r.status_code == 403
