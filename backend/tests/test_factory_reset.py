"""Reset fabryczny na prawdziwych danych (wnioski z historią roboczą i przejęciem,
struktura, użytkownicy, rejestr) — po resecie nie może zostać nic poza kontem
wykonującego i danymi z seedu; każdy błąd przerywa reset bez zmian (fail-closed)."""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from database import engine
from tests.conftest import PW
from tests.test_logic_fixes import _world, _new_request


def _count(table):
    with Session(engine) as s:
        return s.exec(text(f'SELECT COUNT(*) FROM "{table}"')).one()[0]


def _populate(api):
    """Wniosek: wersja robocza kierownika, przejęcie przez przełożonego,
    wysyłka (z automatyczną akceptacją wyższą) i realizacja — powstają kroki, zdarzenia i deklaracje."""
    w = _world(api, two_stage=True)
    rid = _new_request(api, w)
    kier, kierP, it = api.login("kier"), api.login("kierP"), api.login("it")
    item = {"system_id": w["sid"], "permission_id": w["pid"]}
    assert api.post(f"/requests/{rid}/draft", token=kier,
                    json={"items": [item], "comment": "roboczo"}).status_code == 200
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    # Przełożony po przejęciu — akceptacja wyższa zaliczona automatycznie.
    assert api.post(f"/requests/{rid}/workflow/action", token=kierP,
                    json={"action": "select", "items": [item]}).status_code == 200
    r = api.post(f"/requests/{rid}/workflow/action", token=it,
                 json={"action": "execute", "ad_username": "olanowa"})
    assert r.status_code == 200, r.text
    assert _count("requestevent") >= 2
    return w


def _full_body(**kw):
    return {"password": PW, "confirm": "RESET", "wipe_requests": True,
            "wipe_structure": True, "wipe_users": True, "wipe_software": True,
            "wipe_audit": True, **kw}


def test_full_reset_wipes_everything(api):
    w = _populate(api)
    r = api.post("/settings/factory-reset", token=w["sup"], json=_full_body())
    assert r.status_code == 200, r.text
    for t in ("accessrequest", "requestitem", "requestevent", "workflowstep",
              "workflowinstance", "permissiondeclaration", "department", "unit",
              "departmentdeputy", "userunit", "permissionsystem", "systempermission",
              "permissionsystemunit"):
        assert _count(t) == 0, t
    assert _count("user") == 1          # tylko wykonujący
    # Żadnych ostrzeżeń — także o ochronie append-only dziennika (bez maskowania).
    assert not any(d.startswith("⚠") for d in r.json()["details"]), r.json()["details"]
    # Retencja 24 mies. (3.11): świeże wpisy dziennika zostają.
    assert _count("auditlog") > 1


def test_requests_only_reset_keeps_structure_and_users(api):
    w = _populate(api)
    users, depts = _count("user"), _count("department")
    r = api.post("/settings/factory-reset", token=w["sup"],
                 json=_full_body(wipe_structure=False, wipe_users=False,
                                 wipe_software=False, wipe_audit=False))
    assert r.status_code == 200, r.text
    assert _count("accessrequest") == 0 and _count("requestevent") == 0
    assert _count("user") == users and _count("department") == depts


def test_scope_dependencies_rejected_before_any_change(api):
    w = _populate(api)
    before = _count("workflowstep")
    for body in (_full_body(wipe_requests=False),
                 _full_body(wipe_requests=False, wipe_users=False, wipe_software=False),
                 _full_body(wipe_requests=False, wipe_structure=False, wipe_users=False)):
        assert api.post("/settings/factory-reset", token=w["sup"], json=body).status_code == 400
    assert _count("workflowstep") == before


def test_failed_table_aborts_whole_reset(api, monkeypatch):
    """Błąd na dowolnej tabeli → 500 i brak jakichkolwiek zmian."""
    w = _populate(api)
    before = {t: _count(t) for t in ("workflowstep", "accessrequest", "user", "department")}
    # Trigger blokujący DELETE na jednostkach symuluje nieznany klucz obcy.
    with Session(engine) as s:
        s.exec(text("CREATE TRIGGER t_block BEFORE DELETE ON unit "
                    "BEGIN SELECT RAISE(ABORT, 'zablokowane'); END"))
        s.commit()
    r = api.post("/settings/factory-reset", token=w["sup"], json=_full_body())
    assert r.status_code == 500 and "unit" in r.text
    assert {t: _count(t) for t in before} == before
    with Session(engine) as s:
        names = {row[0] for row in s.exec(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='auditlog'"))}
    assert {"auditlog_no_update", "auditlog_no_delete"} <= names


def test_reset_data_tool_wipes_children_and_keeps_users(api, monkeypatch):
    """tools/reset_data.py: usuwa wnioski razem z obiegiem i historią (bez
    osieroconych rekordów), zostawia użytkowników."""
    import sys
    from tools import reset_data
    _populate(api)
    users = _count("user")
    monkeypatch.setattr(sys, "argv", ["reset_data", "--yes"])
    reset_data.main()
    for t in ("accessrequest", "requestevent", "workflowstep", "workflowinstance",
              "permissiondeclaration", "requestitem", "department", "unit"):
        assert _count(t) == 0, t
    assert _count("user") == users
