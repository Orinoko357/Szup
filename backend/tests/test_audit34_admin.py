"""
Audyt 3.4 — administracja: import AD, SSO-exchange, /api/health, reset
fabryczny, ślady w audit logu, SMTP, zdarzenia bezpieczeństwa, migawki.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import text
from sqlmodel import Session, select

from database import engine
from models import (AuditLog, Department, LdapSettings, SecurityEvent, SecuritySeverity,
                    Unit, User)
from tests.conftest import PW


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

def _audit_rows(action: str) -> list[AuditLog]:
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)
                      .order_by(AuditLog.id)).all()


def _security_rows(event_type: str) -> list[SecurityEvent]:
    with Session(engine) as s:
        return s.exec(select(SecurityEvent).where(SecurityEvent.event_type == event_type)
                      .order_by(SecurityEvent.id)).all()


def _mk_ldap_user(api, root, username, roles=None, department_id=None):
    body = {"username": username, "full_name": username, "auth_type": "ldap",
            "roles": roles or ["viewer"]}
    if department_id is not None:
        body["department_id"] = department_id
    r = api.post("/users/", token=root, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

def test_health_endpoint_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["time_utc"].endswith("Z")


# ---------------------------------------------------------------------------
# SSO: wymiana jednorazowego kodu
# ---------------------------------------------------------------------------

def _sso_code(user_id: int, ttl: float = 60.0) -> str:
    from routers import auth as auth_router
    code = f"code-{user_id}-{time.monotonic()}"
    auth_router._sso_codes[code] = (user_id, time.monotonic() + ttl)
    return code


def test_sso_exchange_code_is_one_time(api):
    root = api.setup_superadmin()
    uid = _mk_ldap_user(api, root, "jan.sso")
    code = _sso_code(uid)
    r = api.post("/auth/sso-exchange", json={"code": code})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "jan.sso"
    assert r.json()["access_token"]
    # Drugie użycie tego samego kodu — odrzucone.
    assert api.post("/auth/sso-exchange", json={"code": code}).status_code == 401
    # Kod nieznany — odrzucony.
    assert api.post("/auth/sso-exchange", json={"code": "nope"}).status_code == 401


def test_sso_exchange_expired_code(api):
    root = api.setup_superadmin()
    uid = _mk_ldap_user(api, root, "jan.expired")
    code = _sso_code(uid, ttl=-1)
    assert api.post("/auth/sso-exchange", json={"code": code}).status_code == 401


def test_sso_exchange_inactive_or_local_account(api):
    root = api.setup_superadmin()
    uid = _mk_ldap_user(api, root, "jan.off")
    assert api.patch(f"/users/{uid}", token=root,
                     json={"is_active": False}).status_code == 200
    assert api.post("/auth/sso-exchange",
                    json={"code": _sso_code(uid)}).status_code == 401
    # Konto lokalne nie loguje się przez SSO, nawet z ważnym kodem.
    local_id = api.mk_user(root, "lokalny", ["viewer"])
    assert api.post("/auth/sso-exchange",
                    json={"code": _sso_code(local_id)}).status_code == 401


# ---------------------------------------------------------------------------
# Import użytkowników z AD (LDAP zamockowany)
# ---------------------------------------------------------------------------

_BASE = "DC=t,DC=local"
_UNIT_DN = "OU=Urzad,DC=t,DC=local"
_DEPT_DN = "OU=Informatyka,OU=Urzad,DC=t,DC=local"


def _setup_ad_structure(api, root) -> tuple[int, int]:
    unit_id = api.mk_unit(root, name="Urząd")
    dept_id = api.mk_department(root, unit_id, None, name="Informatyka")
    with Session(engine) as s:
        u = s.get(Unit, unit_id); u.ldap_dn = _UNIT_DN.lower(); s.add(u)
        d = s.get(Department, dept_id); d.ldap_dn = _DEPT_DN.lower(); s.add(d)
        s.add(LdapSettings(enabled=True, host="ldap.test", base_dn=_BASE))
        s.commit()
    return unit_id, dept_id


def _ad_entry(sam, enabled=True, full_name=None):
    dn = f"CN={full_name or sam},{_DEPT_DN}"
    return {"dn": dn, "parent_dn": _DEPT_DN, "username": sam,
            "full_name": full_name or sam, "email": None, "title": None,
            "is_enabled_in_ad": enabled}


def test_ad_import_normalizes_and_deactivates(api, monkeypatch):
    root = api.setup_superadmin()
    _unit_id, dept_id = _setup_ad_structure(api, root)
    # Kierownik komórki z AD — za chwilę wyłączony w AD.
    anna_id = _mk_ldap_user(api, root, "anna", roles=["manager"], department_id=dept_id)
    with Session(engine) as s:
        assert s.get(Department, dept_id).manager_user_id == anna_id
    # Konto, którego AD nie zwróci — NIE może zostać dezaktywowane.
    ghost_id = _mk_ldap_user(api, root, "ghost")

    entries = [
        _ad_entry("Jan.Kowalski", full_name="Jan Kowalski"),
        _ad_entry("ANNA", enabled=False),
    ]
    import services.ldap_service as ldap_service
    monkeypatch.setattr(ldap_service, "fetch_ldap_users", lambda cfg, base: [dict(e) for e in entries])

    r = api.post("/users/ldap/import", token=root,
                 json={"usernames": ["DOMENA\\Jan.Kowalski", "anna@t.local", "ghost"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 1 and res["updated"] == 1, res
    assert any("ghost" in d and "nie znaleziony" in d for d in res["details"])

    with Session(engine) as s:
        jan = s.exec(select(User).where(User.username == "jan.kowalski")).first()
        assert jan is not None and jan.auth_type == "ldap" and jan.department_id == dept_id
        assert s.get(User, anna_id).is_active is False
        assert s.get(Department, dept_id).manager_user_id is None
        assert s.get(User, ghost_id).is_active is True

    deact = _audit_rows("user.deactivated_ad")
    assert len(deact) == 1 and deact[0].target_id == str(anna_id)
    assert _audit_rows("user.created_ad")

    # Ponowny import: konto już nieaktywne — bez zmian, bez drugiego wpisu.
    r = api.post("/users/ldap/import", token=root, json={"usernames": ["anna"]})
    assert r.status_code == 200
    assert r.json()["skipped"] == 1
    assert len(_audit_rows("user.deactivated_ad")) == 1


def test_ad_import_releases_posts_of_already_inactive_account(api, monkeypatch):
    root = api.setup_superadmin()
    _unit_id, dept_id = _setup_ad_structure(api, root)
    anna_id = _mk_ldap_user(api, root, "anna", roles=["manager"], department_id=dept_id)
    # Stan sprzed poprawki: konto nieaktywne, ale wciąż kierownikiem komórki.
    with Session(engine) as s:
        a = s.get(User, anna_id); a.is_active = False; s.add(a); s.commit()
        assert s.get(Department, dept_id).manager_user_id == anna_id

    import services.ldap_service as ldap_service
    monkeypatch.setattr(ldap_service, "fetch_ldap_users",
                        lambda cfg, base: [_ad_entry("anna", enabled=False)])
    r = api.post("/users/ldap/import", token=root, json={"usernames": ["anna"]})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    with Session(engine) as s:
        assert s.get(Department, dept_id).manager_user_id is None


# ---------------------------------------------------------------------------
# Audit log: zmiany kont, role, reset hasła
# ---------------------------------------------------------------------------

def test_user_changes_are_audited(api):
    root = api.setup_superadmin()
    uid = api.mk_user(root, "kowal", ["viewer"])
    created = _audit_rows("user.created")
    assert created and created[-1].target_id == str(uid)
    assert json.loads(created[-1].details)["roles"] == ["viewer"]

    r = api.patch(f"/users/{uid}", token=root, json={"roles": ["viewer", "manager"]})
    assert r.status_code == 200, r.text
    upd = _audit_rows("user.updated")
    assert upd, "brak wpisu user.updated"
    changes = json.loads(upd[-1].details)["changes"]
    assert changes["roles"] == {"old": ["viewer"], "new": ["manager", "viewer"]}
    granted = _security_rows("user.roles_granted")
    assert granted and granted[-1].severity == SecuritySeverity.medium

    assert api.patch(f"/users/{uid}", token=root,
                     json={"roles": ["admin"]}).status_code == 200
    assert _security_rows("user.roles_granted")[-1].severity == SecuritySeverity.high

    r = api.post(f"/users/{uid}/reset-password", token=root,
                 json={"new_password": "Inne-Haslo-123!x"})
    assert r.status_code == 200, r.text
    reset = _audit_rows("user.password_reset")
    assert reset and "Inne-Haslo" not in (reset[-1].details or "")

    # Zmiana bez różnic (te same role) — bez wpisu.
    n = len(_audit_rows("user.updated"))
    api.patch(f"/users/{uid}", token=root, json={"roles": ["admin"]})
    assert len(_audit_rows("user.updated")) == n


def test_deputy_and_template_changes_are_audited(api):
    root = api.setup_superadmin()
    unit_id = api.mk_unit(root)
    mgr = api.mk_user(root, "kier", ["manager"])
    dep = api.mk_user(root, "zast", ["viewer"])
    dept_id = api.mk_department(root, unit_id, mgr)
    assert _audit_rows("department.manager_changed")

    r = api.post(f"/units/departments/{dept_id}/deputies", token=root, json={"user_id": dep})
    assert r.status_code == 201, r.text
    assert _audit_rows("department.deputy_added")
    assert any(json.loads(e.details or "{}").get("action") == "department.deputy_added"
               for e in _security_rows("structure.post_assigned"))
    assert api.delete(f"/units/departments/deputies/{r.json()['id']}",
                      token=root).status_code == 204
    assert _audit_rows("department.deputy_removed")

    graph = api.get("/workflow-templates/", token=root).json()[0]["graph_json"]
    r = api.post("/workflow-templates/", token=root,
                 json={"name": "Kopia", "graph_json": graph})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert api.patch(f"/workflow-templates/{tid}", token=root,
                     json={"name": "Kopia 2"}).status_code == 200
    assert api.delete(f"/workflow-templates/{tid}", token=root).status_code == 204
    for action in ("created", "updated", "deleted"):
        rows = _audit_rows(f"workflow_template.{action}")
        assert rows and rows[-1].target_id == str(tid), action


# ---------------------------------------------------------------------------
# Reset fabryczny
# ---------------------------------------------------------------------------

def _reset_body(password=PW, **kw):
    return {"password": password, "confirm": "RESET", "wipe_requests": False,
            "wipe_structure": False, "wipe_users": False, **kw}


def test_factory_reset_guard(api):
    root = api.setup_superadmin()
    api.mk_user(root, "adm", ["admin"])
    adm = api.login("adm")
    assert api.post("/settings/factory-reset", token=adm,
                    json=_reset_body()).status_code == 403
    assert api.post("/settings/factory-reset", token=root,
                    json={**_reset_body(), "confirm": "reset?"}).status_code == 400

    for _ in range(5):
        r = api.post("/settings/factory-reset", token=root, json=_reset_body("zle-haslo"))
        assert r.status_code == 403
    denied = _security_rows("settings.factory_reset_denied")
    assert len(denied) == 5
    assert denied[-1].severity == SecuritySeverity.critical
    # Limit prób: nawet poprawne hasło jest teraz odrzucane.
    assert api.post("/settings/factory-reset", token=root,
                    json=_reset_body()).status_code == 429


def test_factory_reset_restores_audit_triggers(api):
    root = api.setup_superadmin()
    r = api.post("/settings/factory-reset", token=root, json=_reset_body(wipe_audit=True))
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        names = {row[0] for row in s.exec(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='auditlog'"))}
    assert {"auditlog_no_update", "auditlog_no_delete"} <= names
    assert not _security_rows("audit.triggers_missing")
    assert _audit_rows("settings.factory_reset")


# ---------------------------------------------------------------------------
# SMTP: tylko superadmin, zmiana hosta kasuje hasło
# ---------------------------------------------------------------------------

def _smtp(**kw):
    return {"enabled": True, "smtp_host": "smtp.a.local", "smtp_port": 587,
            "smtp_user": "svc", "from_address": "szup@t.local", "to_address": "",
            "use_tls": True, "sender_as_actor": True, **kw}


def test_smtp_settings_superadmin_only_and_password_cleared(api):
    root = api.setup_superadmin()
    api.mk_user(root, "adm", ["admin"])
    adm = api.login("adm")
    assert api.put("/settings/email", token=adm, json=_smtp()).status_code == 403

    r = api.put("/settings/email", token=root, json=_smtp(smtp_password="Tajne-123"))
    assert r.status_code == 200 and r.json()["has_password"] is True
    # Inne pole bez hasła — hasło zostaje.
    r = api.put("/settings/email", token=root, json=_smtp(smtp_port=25))
    assert r.json()["has_password"] is True and not r.json().get("warning")
    # Nowy host bez hasła — hasło usunięte, komunikat dla admina.
    r = api.put("/settings/email", token=root, json=_smtp(smtp_host="smtp.evil.local"))
    assert r.status_code == 200
    assert r.json()["has_password"] is False and r.json()["warning"]
    # Nowy użytkownik z nowym hasłem — hasło zapisane.
    r = api.put("/settings/email", token=root,
                json=_smtp(smtp_user="inny", smtp_password="Nowe-456"))
    assert r.json()["has_password"] is True and not r.json().get("warning")
    assert _security_rows("settings.email")[-1].severity == SecuritySeverity.high


# ---------------------------------------------------------------------------
# Zdarzenia bezpieczeństwa: admin nie zamyka zdarzeń o sobie
# ---------------------------------------------------------------------------

def test_admin_cannot_resolve_own_security_event(api):
    root = api.setup_superadmin()
    adm_id = api.mk_user(root, "adm", ["admin"])
    adm = api.login("adm")
    with Session(engine) as s:
        own = SecurityEvent(event_type="t.own", summary="o adminie", user_id=adm_id)
        other = SecurityEvent(event_type="t.other", summary="o kimś", user_id=None)
        s.add(own); s.add(other); s.commit()
        own_id, other_id = own.id, other.id
    assert api.post(f"/security/{own_id}/resolve", token=adm, json={}).status_code == 403
    assert api.post(f"/security/{other_id}/resolve", token=adm, json={}).status_code == 200
    assert api.post(f"/security/{own_id}/resolve", token=root, json={}).status_code == 200


# ---------------------------------------------------------------------------
# Audit log: filtry dat ze strefą
# ---------------------------------------------------------------------------

def test_audit_filter_accepts_timezone(api):
    root = api.setup_superadmin()
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    with Session(engine) as s:
        s.add(AuditLog(timestamp=now - timedelta(hours=1), action="t.tz", username="x"))
        s.commit()
    # Godzina temu UTC = (godzina temu + 2 h) w strefie +02:00.
    local = (now - timedelta(hours=1) + timedelta(hours=2)).replace(microsecond=0)
    since_ok = (local - timedelta(minutes=5)).isoformat() + "+02:00"
    since_late = (local + timedelta(minutes=5)).isoformat() + "+02:00"
    rows = api.get("/audit/", token=root, params={"since": since_ok, "action": "t.tz"}).json()
    assert len(rows) == 1
    rows = api.get("/audit/", token=root, params={"since": since_late, "action": "t.tz"}).json()
    assert rows == []
    z = (now - timedelta(hours=2)).replace(microsecond=0).isoformat() + "Z"
    assert len(api.get("/audit/", token=root, params={"since": z, "action": "t.tz"}).json()) == 1
    naive = (now - timedelta(hours=2)).replace(microsecond=0).isoformat()
    assert len(api.get("/audit/", token=root,
                       params={"since": naive, "action": "t.tz"}).json()) == 1


# ---------------------------------------------------------------------------
# Migawki: ręczna nie blokuje nocnej
# ---------------------------------------------------------------------------

def test_nightly_snapshot_replaces_manual(api):
    from services.snapshots import NIGHTLY_GENERATOR, create_snapshot
    with Session(engine) as s:
        manual = create_snapshot(s, generated_by="admin", for_date="2026-10-01")
        assert manual.generated_by == "admin"
        # Druga ręczna bez force — zwraca istniejącą.
        assert create_snapshot(s, generated_by="inny", for_date="2026-10-01").generated_by == "admin"
        nightly = create_snapshot(s, generated_by=NIGHTLY_GENERATOR, for_date="2026-10-01")
        assert nightly.id == manual.id and nightly.generated_by == NIGHTLY_GENERATOR
        # Kolejna ręczna nie nadpisuje nocnej (bez force).
        assert create_snapshot(s, generated_by="admin",
                               for_date="2026-10-01").generated_by == NIGHTLY_GENERATOR


# ---------------------------------------------------------------------------
# LDAP: puste hasło
# ---------------------------------------------------------------------------

def test_authenticate_ldap_rejects_empty_password(monkeypatch):
    from services import ldap_service
    called = []
    import ldap3
    monkeypatch.setattr(ldap3, "Connection", lambda *a, **k: called.append(1))
    cfg = LdapSettings(enabled=True, host="ldap.test", base_dn=_BASE)
    assert ldap_service.authenticate_ldap(cfg, "jan", "") is False
    assert ldap_service.authenticate_ldap(cfg, "jan", None) is False
    assert called == []
