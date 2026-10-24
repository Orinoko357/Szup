"""3.11 — poprawki bezpieczeństwa i administracji po audycie 3.10 (agent B).

1. Niewykonane odebrania przy operacjach superadmina trafiają do kolejki IT
   (likwidacja komórki, usunięcie posiadanej grupy); wnioski w toku bez
   pozostałych pozycji — odrzucenie systemowe.
2. Reset fabryczny i tools/reset_data.py — retencja 24 mies., triggery, ślad.
3. Wspólny budżet prób hasła: atomowość (wyścig), blokada per (konto, IP),
   potwierdzenia hasłem liczą się do blokady logowania; zamykanie zdarzeń.
4. Superadmin poza komórkami; funkcja kadr tylko z aktywnej komórki kadrowej;
   import z AD nie przypisuje do komórki nieaktywnej.
5. Zdarzenie hr_flag_changed — beneficjent go nie zamknie.
6. OverflowError → 400, limity długości nazw, znaki niewidoczne / bidi.
7. Wylogowanie po bezczynności po stronie serwera, PyJWT.
8. Polskie teksty zdarzeń, drobne testy pokrycia (entry_guid, db_int_ok).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine
from main import app
from models import (
    AccessRequest, AuditLog, Department, PasswordConfirmFailure, RequestItem,
    RequestStatus, RequestType, SecurityEvent, SecuritySeverity, SessionActivity, User,
    WorkflowInstance,
)
from tests.conftest import PW
from tests.test_310_structure import (
    _capture_jobs, _force_delete, _grant, _group_delete, _group_world, _hr_request,
    _it_execute, _world,
)

BIG = 2 ** 63


def _events(event_type: str) -> list[SecurityEvent]:
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)
                      .order_by(SecurityEvent.id)).all()


def _uid(username: str) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == username)).one().id


def _set(model, obj_id, **fields):
    with Session(engine) as s:
        obj = s.get(model, obj_id)
        for k, v in fields.items():
            setattr(obj, k, v)
        s.add(obj); s.commit()


def _eff(api, token, uid) -> list[str]:
    return sorted(p["permission_name"] for p in api.get(
        f"/users/{uid}/permissions", token=token).json()["permissions"])


# ---------------------------------------------------------------------------
# 1. Odebrania do kolejki IT
# ---------------------------------------------------------------------------

def _it_request_with_revoke(w, *, with_instance: bool) -> tuple[int, int, int]:
    """Wniosek „zmiana” w realizacji IT: odebranie posiadanego Odczytu i nadanie
    Zapisu (nic jeszcze nie odhaczone). Zwraca (wniosek, pozycja odebrania,
    pozycja nadania)."""
    from routers.systems import start_system_revoke
    with Session(engine) as s:
        rt = s.exec(select(RequestType).where(RequestType.code == "MODIFY")).one()
        req = AccessRequest(worker_name="Piotr Pracownik", worker_user_id=w["worker"],
                            unit_id=w["unit"], department_id=w["dep"], kind="change",
                            request_type_id=rt.id, status=RequestStatus.pending_it,
                            current_node_type="it_execute")
        s.add(req); s.flush()
        rev = RequestItem(request_id=req.id, system_id=w["sid"], permission_id=w["pid"],
                          kind="revoke")
        gr = RequestItem(request_id=req.id, system_id=w["sid"], permission_id=w["pid2"],
                         kind="grant")
        s.add(rev); s.add(gr); s.flush()
        if with_instance:
            start_system_revoke(s, req)
        s.commit()
        return req.id, rev.id, gr.id


@pytest.mark.parametrize("with_instance", [True, False])
def test_force_delete_forwards_unexecuted_revocations_to_it(api, monkeypatch, with_instance):
    w = _world(api)
    _grant(w["unit"], w["dep"], w["sid"], w["pid"], user_id=w["worker"])
    rid, rev_item, grant_item = _it_request_with_revoke(w, with_instance=with_instance)
    jobs = _capture_jobs(monkeypatch)

    r = _force_delete(api, w["sup"], w["dep"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["it_pending_request_ids"] == [rid]
    assert rid not in out["completed_request_ids"] and rid not in out["rejected_request_ids"]
    assert out["detached_users"] == [{"id": w["worker"], "full_name": "Piotr Pracownik",
                                      "login": "prac"}]
    with Session(engine) as s:
        req = s.get(AccessRequest, rid)
        assert req.status == RequestStatus.pending_it
        rev = s.get(RequestItem, rev_item)
        assert not rev.fulfilled and not rev.denied          # NIE „zrealizowane”
        gr = s.get(RequestItem, grant_item)
        assert gr.denied and "Reorganizacja" in gr.deny_comment
        assert s.exec(select(WorkflowInstance).where(WorkflowInstance.request_id == rid)
                      ).one().current_node_id is not None
    # IT i helpdesk dostają zadanie.
    assert any(n == "notify_helpdesk_new_request" and kw["request_id"] == rid
               for n, kw in jobs)
    # Uprawnienie efektywne zostaje do realizacji przez IT…
    assert _eff(api, w["sup"], w["worker"]) == ["Odczyt"]
    details = json.loads(_audit_details("department.force_archived"))
    assert details["it_pending_request_ids"] == [rid]
    # …a znika po niej.
    _it_execute(api, rid)
    assert _eff(api, w["sup"], w["worker"]) == []


def _audit_details(action: str) -> str:
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)
                      .order_by(AuditLog.id.desc())).first().details


def test_group_delete_rejects_requests_left_without_items(api, monkeypatch):
    g = _group_world(api)
    _grant(g["unit"], g["dep"], g["gsid"], g["gp"]["Listy płac"], user_id=g["worker"])
    only_group = _hr_request(api, g, items=[{"system_id": g["gsid"],
                                             "permission_id": g["gp"]["Kartoteki"]}],
                             worker_name="Ola Grupowa")
    mixed = _hr_request(api, g, items=[{"system_id": g["gsid"],
                                        "permission_id": g["gp"]["Kartoteki"]},
                                       {"system_id": g["sid"], "permission_id": g["pid"]}],
                        worker_name="Ola Mieszana")
    r = _group_delete(api, g)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["rejected_request_ids"] == [only_group]
    assert sorted(out["updated_request_ids"]) == sorted([only_group, mixed])
    rev_ids = out["revoke_request_ids"]
    assert len(rev_ids) == 1
    with Session(engine) as s:
        assert s.get(AccessRequest, only_group).status == RequestStatus.rejected
        assert s.get(AccessRequest, mixed).status != RequestStatus.rejected
        rev = s.get(AccessRequest, rev_ids[0])
        assert rev.status == RequestStatus.pending_it and rev.completed_at is None
        assert rev.current_node_type == "it_execute"
        from services.workflow import instance_of, verify_chain
        assert verify_chain(s, instance_of(s, rev).id)
    # Holder ma uprawnienie do realizacji — usunięte uprawnienie nie blokuje realizacji.
    assert _eff(api, g["sup"], g["worker"]) == ["Listy płac"]
    _it_execute(api, rev_ids[0])
    assert _eff(api, g["sup"], g["worker"]) == []
    # Systemowe odebranie nie jest ustaniem stosunku pracy.
    from routers.requests import _is_system_revoke
    with Session(engine) as s:
        assert _is_system_revoke(s, s.get(AccessRequest, rev_ids[0]))
    ev = _events("permission_group.deleted_held")[-1]
    assert "przekazano do realizacji IT" in ev.summary and "1 osoby" in ev.summary


# ---------------------------------------------------------------------------
# 2. Reset fabryczny i tools/reset_data.py — retencja
# ---------------------------------------------------------------------------

def _add_log_entries(when: datetime, n: int = 2) -> None:
    ts = when.strftime("%Y-%m-%d %H:%M:%S.%f")
    with engine.begin() as conn:
        for i in range(n):
            conn.execute(text('INSERT INTO auditlog (timestamp, action, username) '
                              'VALUES (:t, :a, :u)'), {"t": ts, "a": f"test.old{i}", "u": "x"})
            conn.execute(text('INSERT INTO securityevent (created_at, event_type, severity, '
                              'summary) VALUES (:t, :e, :s, :m)'),
                         {"t": ts, "e": f"test.old{i}", "s": "low", "m": "x"})


def _count(table: str, where: str = "1=1") -> int:
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE {where}')).scalar()


def test_factory_reset_wipe_audit_respects_retention(api):
    sup = api.setup_superadmin()
    _add_log_entries(datetime(2020, 1, 1))
    recent_audit = _count("auditlog", "action NOT LIKE 'test.old%'")
    assert recent_audit > 0
    r = api.post("/settings/factory-reset", token=sup, json={
        "password": PW, "confirm": "RESET", "wipe_requests": False,
        "wipe_structure": False, "wipe_users": False, "wipe_audit": True})
    assert r.status_code == 200, r.text
    assert _count("auditlog", "action LIKE 'test.old%'") == 0
    assert _count("securityevent", "event_type LIKE 'test.old%'") == 0
    # Świeże wpisy (np. setup, logowania) zostają — retencja 24 miesiące.
    assert _count("auditlog", "action NOT LIKE 'test.old%' "
                              "AND action <> 'settings.factory_reset'") >= recent_audit
    assert any("24" in d for d in r.json()["details"])
    trace = json.loads(_audit_details("settings.factory_reset"))
    assert trace["audit_retention_months"] == 24


def test_reset_data_tool_retention_triggers_and_trace(api, monkeypatch):
    import sys
    from tools import reset_data
    api.setup_superadmin()
    _add_log_entries(datetime(2020, 1, 1))
    recent = _count("auditlog", "action NOT LIKE 'test.old%'")
    monkeypatch.setattr(sys, "argv", ["reset_data", "--yes"])
    reset_data.main()
    assert _count("auditlog", "action LIKE 'test.old%'") == 0
    assert _count("securityevent", "event_type LIKE 'test.old%'") == 0
    assert _count("auditlog", "action NOT LIKE 'test.old%' "
                              "AND action <> 'settings.factory_reset'") == recent
    # Triggery append-only wróciły w tym samym przebiegu.
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='auditlog'"))}
    assert {"auditlog_no_update", "auditlog_no_delete"} <= names
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM auditlog"))
    # Ślad narzędzia.
    ev = _events("settings.factory_reset")[-1]
    assert ev.source == "tools" and ev.severity == SecuritySeverity.critical
    assert json.loads(ev.details)["source"] == "tools"


# ---------------------------------------------------------------------------
# 3. Wspólny budżet prób hasła
# ---------------------------------------------------------------------------

def test_password_confirm_limit_is_atomic_under_concurrency(api):
    sup = api.setup_superadmin()
    n = 15
    barrier = threading.Barrier(n)
    results: Counter = Counter()
    lock = threading.Lock()

    def worker():
        c = TestClient(app)
        barrier.wait()
        r = c.post("/api/audit/purge", headers={"Authorization": f"Bearer {sup}"},
                   json={"password": "zle-haslo", "reason": "Test wyścigu limitu",
                         "before": "2019-01-01"})
        with lock:
            results[r.status_code] += 1

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results[403] == 5, dict(results)
    assert results[429] == n - 5, dict(results)
    with Session(engine) as s:
        assert len(s.exec(select(PasswordConfirmFailure)).all()) == 5


def _client(ip: str) -> TestClient:
    """Klient „za Apache” — adres klienta z X-Forwarded-For (zaufane proxy)."""
    return TestClient(app, client=("127.0.0.1", 50000), headers={"X-Forwarded-For": ip})


def _login(c: TestClient, password: str, username: str = "root"):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def test_login_lockout_is_per_account_and_ip_and_critical_for_superadmin(api):
    api.setup_superadmin()
    attacker, owner = _client("203.0.113.7"), _client("10.0.0.5")
    for _ in range(4):
        assert _login(attacker, "zle").status_code == 401
    assert _login(attacker, "zle").status_code == 401        # 5. — blokada
    assert _login(attacker, PW).status_code == 423
    # Właściciel konta z innego adresu loguje się normalnie (N8).
    assert _login(owner, PW).status_code == 200
    ev = _events("auth.lockout")
    assert len(ev) == 1 and ev[0].severity == SecuritySeverity.critical
    assert "203.0.113.7" in ev[0].summary and "tools/reset_password.py" in ev[0].summary


def test_ordinary_account_lockout_is_high(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"])
    c = _client("203.0.113.8")
    for _ in range(5):
        _login(c, "zle", "jan")
    assert _login(c, PW, "jan").status_code == 423
    assert _events("auth.lockout")[-1].severity == SecuritySeverity.high
    # Odblokowanie przez administratora czyści budżet prób logowania.
    assert api.post(f"/users/{_uid('jan')}/unlock", token=sup).status_code == 200
    assert _login(c, PW, "jan").status_code == 200


def test_confirm_failures_and_logins_share_one_budget(api):
    c = _client("198.51.100.1")
    api.setup_superadmin()
    sup = _login(c, PW).json()["access_token"]
    h = {"Authorization": f"Bearer {sup}"}
    for _ in range(3):
        r = c.post("/api/audit/purge", headers=h, json={
            "password": "zle", "reason": "Test wspólnego limitu", "before": "2019-01-01"})
        assert r.status_code == 403
    for _ in range(2):
        assert _login(c, "zle").status_code == 401
    # 3 + 2 = 5 prób w oknie — wyczerpane dla logowania i potwierdzeń (N-7).
    assert _login(c, PW).status_code == 423
    r = c.post("/api/audit/purge", headers=h, json={
        "password": PW, "reason": "Test wspólnego limitu", "before": "2019-01-01"})
    assert r.status_code == 429
    # Inny adres: potwierdzenia konta (3) się liczą, logowania z tamtego adresu nie.
    other = _client("198.51.100.2")
    assert _login(other, "zle").status_code == 401
    assert _login(other, PW).status_code == 200


def test_successful_login_clears_only_own_ip_login_failures(api):
    api.setup_superadmin()
    a, b = _client("192.0.2.1"), _client("192.0.2.2")
    for _ in range(3):
        _login(a, "zle")
    _login(b, "zle")
    assert _login(b, PW).status_code == 200
    with Session(engine) as s:
        rows = s.exec(select(PasswordConfirmFailure)).all()
    assert [(r.kind, r.ip) for r in rows] == [("login", "192.0.2.1")] * 3


# ---------------------------------------------------------------------------
# 3b. Zamykanie zdarzeń (N9, N-5, N5)
# ---------------------------------------------------------------------------

def _resolve(api, token, ev_id):
    return api.post(f"/security/{ev_id}/resolve", token=token, json={"note": "ok"})


def _second_superadmin(api, sup, username="root2"):
    uid = api.mk_user(sup, username, ["superadmin"], "Drugi Superadmin")
    return uid, api.login(username)


@pytest.mark.parametrize("event_type,trigger", [
    ("auth.password_change_denied", "change"),
    ("superadmin.confirm_denied", "purge"),
])
def test_superadmin_cannot_resolve_own_password_failures(api, event_type, trigger):
    sup = api.setup_superadmin()
    _uid2, sup2 = _second_superadmin(api, sup)
    if trigger == "change":
        r = api.post("/auth/change-password", token=sup,
                     json={"current_password": "zle", "new_password": "Inne-Haslo-123!"})
        assert r.status_code == 400
    else:
        r = api.post("/audit/purge", token=sup, json={
            "password": "zle", "reason": "Test zamykania zdarzeń", "before": "2019-01-01"})
        assert r.status_code == 403
    ev = _events(event_type)[-1]
    assert _resolve(api, sup, ev.id).status_code == 403
    # Inny superadmin (sprzed zdarzenia) — może.
    assert _resolve(api, sup2, ev.id).status_code == 200


def test_lockout_event_not_resolvable_by_locked_superadmin(api):
    sup = api.setup_superadmin()
    c = _client("203.0.113.9")
    for _ in range(5):
        _login(c, "zle")
    ev = _events("auth.lockout")[-1]
    assert _resolve(api, sup, ev.id).status_code == 403


def test_superadmin_granted_after_event_cannot_resolve_trace(api):
    w = _world(api)
    sup = w["sup"]
    r = _force_delete(api, sup, w["dep"])
    assert r.status_code == 200, r.text
    ev = _events("department.force_deleted")[-1]
    # Superadmin założony po zdarzeniu (przez sprawcę) — 403 (N-5).
    _uid2, sup2 = _second_superadmin(api, sup)
    assert _resolve(api, sup2, ev.id).status_code == 403
    grant = _events("user.roles_granted")[-1]
    assert grant.severity == SecuritySeverity.critical
    assert grant.summary.startswith("Nadano rolę superadmin kontu root2")


def test_superadmin_from_before_event_resolves_trace(api):
    w = _world(api)
    sup = w["sup"]
    _uid2, sup2 = _second_superadmin(api, sup)
    assert _force_delete(api, sup, w["dep"]).status_code == 200
    ev = _events("department.force_deleted")[-1]
    assert _resolve(api, sup, ev.id).status_code == 403
    assert _resolve(api, sup2, ev.id).status_code == 200


def test_role_granted_after_event_blocks_resolve(api):
    """Konto istniało przed zdarzeniem, ale rolę superadmina dostało po nim."""
    w = _world(api)
    sup = w["sup"]
    uid = api.mk_user(sup, "awans", ["viewer"], "Awansowany")
    assert _force_delete(api, sup, w["dep"]).status_code == 200
    ev = _events("department.force_deleted")[-1]
    assert api.patch(f"/users/{uid}", token=sup,
                     json={"roles": ["superadmin"]}).status_code == 200
    assert _resolve(api, api.login("awans"), ev.id).status_code == 403


def test_hr_flag_event_not_resolvable_by_beneficiary(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    a1 = api.mk_user(sup, "adm1", ["admin"], "Admin Jeden")
    api.mk_user(sup, "adm2", ["admin"], "Admin Dwa")
    dep = api.mk_department(sup, unit, None, name="Biuro")
    _set(User, a1, department_id=dep)
    assert api.patch(f"/units/departments/{dep}", token=api.login("adm2"),
                     json={"is_hr": True}).status_code == 200
    ev = _events("department.hr_flag_changed")[-1]
    assert "(1 osoba)" in ev.summary
    assert _resolve(api, api.login("adm1"), ev.id).status_code == 403
    assert _resolve(api, sup, ev.id).status_code == 200


# ---------------------------------------------------------------------------
# 4. Superadmin poza komórkami, kadry z aktywnej komórki, import z AD
# ---------------------------------------------------------------------------

def test_superadmin_cannot_be_assigned_to_department(api):
    w = _world(api)
    sup, root = w["sup"], _uid("root")
    hr_dep = api.hr_department(w["unit"])
    for dep in (w["dep"], hr_dep):
        r = api.patch(f"/users/{root}", token=sup, json={"department_id": dep})
        assert r.status_code == 400 and "komórki" in r.json()["detail"]
    r = api.post("/users/", token=sup, json={
        "username": "sa2", "password": PW, "full_name": "SA", "roles": ["superadmin"],
        "department_id": w["dep"]})
    assert r.status_code == 400
    # Nadanie roli superadmina kontu w komórce — też 400.
    r = api.patch(f"/users/{w['worker']}", token=sup, json={"roles": ["superadmin"]})
    assert r.status_code == 400
    # Odpięcie zawsze działa; zmiana innych pól nie jest blokowana.
    assert api.patch(f"/users/{root}", token=sup,
                     json={"department_id": None}).status_code == 200

    def _check():
        checks = api.get("/settings/health", token=sup).json()["checks"]
        return next(c for c in checks if c["key"] == "superadmin_operational")
    assert _check()["ok"] is True
    _set(User, root, department_id=hr_dep)          # stan sprzed 3.11
    c = _check()
    assert c["ok"] is False and "root (przypisany do komórki)" in c["detail"]
    assert api.patch(f"/users/{root}", token=sup,
                     json={"full_name": "Super Admin 2"}).status_code == 200
    # Superadmin w komórce kadrowej nie ma funkcji kadr.
    from services.permissions import user_is_hr
    with Session(engine) as s:
        assert user_is_hr(s, s.get(User, root)) is False


def test_hr_capability_requires_active_department(api):
    w = _world(api)
    hr_dep = api.hr_department(w["unit"])
    api.mk_user(w["sup"], "kadrowa", ["viewer"], "Kadrowa")
    _set(User, _uid("kadrowa"), department_id=hr_dep)
    from services.permissions import user_is_hr

    def _is_hr():
        with Session(engine) as s:
            return user_is_hr(s, s.get(User, _uid("kadrowa")))
    assert _is_hr() is True
    _set(Department, hr_dep, is_active=False)
    assert _is_hr() is False
    _set(Department, hr_dep, is_active=True, archived_at=datetime.utcnow())
    assert _is_hr() is False


def test_ad_import_does_not_map_into_inactive_department(api, monkeypatch):
    from tests.test_310_identity import _ad_user, _enable_ldap, _mock_ad
    w = _world(api)
    _enable_ldap()
    _set(Department, w["dep"], ldap_dn="ou=k,ou=u,dc=t,dc=l", is_active=False)
    _set(Department, w["parent"], ldap_dn="ou=u,dc=t,dc=l")
    _mock_ad(monkeypatch, [_ad_user("nowy", "OU=K,OU=U,DC=t,DC=l")])
    r = api.post("/users/ldap/import", token=w["sup"], json={"usernames": ["nowy"]})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == "nowy")).first()
    # Ani do nieaktywnej komórki, ani „przeciekiem” do komórki nadrzędnej.
    assert u is None or u.department_id is None
    assert any("nieaktywnej" in d for d in r.json()["details"])


# ---------------------------------------------------------------------------
# 6. OverflowError, limity, znaki niewidoczne
# ---------------------------------------------------------------------------

def test_overflow_ids_give_400_not_500(api):
    w = _world(api)
    sup = w["sup"]
    for method, path, body in (
            ("get", f"/users/{BIG}/permissions", None),
            ("get", f"/systems/{BIG}/permissions", None),
            ("post", f"/security/{BIG}/resolve", {"note": "x"}),
            ("get", f"/registry/granted?system_id={BIG}", None),
            ("post", "/units/departments", {"unit_id": w["unit"], "name": "X",
                                            "manager_user_id": BIG}),
            ("post", "/units/departments", {"unit_id": BIG, "name": "X"})):
        fn = getattr(api, method)
        r = fn(path, token=sup, **({"json": body} if body is not None else {}))
        assert r.status_code in (400, 404), (path, r.status_code, r.text)


@pytest.mark.parametrize("path_body", [
    ("/units/", {"name": "x" * 201, "code": "X"}),
    ("/units/departments", {"name": "x" * 201}),
    ("/units/departments", {"name": "​​"}),
    ("/systems/", {"name": "x" * 201, "all_units": True}),
    ("/systems/", {"name": "Linia\nDruga", "all_units": True}),
    ("/vendors/", {"name": "x" * 201}),
])
def test_name_limits(api, path_body):
    w = _world(api)
    path, body = path_body
    if path == "/units/departments":
        body = {"unit_id": w["unit"], **body}
    r = api.post(path, token=w["sup"], json=body)
    assert r.status_code == 400, r.text


def test_permission_and_deputy_limits(api):
    w = _world(api)
    sup = w["sup"]
    r = api.post(f"/systems/{w['sid']}/permissions", token=sup,
                 json={"permission_name": "x" * 201})
    assert r.status_code == 400
    r = api.post(f"/systems/{w['sid']}/permissions", token=sup,
                 json={"permission_name": "Opis", "description": "d" * 2001})
    assert r.status_code == 400
    r = api.post(f"/systems/{w['sid']}/permissions", token=sup,
                 json={"permission_name": "Opis", "description": "wiersz 1\nwiersz 2"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert api.patch(f"/systems/permissions/{pid}", token=sup,
                     json={"description": "d" * 2001}).status_code == 400
    # Pusty opis nadal czyści pole.
    r = api.patch(f"/systems/permissions/{pid}", token=sup, json={"description": ""})
    assert r.status_code == 200 and not r.json()["description"]
    other = api.mk_user(sup, "zast2", ["viewer"], "Zastępca Dwa")
    r = api.post(f"/units/departments/{w['dep']}/deputies", token=sup,
                 json={"user_id": other, "role_label": "x" * 201})
    assert r.status_code == 400
    r = api.patch(f"/units/departments/{w['dep']}", token=sup, json={"name": "y" * 201})
    assert r.status_code == 400
    r = api.patch(f"/units/departments/{w['dep']}", token=sup, json={"name": None})
    assert r.status_code == 400


def test_person_names_reject_invisible_and_strip_bidi(api):
    sup = api.setup_superadmin()
    r = api.post("/users/", token=sup, json={
        "username": "zw", "password": PW, "full_name": "​‌⁠", "roles": ["viewer"]})
    assert r.status_code == 400 and "niewidocznych" in r.json()["detail"]
    r = api.post("/users/", token=sup, json={
        "username": "rtl", "password": PW, "full_name": "Jan ‮ikswolaK", "roles": ["viewer"]})
    assert r.status_code in (200, 201), r.text
    assert r.json()["full_name"] == "Jan ikswolaK"
    from services.auth_service import clean_text_field
    assert clean_text_field("  ⁦Ala⁩ ", "x") == "Ala"
    assert clean_text_field("a\nb", "x", multiline=True) == "a\nb"


def test_request_worker_name_rejects_bidi_and_invisible(api):
    w = _world(api)
    for name in ("Jan‮ikswolaK", "​​"):
        r = api.post("/requests/", token=api.login("hr"), json={
            "worker_name": name, "unit_id": w["unit"], "department_id": w["dep"],
            "request_type_id": w["rtype"], "items": []})
        assert r.status_code == 400, (name, r.text)


# ---------------------------------------------------------------------------
# 7. Bezczynność i tokeny
# ---------------------------------------------------------------------------

def _token(username: str, *, iat: int) -> tuple[str, str]:
    import jwt
    from services.auth_service import ALGORITHM, _jwt_secret
    jti = f"t{iat}{username}"
    tok = jwt.encode({"sub": username, "uid": _uid(username), "roles": ["superadmin"],
                      "iat": iat, "exp": iat + 8 * 3600, "jti": jti},
                     _jwt_secret(), algorithm=ALGORITHM)
    return tok, jti


def test_server_side_idle_timeout(api):
    from services import auth_service
    api.setup_superadmin()
    now = int(time.time())
    # Token wydany 40 minut temu, bez żadnej aktywności — 401.
    old, _ = _token("root", iat=now - 40 * 60)
    r = api.get("/auth/me", token=old)
    assert r.status_code == 401 and "bezczynności" in r.json()["detail"]
    # Token sprzed 40 minut, ale aktywny 5 minut temu — działa.
    active, jti = _token("root", iat=now - 40 * 60 + 1)
    with Session(engine) as s:
        s.add(SessionActivity(jti=jti, user_id=_uid("root"),
                              last_seen_at=datetime.utcnow() - timedelta(minutes=5)))
        s.commit()
    assert api.get("/auth/me", token=active).status_code == 200
    with Session(engine) as s:
        first = s.get(SessionActivity, jti).last_seen_at
    assert datetime.utcnow() - first < timedelta(seconds=30)
    # Kolejne żądanie w ciągu minuty nie zapisuje aktywności ponownie.
    assert api.get("/auth/me", token=active).status_code == 200
    with Session(engine) as s:
        assert s.get(SessionActivity, jti).last_seen_at == first
    assert auth_service.IDLE_TIMEOUT_MINUTES == 30


def test_idle_value_matches_frontend():
    import re
    from pathlib import Path
    from services.auth_service import IDLE_TIMEOUT_MINUTES
    src = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "hooks"
           / "useIdleLogout.js")
    if not src.exists():
        pytest.skip("brak źródeł frontendu")
    m = re.search(r"IDLE_TIMEOUT_MS\s*=\s*(\d+)\s*\*\s*60\s*\*\s*1000", src.read_text())
    assert m and int(m.group(1)) == IDLE_TIMEOUT_MINUTES


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_tokens_in_previous_format_still_decode(api):
    """Token HS256 zbudowany ręcznie jak python-jose (nagłówek z „typ”, JSON
    z separatorami „,:”) — PyJWT go przyjmuje (wydane tokeny działają po
    aktualizacji)."""
    from services.auth_service import _jwt_secret
    api.setup_superadmin()
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": "root", "roles": ["superadmin"], "role": "superadmin",
                               "uid": _uid("root"), "iat": now, "exp": now + 600,
                               "jti": "jose-format"}, separators=(",", ":")).encode())
    sig = hmac.new(_jwt_secret().encode(), f"{header}.{payload}".encode(),
                   hashlib.sha256).digest()
    token = f"{header}.{payload}.{_b64(sig)}"
    assert api.get("/auth/me", token=token).status_code == 200
    assert api.get("/auth/me", token=token[:-2] + "xx").status_code == 401


# ---------------------------------------------------------------------------
# 8. Teksty i drobne testy pokrycia
# ---------------------------------------------------------------------------

def test_polish_plural_and_local_date():
    from services.security_events import local_date, plural, role_labels
    forms = ("wpis", "wpisy", "wpisów")
    assert [plural(n, *forms) for n in (0, 1, 2, 4, 5, 12, 22, 25, 112, 104)] == \
        ["wpisów", "wpis", "wpisy", "wpisy", "wpisów", "wpisów", "wpisy", "wpisów",
         "wpisów", "wpisy"]
    # Północ czasu polskiego 24.10.2024 to 22:00 UTC dnia poprzedniego.
    assert local_date("2024-10-23T22:00:00") == "24.10.2024"
    assert role_labels(["it_staff", "manager", "admin"]) == ["IT", "kierownik", "administrator"]


def test_purge_trace_summary_is_polish(api):
    sup = api.setup_superadmin()
    r = api.post("/audit/purge", token=sup, json={
        "password": PW, "reason": "Porządki w dzienniku", "before": "2019-01-01"})
    assert r.status_code == 200, r.text
    ev = _events("audit.purged")[-1]
    assert ev.summary.startswith("Wyczyszczono dziennik zdarzeń (0 wpisów sprzed 01.01.2019)")


def test_post_assigned_event_uses_polish_label(api):
    _world(api)
    evs = _events("structure.post_assigned")
    assert evs and all("manager_changed" not in e.summary and "deputy_added" not in e.summary
                       for e in evs)
    assert any("(kierownik komórki)" in e.summary for e in evs)
    assert any("(zastępca kierownika komórki)" in e.summary for e in evs)


def test_entry_guid_conversions():
    import uuid
    from services.ldap_service import entry_guid
    g = uuid.UUID("12345678-1234-5678-9abc-def012345678")

    class Attr:
        def __init__(self, raw=None, value=None):
            if raw is not None:
                self.raw_values = [raw]
            self.value = value

    class Entry:
        entry_dn = "CN=x"

        def __init__(self, attr):
            if attr is not None:
                self.objectGUID = attr

    assert entry_guid(Entry(Attr(raw=g.bytes_le))) == str(g)
    assert entry_guid(Entry(Attr(value=g.bytes_le))) == str(g)
    assert entry_guid(Entry(Attr(value="{" + str(g).upper() + "}"))) == str(g)
    assert entry_guid(Entry(None)) is None
    assert entry_guid(Entry(Attr(value="nie-guid"))) is None
    assert entry_guid(Entry(Attr(value=None))) is None


def test_db_int_ok_non_int_values():
    from services.structure import db_int_ok
    assert db_int_ok(5) and db_int_ok("7") and db_int_ok(2 ** 63 - 1)
    assert not db_int_ok(2 ** 63) and not db_int_ok(-(2 ** 63) - 1)
    assert not db_int_ok(None) and not db_int_ok("abc") and not db_int_ok([1])
