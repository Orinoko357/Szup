"""SZUP 3.10 — tożsamość, sesje i ślady (poprawki po audycie 3.9).

1. Zdolność kadrowa w zdarzeniach bezpieczeństwa (F2, Ś9).
2. Import z AD: bez przenoszenia własnego konta, niejednoznaczne OU,
   zwalnianie stanowisk po przeniesieniu (F3, Ś8).
3. Wspólny, trwały limit prób potwierdzenia hasłem (F5).
4. Ślady czyszczeń: reset fabryczny, atomowość, triggery, retencja 24 mies.,
   zamykanie własnych zdarzeń przez superadmina (F4, F6, Ś10).
5. S7: zdarzenie o powołaniu (new_user_id) zamyka ktoś inny.
6. Zmiana loginu konta AD weryfikowana w AD (F7/H4).
7. Sesje: wylogowanie, zmiana/reset hasła, zmiana loginu, nieprawidłowy JWT.
8. Limit logowań liczy tylko nieudane próby (M10).
9. Limity pól kont i wniosków o zmianę nazwiska (N2).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine, SECURITYEVENT_TRIGGERS
from models import (
    AuditLog, AuthType, Department, LdapSettings, PasswordConfirmFailure,
    SecurityEvent, SecuritySeverity, User,
)
from tests.conftest import PW

NEW_PW = "Inne!Haslo-2026xyz"
REASON = "Porządki retencji dzienników 2026"


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _events(event_type: str) -> list[SecurityEvent]:
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)
                      .order_by(SecurityEvent.id)).all()


def _audit(action: str) -> list[AuditLog]:
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)
                      .order_by(AuditLog.id)).all()


def _details(ev) -> dict:
    return json.loads(ev.details) if ev.details else {}


def _uid(username: str) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.username == username)).one().id


def _set(model, obj_id, **fields):
    with Session(engine) as s:
        obj = s.get(model, obj_id)
        for k, v in fields.items():
            setattr(obj, k, v)
        s.add(obj); s.commit()


def _enable_ldap():
    with Session(engine) as s:
        cfg = s.exec(select(LdapSettings)).first() or LdapSettings()
        cfg.enabled = True; cfg.host = "ad.test"; cfg.base_dn = "DC=t,DC=l"
        s.add(cfg); s.commit()


def _token(username: str) -> str:
    """Token konta AD (logowanie do AD w testach jest symulowane)."""
    from services.auth_service import create_access_token
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).one()
        from models import parse_roles
        return create_access_token(u.username, parse_roles(u.roles), u.id)


def _old_token(username: str, age_s: int = 10) -> str:
    """Token wydany `age_s` sekund temu. `tokens_valid_from` ma rozdzielczość
    pełnej sekundy (token z tej samej sekundy co unieważnienie jest ważny),
    więc „stara” sesja w teście musi być naprawdę starsza."""
    import time
    import uuid
    import jwt  # PyJWT
    from models import parse_roles
    from services.auth_service import ALGORITHM, _jwt_secret
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).one()
        now = int(time.time()) - age_s
        return jwt.encode({"sub": u.username, "roles": parse_roles(u.roles), "uid": u.id,
                           "iat": now, "exp": now + 3600, "jti": uuid.uuid4().hex},
                          _jwt_secret(), algorithm=ALGORITHM)


def _world(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "Urząd", "UM")
    api.mk_user(sup, "adm", ["admin"], "Administrator")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    api.mk_user(sup, "it", ["it_staff"], "Informatyk")
    dep = api.mk_department(sup, unit, kid, name="Wydział A")
    _set(User, kid, department_id=dep)
    hr = api.hr_department(unit)
    return dict(sup=sup, unit=unit, kid=kid, dep=dep, hr=hr, adm=api.login("adm"))


# ---------------------------------------------------------------------------
# 1. Zdolność kadrowa
# ---------------------------------------------------------------------------

def test_create_user_in_hr_department_emits_medium_event(api):
    w = _world(api)
    r = api.post("/users/", token=w["adm"], json={
        "username": "kadrowa", "password": PW, "full_name": "Anna Kadrowa",
        "roles": ["viewer"], "department_id": w["hr"]})
    assert r.status_code == 201, r.text
    evs = _events("user.hr_capability_granted")
    assert len(evs) == 1
    assert evs[0].severity == SecuritySeverity.medium
    d = _details(evs[0])
    assert d["target_user_id"] == r.json()["id"] and d["via"] == "create"
    assert d["department_id"] == w["hr"]
    assert evs[0].user_id == _uid("adm")


def test_patch_into_hr_department_emits_event_only_on_entry(api):
    w = _world(api)
    uid = api.mk_user(w["sup"], "jan", ["viewer"], "Jan Zwykły")
    assert not _events("user.hr_capability_granted")
    r = api.patch(f"/users/{uid}", token=w["adm"], json={"department_id": w["hr"]})
    assert r.status_code == 200, r.text
    assert [_details(e)["via"] for e in _events("user.hr_capability_granted")] == ["update"]
    # Ponowny zapis tej samej komórki i przejście do drugiej komórki kadrowej
    # niczego nie poszerzają — bez kolejnych zdarzeń.
    api.patch(f"/users/{uid}", token=w["adm"], json={"department_id": w["hr"],
                                                     "full_name": "Jan Kadrowy"})
    hr2 = api.hr_department(None)
    assert api.patch(f"/users/{uid}", token=w["adm"],
                     json={"department_id": hr2}).status_code == 200
    assert len(_events("user.hr_capability_granted")) == 1


def test_password_reset_of_hr_member_is_high(api):
    w = _world(api)
    uid = api.mk_user(w["sup"], "kadry1", ["hr"], "Kadrowa", unit_ids=[w["unit"]])
    plain = api.mk_user(w["sup"], "zwykly", ["viewer"], "Zwykły")
    assert api.post(f"/users/{plain}/reset-password", token=w["adm"],
                    json={"new_password": NEW_PW}).status_code == 200
    assert not _events("user.password_reset")
    assert api.post(f"/users/{uid}/reset-password", token=w["adm"],
                    json={"new_password": NEW_PW}).status_code == 200
    evs = _events("user.password_reset")
    assert len(evs) == 1 and evs[0].severity == SecuritySeverity.high
    assert _details(evs[0])["target_user_id"] == uid
    assert "hr" in _details(evs[0])["roles"]


# ---------------------------------------------------------------------------
# 2. Import użytkowników z AD
# ---------------------------------------------------------------------------

def _ad_user(username, ou, *, guid=None, full_name=None):
    return {"dn": f"CN={username},{ou}", "parent_dn": ou, "username": username,
            "full_name": full_name or username, "email": None, "title": "",
            "guid": guid, "is_enabled_in_ad": True}


def _mock_ad(monkeypatch, users):
    import services.ldap_service as ls
    monkeypatch.setattr(ls, "fetch_ldap_users", lambda cfg, base: list(users))


def test_ldap_import_never_moves_importing_admins_own_account(api, monkeypatch):
    w = _world(api)
    _enable_ldap()
    adm_id = _uid("adm")
    _set(Department, w["hr"], ldap_dn="ou=kadry,dc=t,dc=l")
    _set(User, adm_id, auth_type=AuthType.ldap, department_id=w["dep"])
    _mock_ad(monkeypatch, [_ad_user("adm", "OU=Kadry,DC=t,DC=l")])
    adm = _token("adm")
    n_before = len(_events("user.hr_capability_granted"))
    r = api.post("/users/ldap/import", token=adm, json={"usernames": ["adm"]})
    assert r.status_code == 200, r.text
    assert any("Twoje konto" in d for d in r.json()["details"])
    with Session(engine) as s:
        assert s.get(User, adm_id).department_id == w["dep"]
    assert "hr" not in api.get("/auth/me", token=adm).json()["roles"]
    assert len(_events("user.hr_capability_granted")) == n_before


def test_ldap_import_skips_ou_mapped_to_several_departments(api, monkeypatch):
    w = _world(api)
    _enable_ldap()
    sup = w["sup"]
    jan = api.mk_user(sup, "jan", ["viewer"], "Jan")
    _set(User, jan, auth_type=AuthType.ldap, department_id=w["dep"])
    # Ta sama OU dopisana zwykłej komórce i komórce kadrowej — niejednoznaczna.
    _set(Department, w["dep"], ldap_dn="ou=a,dc=t,dc=l")
    _set(Department, w["hr"], ldap_dn="OU=A,DC=t,DC=l")
    from models import Unit
    _set(Unit, w["unit"], ldap_dn="dc=t,dc=l")
    _mock_ad(monkeypatch, [_ad_user("jan", "OU=A,DC=t,DC=l")])
    r = api.post("/users/ldap/import", token=api.login("root"), json={"usernames": ["jan"]})
    assert r.status_code == 200, r.text
    assert any("kilku" in d for d in r.json()["details"])
    with Session(engine) as s:
        assert s.get(User, jan).department_id == w["dep"]
    assert not _events("user.hr_capability_granted")


def test_ldap_import_move_releases_posts_and_reports_hr_capability(api, monkeypatch):
    """Ś8: kierownik przeniesiony w AD do OU kadr — zwolnione stanowisko
    w dawnej komórce, zdarzenie o zdolności kadrowej, zapisany objectGUID."""
    w = _world(api)
    _enable_ldap()
    kid = w["kid"]
    _set(User, kid, auth_type=AuthType.ldap)
    _set(Department, w["dep"], ldap_dn="ou=a,dc=t,dc=l")
    _set(Department, w["hr"], ldap_dn="ou=kadry,dc=t,dc=l")
    guid = "0b7d3c4e-1111-4222-8333-944455556666"
    _mock_ad(monkeypatch, [_ad_user("kier", "OU=Kadry,DC=t,DC=l", guid=guid)])
    r = api.post("/users/ldap/import", token=w["adm"], json={"usernames": ["kier"]})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        u = s.get(User, kid)
        assert u.department_id == w["hr"]
        assert u.ldap_guid == guid
        assert s.get(Department, w["dep"]).manager_user_id is None
    evs = _events("user.hr_capability_granted")
    assert len(evs) == 1 and _details(evs[0])["via"] == "ldap_import"
    assert _details(evs[0])["target_user_id"] == kid
    upd = _audit("user.updated_ad")[-1]
    assert w["dep"] in _details(upd)["structure"]["released_dept_ids"]


def test_ldap_import_new_account_in_hr_ou_emits_event(api, monkeypatch):
    w = _world(api)
    _enable_ldap()
    _set(Department, w["hr"], ldap_dn="ou=kadry,dc=t,dc=l")
    _mock_ad(monkeypatch, [_ad_user("nowa", "OU=Kadry,DC=t,DC=l")])
    r = api.post("/users/ldap/import", token=w["adm"], json={"usernames": ["nowa"]})
    assert r.status_code == 200 and r.json()["created"] == 1, r.text
    evs = _events("user.hr_capability_granted")
    assert len(evs) == 1 and _details(evs[0])["target_user_id"] == _uid("nowa")


# ---------------------------------------------------------------------------
# 3. Wspólny limit prób potwierdzenia hasłem
# ---------------------------------------------------------------------------

def _change_pw(api, token, current, new=NEW_PW):
    return api.post("/auth/change-password", token=token,
                    json={"current_password": current, "new_password": new})


def _purge(api, token, log="audit", **body):
    payload = {"password": PW, "reason": REASON, "before": "2019-01-01", **body}
    return api.post(f"/{log}/purge", token=token, json=payload)


def test_change_password_guessing_is_limited_and_blocks_purge(api):
    sup = api.setup_superadmin()
    for i in range(5):
        assert _change_pw(api, sup, f"zle-{i}").status_code == 400
    # Limit wyczerpany: zmiana hasła i operacje superadmina — także z poprawnym hasłem.
    assert _change_pw(api, sup, PW).status_code == 429
    assert _purge(api, sup).status_code == 429
    r = api.post("/settings/factory-reset", token=sup, json={
        "password": PW, "confirm": "RESET", "wipe_requests": False,
        "wipe_structure": False, "wipe_users": False})
    assert r.status_code == 429
    evs = _events("auth.password_change_denied")
    assert len(evs) == 5
    # Konto uprzywilejowane: high, a próba wyczerpująca limit — critical.
    assert [e.severity for e in evs] == [SecuritySeverity.high] * 4 + [SecuritySeverity.critical]
    # Licznik jest w bazie (przetrwa restart usługi).
    with Session(engine) as s:
        assert len(s.exec(select(PasswordConfirmFailure)).all()) == 5


def test_ordinary_account_change_password_events_are_medium(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"])
    tok = api.login("jan")
    assert _change_pw(api, tok, "zle").status_code == 400
    evs = _events("auth.password_change_denied")
    assert len(evs) == 1 and evs[0].severity == SecuritySeverity.medium
    # Udana zmiana hasła zeruje licznik.
    assert _change_pw(api, tok, PW).status_code == 200
    with Session(engine) as s:
        assert not s.exec(select(PasswordConfirmFailure)).all()


def test_purge_and_factory_reset_failures_share_the_counter(api):
    sup = api.setup_superadmin()
    for _ in range(3):
        assert _purge(api, sup, password="zle").status_code == 403
    for _ in range(2):
        r = api.post("/settings/factory-reset", token=sup, json={
            "password": "zle", "confirm": "RESET", "wipe_requests": False,
            "wipe_structure": False, "wipe_users": False})
        assert r.status_code == 403
    assert _events("settings.factory_reset_denied")[-1].severity == SecuritySeverity.critical
    assert _change_pw(api, sup, PW).status_code == 429


def test_limit_window_expires(api):
    sup = api.setup_superadmin()
    uid = _uid("root")
    with Session(engine) as s:
        old = datetime.utcnow() - timedelta(minutes=16)
        for _ in range(5):
            s.add(PasswordConfirmFailure(user_id=uid, created_at=old, operation="x"))
        s.commit()
    assert _change_pw(api, sup, PW).status_code == 200


# ---------------------------------------------------------------------------
# 4. Ślady czyszczeń, retencja, zamykanie zdarzeń
# ---------------------------------------------------------------------------

def _add_old_entries(when=datetime(2018, 5, 1)):
    with Session(engine) as s:
        for i in range(3):
            s.add(AuditLog(timestamp=when, action=f"test.old.{i}", username="x"))
            s.add(SecurityEvent(created_at=when, event_type=f"test.old.{i}",
                                summary="stare zdarzenie"))
        s.commit()


def test_factory_reset_wipe_audit_keeps_purge_and_reset_traces(api):
    sup = api.setup_superadmin()
    _add_old_entries()
    assert _purge(api, sup).status_code == 200
    assert _purge(api, sup, log="security").status_code == 200
    body = {"password": PW, "confirm": "RESET", "wipe_requests": False,
            "wipe_structure": False, "wipe_users": False, "wipe_audit": True}
    assert api.post("/settings/factory-reset", token=sup, json=body).status_code == 200
    assert api.post("/settings/factory-reset", token=sup, json=body).status_code == 200
    for action in ("audit.purged", "security.purged"):
        assert len(_audit(action)) == 1 and len(_events(action)) == 1
    # Oba resety zostawiły ślad — drugi nie usunął pierwszego.
    assert len(_audit("settings.factory_reset")) == 2
    assert len(_events("settings.factory_reset")) == 2
    assert _details(_audit("settings.factory_reset")[-1])["scope"]["wipe_audit"] is True
    # Stare wpisy zniknęły; świeże (np. logowanie) zostają — retencja 24 mies. (3.11).
    assert not _audit("test.old.0")
    assert _audit("login.success")


def test_securityevent_trace_rows_are_append_only(api):
    sup = api.setup_superadmin()
    _add_old_entries()
    assert _purge(api, sup).status_code == 200
    trace_id = _events("audit.purged")[0].id
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='securityevent'"))}
        assert set(SECURITYEVENT_TRIGGERS) <= names
    for sql in (f"DELETE FROM securityevent WHERE id = {trace_id}",
                f"UPDATE securityevent SET summary = 'x' WHERE id = {trace_id}",
                f"UPDATE securityevent SET event_type = 'inne' WHERE id = {trace_id}"):
        with engine.connect() as conn:
            with pytest.raises(Exception):
                conn.execute(text(sql))
                conn.commit()
    # Zwykłe zdarzenia nadal można usuwać, a ślad — zamknąć (kolumny resolved_*).
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM securityevent WHERE event_type LIKE 'test.old.%'"))
        conn.execute(text(f"UPDATE securityevent SET resolution_note = 'ok' WHERE id = {trace_id}"))
        conn.commit()


def test_purge_trace_written_in_same_transaction(api, monkeypatch):
    """F6: ślad nie zależy od ORM ani od osobnego commitu — powstaje razem
    z usunięciem, a jego błąd wycofuje całe czyszczenie."""
    sup = api.setup_superadmin()
    _add_old_entries()
    import services.audit as sa
    import services.security_events as se

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("db busy")

    monkeypatch.setattr(sa, "AuditLog", Boom)
    monkeypatch.setattr(se, "SecurityEvent", Boom)
    r = _purge(api, sup)
    monkeypatch.undo()
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 3
    tr = _audit("audit.purged")
    assert len(tr) == 1 and len(_events("audit.purged")) == 1
    d = _details(tr[0])
    assert d["deleted_by_type"] == {"test.old.0": 1, "test.old.1": 1, "test.old.2": 1}
    assert d["retention_months"] == 24

    # Błąd zapisu śladu → nic nie zostaje usunięte.
    _add_old_entries()

    def broken_writer(**kw):
        def write(cur, deleted, by_type):
            raise RuntimeError("awaria zapisu śladu")
        return write

    monkeypatch.setattr(sa, "_purge_trace_writer", broken_writer)
    r = _purge(api, sup)
    monkeypatch.undo()
    assert r.status_code == 500
    assert len(_audit("audit.purged")) == 1
    with Session(engine) as s:
        assert len(s.exec(select(AuditLog).where(AuditLog.action.like("test.old.%"))).all()) == 3


def test_purge_respects_24_month_retention(api):
    from services.audit import retention_limit
    sup = api.setup_superadmin()
    r = _purge(api, sup, mode="all")
    assert r.status_code == 400 and "24" in r.json()["detail"]
    r = _purge(api, sup, before="2099-01-01")
    assert r.status_code == 400 and "przyszłości" in r.json()["detail"]
    limit = retention_limit()
    too_late = (limit + timedelta(days=2)).date().isoformat()
    r = _purge(api, sup, before=too_late)
    assert r.status_code == 400 and "24 miesiące" in r.json()["detail"]
    r = _purge(api, sup, before=(datetime.utcnow() - timedelta(days=1)).date().isoformat())
    assert r.status_code == 400
    ok = (limit - timedelta(days=2)).date().isoformat()
    r = _purge(api, sup, before=ok)
    assert r.status_code == 200, r.text
    assert not _events("superadmin.confirm_denied")


def test_retention_limit_handles_leap_day():
    from services.audit import retention_limit
    assert retention_limit(datetime(2028, 2, 29, 12, 0)) == datetime(2026, 2, 28, 12, 0)
    assert retention_limit(datetime(2026, 10, 23)) == datetime(2024, 10, 23)


def test_superadmin_cannot_resolve_own_purge_event(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "sup2", ["superadmin"], "Drugi Superadmin")
    _add_old_entries()
    assert _purge(api, sup).status_code == 200
    ev = _events("audit.purged")[0]
    r = api.post(f"/security/{ev.id}/resolve", token=sup, json={"note": "moje"})
    assert r.status_code == 403 and "inny superadmin" in r.json()["detail"]
    r = api.post(f"/security/{ev.id}/resolve", token=api.login("sup2"),
                 json={"note": "sprawdzone"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(SecurityEvent, ev.id).resolved_by_user_id == _uid("sup2")


def test_superadmin_cannot_resolve_own_force_delete_event(api):
    sup = api.setup_superadmin()
    with Session(engine) as s:
        ev = SecurityEvent(event_type="department.force_deleted",
                           severity=SecuritySeverity.high, summary="usunięto komórkę",
                           user_id=_uid("root"))
        s.add(ev); s.commit(); eid = ev.id
    assert api.post(f"/security/{eid}/resolve", token=sup, json={}).status_code == 403


# ---------------------------------------------------------------------------
# 5. S7 — powołanie na stanowisko (new_user_id)
# ---------------------------------------------------------------------------

def test_admin_cannot_resolve_event_about_own_appointment(api):
    w = _world(api)
    adm_id = _uid("adm")
    with Session(engine) as s:
        ev = SecurityEvent(event_type="structure.post_assigned",
                           severity=SecuritySeverity.medium,
                           summary="Powołano kierownika", user_id=w["kid"],
                           details=json.dumps({"new_user_id": adm_id}))
        s.add(ev); s.commit(); eid = ev.id
    r = api.post(f"/security/{eid}/resolve", token=w["adm"], json={})
    assert r.status_code == 403
    api.mk_user(w["sup"], "adm2", ["admin"])
    assert api.post(f"/security/{eid}/resolve", token=api.login("adm2"),
                    json={}).status_code == 200


# ---------------------------------------------------------------------------
# 6. Zmiana loginu konta AD
# ---------------------------------------------------------------------------

def _ldap_name_change(api, w, *, ldap_dn="cn=jan kierownik,ou=a,dc=t,dc=l", guid=None):
    _enable_ldap()
    _set(User, w["kid"], auth_type=AuthType.ldap, ldap_dn=ldap_dn, ldap_guid=guid)
    r = api.post("/name-changes", token=_token("kier"),
                 json={"requested_full_name": "Jan Nowak"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mock_lookup(monkeypatch, status, **info):
    import services.ldap_service as ls
    calls = []

    def fake(cfg, username):
        calls.append(username)
        return status, dict(info)
    monkeypatch.setattr(ls, "lookup_user", fake)
    return calls


def _resolve(api, nid, token, **body):
    return api.post(f"/name-changes/{nid}/resolve", token=token,
                    json={"action": "apply", **body})


def test_ad_login_change_requires_same_ad_object(api, monkeypatch):
    w = _world(api)
    nid = _ldap_name_change(api, w)
    _mock_lookup(monkeypatch, "ok", dn="CN=Inna Osoba,OU=A,DC=t,DC=l", guid=None)
    r = _resolve(api, nid, api.login("it"), new_username="wspolnik")
    assert r.status_code == 403 and "innej osoby" in r.json()["detail"]
    with Session(engine) as s:
        u = s.get(User, w["kid"])
        assert u.username == "kier" and u.full_name == "Jan Kierownik"
    assert not _events("user.login_changed")


def test_ad_login_change_verified_by_dn(api, monkeypatch):
    w = _world(api)
    nid = _ldap_name_change(api, w)
    calls = _mock_lookup(monkeypatch, "ok", dn="CN=Jan Kierownik, OU=A,DC=t,DC=l", guid=None)
    old = _token("kier")
    r = _resolve(api, nid, api.login("it"), new_username="J.Nowak")
    assert r.status_code == 200, r.text
    assert calls == ["j.nowak"]
    assert r.json()["new_username"] == "j.nowak"
    ev = _events("user.login_changed")[0]
    assert _details(ev)["ad_verified_by"] == "dn"
    # Stara sesja nie działa po zmianie loginu.
    assert api.get("/auth/me", token=old).status_code == 401


def test_ad_login_change_verified_by_guid_after_rename(api, monkeypatch):
    w = _world(api)
    guid = "0b7d3c4e-1111-4222-8333-944455556666"
    nid = _ldap_name_change(api, w, guid=guid)
    # CN zmienione w AD razem z nazwiskiem — DN inny, objectGUID ten sam.
    _mock_lookup(monkeypatch, "ok", dn="CN=Jan Nowak,OU=A,DC=t,DC=l", guid=guid.upper())
    r = _resolve(api, nid, api.login("it"), new_username="jnowak")
    assert r.status_code == 200, r.text
    assert _details(_events("user.login_changed")[0])["ad_verified_by"] == "guid"


def test_ad_login_change_refused_when_ad_unavailable(api, monkeypatch):
    w = _world(api)
    nid = _ldap_name_change(api, w)
    _mock_lookup(monkeypatch, "error", message="timeout")
    it = api.login("it")
    r = _resolve(api, nid, it, new_username="jnowak")
    assert r.status_code == 403 and "bez zmiany loginu" in r.json()["detail"]
    # Sama zmiana nazwiska — bez pytania AD.
    r = _resolve(api, nid, it)
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        u = s.get(User, w["kid"])
        assert u.username == "kier" and u.full_name == "Jan Nowak"


def test_ad_login_change_refused_without_stored_identity_or_config(api, monkeypatch):
    w = _world(api)
    nid = _ldap_name_change(api, w, ldap_dn=None)
    calls = _mock_lookup(monkeypatch, "ok", dn="CN=x,DC=t,DC=l", guid=None)
    r = _resolve(api, nid, api.login("it"), new_username="jnowak")
    assert r.status_code == 403 and "tożsamości z AD" in r.json()["detail"]
    with Session(engine) as s:
        cfg = s.exec(select(LdapSettings)).first()
        cfg.enabled = False; s.add(cfg)
        u = s.get(User, w["kid"]); u.ldap_dn = "cn=x,dc=t,dc=l"; s.add(u)
        s.commit()
    r = _resolve(api, nid, api.login("it"), new_username="jnowak")
    assert r.status_code == 403 and "wyłączone" in r.json()["detail"]
    assert calls == []


def test_ad_login_not_found_in_ad(api, monkeypatch):
    w = _world(api)
    nid = _ldap_name_change(api, w)
    _mock_lookup(monkeypatch, "not_found")
    r = _resolve(api, nid, api.login("it"), new_username="jnowak")
    assert r.status_code == 400 and "nie istnieje w AD" in r.json()["detail"]


def test_local_account_login_change_needs_no_ad(api, monkeypatch):
    _world(api)
    calls = _mock_lookup(monkeypatch, "error", message="nie wołać")
    old = api.login("kier")
    nid = api.post("/name-changes", token=old,
                   json={"requested_full_name": "Jan Nowak"}).json()["id"]
    assert _resolve(api, nid, api.login("it"), new_username="jnowak").status_code == 200
    assert calls == []
    assert api.get("/auth/me", token=old).status_code == 401
    assert api.login("jnowak")


# ---------------------------------------------------------------------------
# 7. Sesje
# ---------------------------------------------------------------------------

def test_logout_revokes_only_that_token(api):
    api.setup_superadmin()
    t1, t2 = api.login("root"), api.login("root")
    assert api.post("/auth/logout", token=t1).status_code == 200
    assert api.get("/auth/me", token=t1).status_code == 401
    assert api.get("/auth/me", token=t2).status_code == 200
    assert api.get("/auth/me", token=api.login("root")).status_code == 200


def test_password_change_invalidates_older_tokens(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"])
    t1, t2 = _old_token("jan"), _old_token("jan", 20)
    assert _change_pw(api, t1, PW).status_code == 200
    assert api.get("/auth/me", token=t1).status_code == 401
    assert api.get("/auth/me", token=t2).status_code == 401
    assert api.get("/auth/me", token=api.login("jan", NEW_PW)).status_code == 200


def test_admin_password_reset_invalidates_tokens_immediately(api):
    sup = api.setup_superadmin()
    uid = api.mk_user(sup, "jan", ["viewer"])
    tok = _old_token("jan")
    assert api.post(f"/users/{uid}/reset-password", token=sup,
                    json={"new_password": NEW_PW}).status_code == 200
    assert api.get("/auth/me", token=tok).status_code == 401
    with Session(engine) as s:
        u = s.get(User, uid)
        # Bez dawnego marginesu −5 s: granica to pełna bieżąca sekunda.
        assert u.tokens_valid_from >= datetime.utcnow().replace(microsecond=0) - timedelta(seconds=2)
    fresh = api.login("jan", NEW_PW)
    assert api.get("/auth/me", token=fresh).status_code == 200


@pytest.mark.parametrize("token", [
    "smieci",
    "a.b.c",
    # poprawna struktura, zły podpis
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJyb290IiwidWlkIjoxfQ.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
])
def test_garbage_jwt_is_rejected(api, token):
    api.setup_superadmin()
    assert api.get("/auth/me", token=token).status_code == 401
    assert api.post("/auth/logout", token=token).status_code == 401


def test_token_without_uid_or_wrong_key_is_rejected(api):
    import jwt  # PyJWT
    from services.auth_service import ALGORITHM, _jwt_secret
    import time
    api.setup_superadmin()
    now = int(time.time())
    no_uid = jwt.encode({"sub": "root", "iat": now, "exp": now + 60}, _jwt_secret(),
                        algorithm=ALGORITHM)
    assert api.get("/auth/me", token=no_uid).status_code == 401
    other_key = jwt.encode({"sub": "root", "uid": _uid("root"), "iat": now, "exp": now + 60},
                           "inny-klucz", algorithm=ALGORITHM)
    assert api.get("/auth/me", token=other_key).status_code == 401
    expired = jwt.encode({"sub": "root", "uid": _uid("root"), "iat": now - 120,
                          "exp": now - 60}, _jwt_secret(), algorithm=ALGORITHM)
    assert api.get("/auth/me", token=expired).status_code == 401


# ---------------------------------------------------------------------------
# 8. Limit logowań — tylko nieudane próby
# ---------------------------------------------------------------------------

def test_successful_logins_do_not_count_towards_ip_limit(api):
    api.setup_superadmin()
    for _ in range(15):
        api.login("root")


def test_failed_logins_are_limited_per_ip(api):
    api.setup_superadmin()
    for _ in range(10):
        r = api.post("/auth/login", json={"username": "root", "password": "zle"})
        assert r.status_code in (401, 423)
    r = api.post("/auth/login", json={"username": "root", "password": PW})
    assert r.status_code == 429


def test_failed_login_tracking_is_bounded(monkeypatch):
    from routers import auth
    monkeypatch.setattr(auth, "_IP_HITS_MAX_KEYS", 50)
    auth._ip_hits.clear()
    for i in range(200):
        auth._register_failed_login(f"10.0.{i // 250}.{i % 250}")
    assert 0 < len(auth._ip_hits) <= 51
    auth._ip_hits.clear()


# ---------------------------------------------------------------------------
# 9. Limity pól
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("full_name", "x" * 201),
    ("full_name", "Jan\nKowalski"),
    ("full_name", "Jan\x00Kowalski"),
    ("email", "a" * 195 + "@t.local"),
    ("username", "u" * 201),
    ("username", "jan\r\nadmin"),
])
def test_user_create_rejects_oversized_or_control_chars(api, field, value):
    sup = api.setup_superadmin()
    body = {"username": "jan", "password": PW, "full_name": "Jan", "roles": ["viewer"],
            field: value}
    r = api.post("/users/", token=sup, json=body)
    assert r.status_code == 400, r.text
    assert isinstance(r.json()["detail"], str)


def test_user_update_rejects_oversized_name_and_trims(api):
    sup = api.setup_superadmin()
    uid = api.mk_user(sup, "jan", ["viewer"])
    assert api.patch(f"/users/{uid}", token=sup,
                     json={"full_name": "J" * 300}).status_code == 400
    assert api.patch(f"/users/{uid}", token=sup,
                     json={"email": "a@b.pl\r\nBcc: x@y"}).status_code == 400
    r = api.patch(f"/users/{uid}", token=sup, json={"full_name": "  Jan Nowak  "})
    assert r.status_code == 200 and r.json()["full_name"] == "Jan Nowak"


def test_name_change_request_limits(api):
    sup = api.setup_superadmin()
    api.mk_user(sup, "jan", ["viewer"], "Jan Kowalski")
    tok = api.login("jan")
    r = api.post("/name-changes", token=tok, json={"requested_full_name": "N" * 101})
    assert r.status_code == 400 and "100" in r.json()["detail"]
    r = api.post("/name-changes", token=tok, json={"requested_full_name": "Jan\r\nNowak"})
    assert r.status_code == 400
    r = api.post("/name-changes", token=tok, json={"requested_full_name": "Jan\tNowak"})
    assert r.status_code == 400
    r = api.post("/name-changes", token=tok, json={"requested_full_name": "N" * 100})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# GET /users/my-workers — will_take_over
# ---------------------------------------------------------------------------

def test_my_workers_will_take_over_flag(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "Urząd", "UM")
    nacz = api.mk_user(sup, "nacz", ["manager"], "Naczelnik")
    kier = api.mk_user(sup, "kier", ["manager"], "Kierownik")
    parent = api.mk_department(sup, unit, nacz, name="Wydział")
    child = api.mk_department(sup, unit, kier, name="Referat", parent_dept_id=parent)
    w1 = api.mk_user(sup, "w1", ["viewer"], "Pracownik Wydziału")
    w2 = api.mk_user(sup, "w2", ["viewer"], "Pracownik Referatu")
    _set(User, nacz, department_id=parent)
    _set(User, kier, department_id=child)
    _set(User, w1, department_id=parent)
    _set(User, w2, department_id=child)

    def flags(token):
        rows = api.get("/users/my-workers", token=token).json()
        return {r["username"]: r["will_take_over"] for r in rows}

    f = flags(api.login("nacz"))
    assert f["nacz"] is False and f["w1"] is False
    assert f["w2"] is True and f["kier"] is True
    assert flags(api.login("kier"))["w2"] is False
    # Kierownik referatu nieaktywny — wniosek trafia wprost do przełożonego.
    _set(User, kier, is_active=False)
    assert flags(api.login("nacz"))["w2"] is False


def test_archived_or_inactive_department_rejects_accounts(api):
    w = _world(api)
    _set(Department, w["dep"], archived_at=datetime.utcnow(), archived_reason="likwidacja")
    r = api.post("/users/", token=w["adm"], json={
        "username": "nowy", "password": PW, "full_name": "Nowy", "roles": ["viewer"],
        "department_id": w["dep"]})
    assert r.status_code == 400 and "zlikwidowana" in r.json()["detail"]
    uid = api.mk_user(w["sup"], "jan", ["viewer"])
    assert api.patch(f"/users/{uid}", token=w["adm"],
                     json={"department_id": w["dep"]}).status_code == 400
    _set(Department, w["hr"], is_active=False)
    assert api.patch(f"/users/{uid}", token=w["adm"],
                     json={"department_id": w["hr"]}).status_code == 400
    # Konto już w zlikwidowanej komórce można edytować bez zmiany komórki.
    r = api.patch(f"/users/{w['kid']}", token=w["sup"],
                  json={"department_id": w["dep"], "full_name": "Jan K."})
    assert r.status_code == 200, r.text


def test_effective_permissions_skip_system_revoked_grants(api):
    from models import AccessRequest, RequestItem, RequestStatus
    from routers.users import _effective_permissions
    w = _world(api)
    sid, pid = api.mk_system_perm(w["sup"], "FK", "Odczyt")
    now = datetime.utcnow()
    with Session(engine) as s:
        req = AccessRequest(worker_name="Jan", worker_user_id=w["kid"], unit_id=w["unit"],
                            department_id=w["dep"], kind="grant",
                            status=RequestStatus.completed, created_at=now,
                            approved_at=now, completed_at=now)
        s.add(req); s.flush()
        item = RequestItem(request_id=req.id, system_id=sid, permission_id=pid,
                           kind="grant", fulfilled=True, fulfilled_at=now)
        s.add(item); s.commit(); item_id = item.id
        assert len(_effective_permissions(s, w["kid"])["permissions"]) == 1
    _set(RequestItem, item_id, revoked_by_request_id=req.id)
    with Session(engine) as s:
        assert _effective_permissions(s, w["kid"])["permissions"] == []
