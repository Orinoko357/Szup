"""Decyzje 3.9 — operacje superadmina (konto awaryjne) i neutralizacja CSV.

1. Czyszczenie dziennika zdarzeń / zdarzeń bezpieczeństwa (tylko superadmin,
   hasło + powód, atomowo z triggerami append-only, ślad nieusuwalny).
2. Usunięcie komórki przez superadmina — usunięcie albo archiwizacja.
3. Usunięcie grupy uprawnień, którą ktoś posiada — tylko superadmin.
4. Neutralizacja formuł w eksportach CSV.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine, AUDITLOG_TRIGGERS
from models import (
    AccessRequest, AuditLog, Department, DepartmentDeputy, RequestItem,
    RequestStatus, SecurityEvent, SystemPermission, User, WorkflowInstance,
    WorkflowStep,
)
from tests.conftest import PW

REASON = "Porządki po migracji danych testowych"


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _triggers() -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='auditlog'"))}


def _audit(action: str) -> list[AuditLog]:
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)
                      .order_by(AuditLog.id)).all()


def _events(event_type: str) -> list[SecurityEvent]:
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)
                      .order_by(SecurityEvent.id)).all()


def _add_old_entries(n: int = 3, when: datetime = datetime(2019, 5, 1)) -> None:
    with Session(engine) as s:
        for i in range(n):
            s.add(AuditLog(timestamp=when, action=f"test.old.{i}", username="x"))
            s.add(SecurityEvent(created_at=when, event_type=f"test.old.{i}",
                                summary="stare zdarzenie"))
        s.commit()


def _grant(user_id: int, unit_id: int, dept_id: int, sid: int, pid: int,
           worker_name: str | None = None) -> int:
    """Zrealizowany wniosek o nadanie (bez obiegu) — pracownik POSIADA uprawnienie."""
    now = datetime.utcnow()
    with Session(engine) as s:
        u = s.get(User, user_id)
        req = AccessRequest(worker_name=worker_name or u.full_name or u.username,
                            worker_user_id=user_id, unit_id=unit_id,
                            department_id=dept_id, kind="grant",
                            status=RequestStatus.completed, created_at=now,
                            approved_at=now, completed_at=now)
        s.add(req); s.flush()
        s.add(RequestItem(request_id=req.id, system_id=sid, permission_id=pid,
                          kind="grant", fulfilled=True, fulfilled_at=now))
        s.commit()
        return req.id


def _base(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "Urząd", "U")
    api.mk_user(sup, "adm", ["admin"], "Administrator")
    api.mk_user(sup, "it", ["it_staff"], "Informatyk")
    api.mk_user(sup, "hr", ["hr"], "Kadrowa", unit_ids=[unit])
    return dict(sup=sup, unit=unit, adm=api.login("adm"), it=api.login("it"),
                hr=api.login("hr"))


def _purge(api, token, log="audit", **body):
    # Od 3.10 czyścić można tylko wpisy starsze niż 24 miesiące (bez trybu "all").
    payload = {"password": PW, "reason": REASON, "before": "2020-01-01", **body}
    return api.post(f"/{log}/purge", token=token, json=payload)


# ---------------------------------------------------------------------------
# 1. Czyszczenie dzienników
# ---------------------------------------------------------------------------

def test_purge_superadmin_only_and_validation(api):
    b = _base(api)
    assert _purge(api, b["adm"]).status_code == 403
    assert _purge(api, b["adm"], log="security").status_code == 403
    assert _purge(api, b["it"]).status_code == 403

    r = _purge(api, b["sup"], reason="za krótko")
    assert r.status_code == 400
    r = _purge(api, b["sup"], before="")
    assert r.status_code == 400 and "datę" in r.json()["detail"]
    r = _purge(api, b["sup"], mode="before", before="wczoraj")
    assert r.status_code == 400
    r = _purge(api, b["sup"], mode="sometimes")
    assert r.status_code == 400

    r = _purge(api, b["sup"], password="złe-hasło")
    assert r.status_code == 403
    assert _events("superadmin.confirm_denied")
    # Nic nie zostało usunięte.
    assert not _audit("audit.purged")


def test_purge_password_attempts_limited(api):
    b = _base(api)
    for _ in range(5):
        assert _purge(api, b["sup"], password="złe").status_code == 403
    # Po limicie blokada — także dla poprawnego hasła.
    assert _purge(api, b["sup"]).status_code == 429
    assert any(e.severity == "critical" for e in _events("superadmin.confirm_denied"))


def test_purge_restores_triggers_and_keeps_trace(api):
    b = _base(api)
    _add_old_entries()
    assert set(AUDITLOG_TRIGGERS) <= _triggers()

    r = _purge(api, b["sup"])
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] > 0
    assert set(AUDITLOG_TRIGGERS) <= _triggers()

    traces = _audit("audit.purged")
    assert len(traces) == 1
    details = json.loads(traces[0].details)
    assert details["reason"] == REASON and details["mode"] == "before"
    assert details["deleted"] == r.json()["deleted"]
    assert any(e.severity == "critical" for e in _events("audit.purged"))
    with Session(engine) as s:
        assert not s.exec(select(AuditLog).where(AuditLog.action.like("test.old.%"))).all()

    # Append-only działa dalej — bezpośrednie DELETE jest blokowane.
    with engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("DELETE FROM auditlog"))
            conn.commit()

    # Kolejne czyszczenie nie usuwa śladu poprzedniego.
    r = _purge(api, b["sup"])
    assert r.status_code == 200, r.text
    assert len(_audit("audit.purged")) == 2
    assert set(AUDITLOG_TRIGGERS) <= _triggers()


def test_purge_before_date_deletes_only_older(api):
    b = _base(api)
    _add_old_entries()
    with Session(engine) as s:
        recent = s.exec(select(AuditLog)).all()
        recent_ids = {e.id for e in recent if e.timestamp.year > 2020}
    assert recent_ids

    r = _purge(api, b["sup"], mode="before", before="2020-01-01")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 3
    with Session(engine) as s:
        left = {e.id for e in s.exec(select(AuditLog)).all()}
    assert recent_ids <= left
    details = json.loads(_audit("audit.purged")[0].details)
    # Data bez strefy = północ czasu polskiego (zimą UTC+1), zapis w UTC.
    assert details["mode"] == "before" and details["before"].startswith("2019-12-31T23:00")


def test_security_purge_keeps_trace_events(api):
    b = _base(api)
    _add_old_entries()
    r = _purge(api, b["sup"], log="security")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 3
    with Session(engine) as s:
        assert not s.exec(select(SecurityEvent)
                          .where(SecurityEvent.event_type.like("test.old.%"))).all()
    assert len(_audit("security.purged")) == 1
    first = _events("security.purged")
    assert len(first) == 1 and first[0].severity == "critical"

    # Drugie czyszczenie: ślad pierwszego zostaje.
    r = _purge(api, b["sup"], log="security")
    assert r.status_code == 200, r.text
    assert len(_events("security.purged")) == 2


def test_purge_failure_rolls_back_and_reinstalls_triggers(api, monkeypatch):
    b = _base(api)
    _add_old_entries()
    with Session(engine) as s:
        before_count = len(s.exec(select(AuditLog)).all())

    import services.audit as audit_service
    real = audit_service.table_triggers
    calls = {"n": 0}

    def flaky(conn, table):
        calls["n"] += 1
        if calls["n"] == 2:     # kontrola po odtworzeniu triggerów — w środku transakcji
            raise RuntimeError("awaria dysku")
        return real(conn, table)

    monkeypatch.setattr(audit_service, "table_triggers", flaky)
    r = _purge(api, b["sup"])
    monkeypatch.setattr(audit_service, "table_triggers", real)
    assert r.status_code == 500
    assert set(AUDITLOG_TRIGGERS) <= _triggers()
    with Session(engine) as s:
        assert len(s.exec(select(AuditLog).where(AuditLog.action.like("test.old.%"))).all()) == 3
        assert len(s.exec(select(AuditLog)).all()) >= before_count
    assert not _audit("audit.purged")
    assert _events("audit.purge_failed")


# ---------------------------------------------------------------------------
# 2. Usunięcie komórki przez superadmina
# ---------------------------------------------------------------------------

def _force_delete(api, token, dept_id, **body):
    payload = {"reason": "Likwidacja komórki", "password": PW, **body}
    return api.post(f"/units/departments/{dept_id}/force-delete", token=token, json=payload)


def test_force_delete_requires_superadmin_reason_password(api):
    b = _base(api)
    dep = api.mk_department(b["sup"], b["unit"], None, name="Pusta")
    assert _force_delete(api, b["adm"], dep).status_code == 403
    assert _force_delete(api, b["sup"], dep, reason="  ").status_code == 400
    assert _force_delete(api, b["sup"], dep, password="złe").status_code == 403
    with Session(engine) as s:
        assert s.get(Department, dep) is not None


def test_force_delete_empty_department_hard_deletes_and_reparents(api):
    b = _base(api)
    parent = api.mk_department(b["sup"], b["unit"], None, name="Nadrzędna")
    dep = api.mk_department(b["sup"], b["unit"], None, name="Środkowa",
                            parent_dept_id=parent)
    child = api.mk_department(b["sup"], b["unit"], None, name="Podrzędna",
                              parent_dept_id=dep)

    r = _force_delete(api, b["sup"], dep)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "deleted"
    assert out["reparented_department_ids"] == [child]
    with Session(engine) as s:
        assert s.get(Department, dep) is None
        assert s.get(Department, child).parent_dept_id == parent
    entry = _audit("department.force_deleted")
    assert entry and json.loads(entry[0].details)["reparented_department_ids"] == [child]
    assert any(e.severity == "high" for e in _events("department.force_deleted"))


def test_force_delete_referenced_department_archives(api):
    b = _base(api)
    kid = api.mk_user(b["sup"], "kier", ["manager"], "Kierownik")
    dep_uid = api.mk_user(b["sup"], "zast", ["viewer"], "Zastępca")
    worker = api.mk_user(b["sup"], "prac", ["viewer"], "Pracownik")
    sid, pid = api.mk_system_perm(b["sup"])
    parent = api.mk_department(b["sup"], b["unit"], None, name="Nadrzędna")
    dep = api.mk_department(b["sup"], b["unit"], kid, name="Likwidowana",
                            parent_dept_id=parent)
    child = api.mk_department(b["sup"], b["unit"], None, name="Referat",
                              parent_dept_id=dep)
    r = api.post(f"/units/departments/{dep}/deputies", token=b["sup"],
                 json={"user_id": dep_uid})
    assert r.status_code in (200, 201), r.text
    with Session(engine) as s:
        u = s.get(User, worker); u.department_id = dep; s.add(u); s.commit()
    done = _grant(worker, b["unit"], dep, sid, pid)

    r = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Nowy Pracownik", "unit_id": b["unit"], "department_id": dep,
        "items": [], "request_type_id": api.request_type(b["sup"], "NEW_EMP")})
    assert r.status_code in (200, 201), r.text
    active = r.json()["id"]

    r = _force_delete(api, b["sup"], dep, reason="Reorganizacja urzędu")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "archived"
    assert out["detached_users"] == 1
    assert out["removed_deputies"] == 1
    assert out["reparented_department_ids"] == [child]
    assert out["rejected_request_ids"] == [active]

    sup_id = api.get("/auth/me", token=b["sup"]).json()["id"]
    with Session(engine) as s:
        d = s.get(Department, dep)
        assert d is not None and d.is_active is False
        assert d.archived_at is not None and d.archived_reason == "Reorganizacja urzędu"
        assert d.manager_user_id is None
        assert s.get(User, worker).department_id is None
        assert not s.exec(select(DepartmentDeputy)
                          .where(DepartmentDeputy.department_id == dep)).all()
        assert s.get(Department, child).parent_dept_id == parent
        req = s.get(AccessRequest, active)
        assert req.status == RequestStatus.rejected
        assert s.get(AccessRequest, done).status == RequestStatus.completed
        inst = s.exec(select(WorkflowInstance)
                      .where(WorkflowInstance.request_id == active)).first()
        step = s.exec(select(WorkflowStep).where(WorkflowStep.instance_id == inst.id)
                      .order_by(WorkflowStep.step_index.desc())).first()
        assert step.action == "reject" and step.actor_user_id == sup_id
        assert step.comment == "Komórka usunięta: Reorganizacja urzędu"
        from services.workflow import verify_chain
        assert verify_chain(s, inst.id)

    # Archiwum znika z list i wyborów, nie da się go edytować ani usunąć.
    all_ids = {d["id"] for d in api.get("/units/departments/all", token=b["sup"]).json()}
    active_ids = {d["id"] for d in api.get("/units/departments/active",
                                           token=b["sup"]).json()}
    assert dep not in all_ids and dep not in active_ids and child in all_ids
    assert api.patch(f"/units/departments/{dep}", token=b["sup"],
                     json={"is_active": True}).status_code == 404
    assert api.delete(f"/units/departments/{dep}", token=b["sup"]).status_code == 404
    assert _force_delete(api, b["sup"], dep).status_code == 404

    entry = _audit("department.force_archived")
    assert entry
    details = json.loads(entry[0].details)
    assert details["detached_user_ids"] == [worker]
    assert details["rejected_request_ids"] == [active]
    assert details["reparented_department_ids"] == [child]
    assert any(e.severity == "high" for e in _events("department.force_deleted"))


def test_plain_admin_delete_unchanged(api):
    b = _base(api)
    dep = api.mk_department(b["sup"], b["unit"], None, name="Pusta")
    assert api.delete(f"/units/departments/{dep}", token=b["adm"]).status_code == 204


# ---------------------------------------------------------------------------
# 3. Usunięcie grupy uprawnień
# ---------------------------------------------------------------------------

def _group_setup(api):
    b = _base(api)
    kid = api.mk_user(b["sup"], "kier", ["manager"], "Kierownik")
    dep = api.mk_department(b["sup"], b["unit"], kid, name="Wydział")
    worker = api.mk_user(b["sup"], "prac", ["viewer"], "Jan Pracownik")
    s = api.post("/systems/", token=b["sup"],
                 json={"name": "Księgowość", "access_only": False, "all_units": True})
    sid = s.json()["id"]
    r = api.post(f"/systems/{sid}/permissions/import/commit", token=b["sup"], json={
        "group_name": "G",
        "items": [{"permission_name": "Odczyt"}, {"permission_name": "Zapis"}]})
    assert r.status_code == 200, r.text
    perms = {p["permission_name"]: p["id"]
             for p in api.get(f"/systems/{sid}/permissions", token=b["sup"]).json()
             if p["group_name"] == "G"}
    _grant(worker, b["unit"], dep, sid, perms["Odczyt"])
    r = api.post("/requests/", token=b["hr"], json={
        "worker_name": "Ktoś Nowy", "unit_id": b["unit"], "department_id": dep,
        "request_type_id": api.request_type(b["sup"]),
        "items": [{"system_id": sid, "permission_id": perms["Zapis"], "kind": "grant"}]})
    assert r.status_code in (200, 201), r.text
    return dict(b, dep=dep, worker=worker, sid=sid, perms=perms, in_progress=r.json()["id"])


def test_group_usage_lists_holders_and_requests(api):
    g = _group_setup(api)
    r = api.get(f"/systems/{g['sid']}/permissions/group-usage",
                token=g["it"], params={"group_name": "G"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["holders"] == [{"user_id": g["worker"], "full_name": "Jan Pracownik",
                               "username": "prac", "permissions": ["Odczyt"]}]
    assert out["in_progress_requests"] == [g["in_progress"]]
    assert api.get(f"/systems/{g['sid']}/permissions/group-usage", token=g["it"],
                   params={"group_name": "Brak"}).status_code == 404


def test_held_group_delete_superadmin_only(api):
    g = _group_setup(api)
    url = f"/systems/{g['sid']}/permissions/group-delete"
    r = api.post(url, token=g["it"], json={"group_name": "G", "reason": "x"})
    assert r.status_code == 403
    r = api.post(url, token=g["sup"], json={"group_name": "G"})
    assert r.status_code == 400
    # Nic się nie zmieniło.
    perms = api.get(f"/users/{g['worker']}/permissions", token=g["sup"]).json()["permissions"]
    assert [p["permission_name"] for p in perms] == ["Odczyt"]


def test_held_group_delete_revokes_from_holders(api):
    g = _group_setup(api)
    reason = "Moduł wycofany z użycia"
    r = api.post(f"/systems/{g['sid']}/permissions/group-delete", token=g["sup"],
                 json={"group_name": "G", "reason": reason, "password": PW})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["affected_user_ids"] == [g["worker"]]
    assert len(out["revoke_request_ids"]) == 1
    assert out["updated_request_ids"] == [g["in_progress"]]

    # Uprawnienia efektywne: odebrane.
    eff = api.get(f"/users/{g['worker']}/permissions", token=g["sup"]).json()
    assert eff["permissions"] == []
    assert any(r_["kind"] == "revoke" for r_ in eff["requests"])

    sup_id = api.get("/auth/me", token=g["sup"]).json()["id"]
    with Session(engine) as s:
        rev = s.get(AccessRequest, out["revoke_request_ids"][0])
        assert rev.kind == "revoke" and rev.status == RequestStatus.completed
        assert rev.created_by_id == sup_id and rev.worker_user_id == g["worker"]
        assert reason in (rev.it_comment or "")
        items = s.exec(select(RequestItem).where(RequestItem.request_id == rev.id)).all()
        assert [(i.permission_id, i.kind, i.fulfilled) for i in items] == \
            [(g["perms"]["Odczyt"], "revoke", True)]
        # Wniosek w toku: pozycja odmówiona z notatką.
        it = s.exec(select(RequestItem)
                    .where(RequestItem.request_id == g["in_progress"])
                    .where(RequestItem.permission_id == g["perms"]["Zapis"])).first()
        assert it.denied is True and reason in it.deny_comment
        # Miękkie usunięcie — nazwy zostają w historii.
        for pid in g["perms"].values():
            p = s.get(SystemPermission, pid)
            assert p.deleted_at is not None and p.is_active is False
            assert p.deleted_reason == reason

    left = [p for p in api.get(f"/systems/{g['sid']}/permissions", token=g["sup"]).json()
            if p["group_name"] == "G"]
    assert left == []
    # Grupy nie da się „przywrócić" ani usunąć ponownie.
    assert api.post(f"/systems/{g['sid']}/permissions/group-state", token=g["sup"],
                    json={"group_name": "G", "is_active": True}).status_code == 404

    entry = _audit("permission_group.deleted")
    assert entry
    details = json.loads(entry[0].details)
    assert details["affected_users"][0]["user_id"] == g["worker"]
    assert details["affected_users"][0]["permissions"] == ["Odczyt"]
    assert any(e.severity == "high" for e in _events("permission_group.deleted_held"))


def test_unheld_group_delete_still_allowed_for_it(api):
    b = _base(api)
    s = api.post("/systems/", token=b["sup"],
                 json={"name": "Kadry", "access_only": False, "all_units": True})
    sid = s.json()["id"]
    api.post(f"/systems/{sid}/permissions/import/commit", token=b["sup"], json={
        "group_name": "G", "items": [{"permission_name": "Odczyt"}]})
    usage = api.get(f"/systems/{sid}/permissions/group-usage", token=b["it"],
                    params={"group_name": "G"}).json()
    assert usage == {"holders": [], "unlinked_holders": [], "in_progress_requests": []}
    r = api.post(f"/systems/{sid}/permissions/group-delete", token=b["it"],
                 json={"group_name": "G"})
    assert r.status_code == 200, r.text
    assert r.json()["deactivated"] == 1


# ---------------------------------------------------------------------------
# 4. Neutralizacja formuł w CSV
# ---------------------------------------------------------------------------

def test_csv_exports_neutralize_formulas(api):
    b = _base(api)
    kid = api.mk_user(b["sup"], "kier", ["manager"], "Kierownik")
    dep = api.mk_department(b["sup"], b["unit"], kid, name="Wydział")
    worker = api.mk_user(b["sup"], "prac", ["viewer"], "=HYPERLINK(\"http://x\")")
    sid, pid = api.mk_system_perm(b["sup"], sys_name="+System", perm_name="@Odczyt")
    with Session(engine) as s:
        u = s.get(User, worker); u.department_id = dep; s.add(u); s.commit()
    _grant(worker, b["unit"], dep, sid, pid, worker_name="=SUM(1+1)")
    with Session(engine) as s:
        s.add(AuditLog(action="test.csv", username="-2+3", details="=cmd|' /C calc'!A0"))
        s.commit()

    audit_csv = api.get("/audit/export.csv", token=b["sup"]).text
    assert "'-2+3" in audit_csv and "'=cmd" in audit_csv
    assert ";-2+3;" not in audit_csv

    reg = api.get("/registry/granted.csv", token=b["sup"]).text
    assert "'=SUM(1+1)" in reg and "'+System" in reg and "'@Odczyt" in reg

    from services.snapshots import create_snapshot
    with Session(engine) as s:
        create_snapshot(s, generated_by="test", for_date="2026-01-02")
    snap = api.get("/snapshots/2026-01-02.csv", token=b["sup"]).text
    assert "'=HYPERLINK" in snap and "'+System" in snap and "'@Odczyt" in snap


def test_csv_safe_helper():
    from services.csv_utils import csv_safe
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("  @x") == "'  @x"
    assert csv_safe("\tx") == "'\tx"
    assert csv_safe("Jan Kowalski") == "Jan Kowalski"
    assert csv_safe(5) == 5


# ---------------------------------------------------------------------------
# Superadmin nie pełni funkcji w strukturze; komórki widoczne dla wszystkich
# ---------------------------------------------------------------------------

def test_superadmin_cannot_hold_structure_posts(api):
    b = _base(api)
    sup_id = api.get("/auth/me", token=b["sup"]).json()["id"]
    msg = "Superadmin to konto awaryjne"
    r = api.post("/units/departments", token=b["sup"], json={
        "unit_id": b["unit"], "name": "X", "kind": "department",
        "manager_user_id": sup_id})
    assert r.status_code == 400 and msg in r.json()["detail"]
    dep = api.mk_department(b["sup"], b["unit"], None, name="Y")
    r = api.patch(f"/units/departments/{dep}", token=b["sup"],
                  json={"manager_user_id": sup_id})
    assert r.status_code == 400 and msg in r.json()["detail"]
    r = api.patch(f"/units/{b['unit']}", token=b["sup"], json={"manager_user_id": sup_id})
    assert r.status_code == 400 and msg in r.json()["detail"]
    r = api.post(f"/units/departments/{dep}/deputies", token=b["sup"],
                 json={"user_id": sup_id})
    assert r.status_code == 400 and msg in r.json()["detail"]

    # Auto-przypisanie kierowników pomija superadmina.
    with Session(engine) as s:
        u = s.get(User, sup_id); u.department_id = dep; u.title = "Kierownik"
        s.add(u); s.commit()
    r = api.post("/units/departments/auto-managers", token=b["sup"], json={})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(Department, dep).manager_user_id is None


def test_active_units_and_departments_not_scoped(api):
    b = _base(api)
    other = api.mk_unit(b["sup"], "Inny urząd", "I")
    dep = api.mk_department(b["sup"], other, None, name="Obca komórka")
    units = {u["id"] for u in api.get("/units/active", token=b["hr"]).json()}
    assert {b["unit"], other} <= units
    depts = {d["id"] for d in api.get("/units/departments/active", token=b["hr"]).json()}
    assert dep in depts
