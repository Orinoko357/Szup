"""3.10 — struktura i rejestr (poprawki po audycie 3.9).

1. `services.structure.live_department` — komórka do przypisań (400 dla
   nieistniejącej, zarchiwizowanej, nieaktywnej, id spoza zakresu).
2. Usunięcie komórki przez superadmina: wersja robocza czyszczona przy
   odrzuceniu, powiadomienie kierownika i zastępców, wniosek częściowo
   zrealizowany przez IT zamykany zamiast odrzucany, odpięci pracownicy
   w odpowiedzi, id spoza zakresu, limit długości powodu.
3. Usunięcie posiadanej grupy uprawnień: hasło superadmina, posiadacze bez
   konta, pozycje już nadane przez IT, oznaczenie wniosków systemowych,
   e-maile, rejestr nadanych z oznaczeniem odebranych.
4. Akceptacja wyższa bez osoby uprawnionej — nie blokuje edycji komórki,
   zgłaszana na liście kontrolnej i w dzienniku.
5. Lista kontrolna: komórka kadrowa, osoby bez funkcji kadr po migracji 3.9,
   `blocking` zależne od poziomu.
6. `org_sync.after_department_change` — przeniesienie osoby do innej komórki.
7. Migawka obejmuje konta nieaktywne z uprawnieniami.
8. Migracje: indeksy na zaktualizowanych bazach, ostrzeżenie LDAP tylko przy
   skonfigurowanym LDAP.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine
from models import (
    AccessRequest, AuditLog, Department, RequestItem, RequestStatus, User,
)
from tests.conftest import PW

BIG = 2 ** 63


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _capture_jobs(monkeypatch):
    import services.after_commit as ac
    jobs = []
    monkeypatch.setattr(ac, "_submit", lambda fn, kwargs: jobs.append((fn.__name__, kwargs)))
    return jobs


def _audit(action: str) -> list[AuditLog]:
    with Session(engine) as s:
        return s.exec(select(AuditLog).where(AuditLog.action == action)
                      .order_by(AuditLog.id)).all()


def _set_dept(user_id: int, dept_id) -> None:
    with Session(engine) as s:
        u = s.get(User, user_id); u.department_id = dept_id; s.add(u); s.commit()


def _grant(unit_id, dept_id, sid, pid, *, user_id=None, worker_name="Jan Pracownik") -> int:
    """Zrealizowany wniosek o nadanie (bez obiegu)."""
    now = datetime.utcnow()
    with Session(engine) as s:
        req = AccessRequest(worker_name=worker_name, worker_user_id=user_id,
                            worker_email="zlecenie@t.local" if user_id is None else None,
                            unit_id=unit_id, department_id=dept_id, kind="grant",
                            status=RequestStatus.completed, created_at=now,
                            approved_at=now, completed_at=now)
        s.add(req); s.flush()
        s.add(RequestItem(request_id=req.id, system_id=sid, permission_id=pid,
                          kind="grant", fulfilled=True, fulfilled_at=now))
        s.commit()
        return req.id


def _world(api, two_stage=False):
    """Jednostka U: komórka P (kierownik kierP), pod nią K (kierownik kier,
    zastępca zast, pracownik prac). IT, admin, kadry."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kp = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    zid = api.mk_user(sup, "zast", ["viewer"], "Zenon Zastępca")
    worker = api.mk_user(sup, "prac", ["viewer"], "Piotr Pracownik")
    api.mk_user(sup, "it", ["it_staff"], "Informatyk")
    api.mk_user(sup, "adm", ["admin"], "Administrator")
    api.mk_user(sup, "hr", ["hr"], "Kadrowa", unit_ids=[unit])
    parent = api.mk_department(sup, unit, kp, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    assert api.post(f"/units/departments/{dep}/deputies", token=sup,
                    json={"user_id": zid}).status_code == 201
    _set_dept(worker, dep)
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    p2 = api.post(f"/systems/{sid}/permissions", token=sup,
                  json={"permission_name": "Zapis"}).json()["id"]
    return dict(sup=sup, unit=unit, parent=parent, dep=dep, kp=kp, kid=kid, zid=zid,
                worker=worker, sid=sid, pid=pid, pid2=p2,
                rtype=api.request_type(sup, "NEW_EMP"))


def _hr_request(api, w, items=(), worker_name="Ola Nowa", dept=None):
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": worker_name, "unit_id": w["unit"], "department_id": dept or w["dep"],
        "request_type_id": w["rtype"], "items": list(items)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _force_delete(api, token, dept_id, **body):
    payload = {"reason": "Reorganizacja urzędu", "password": PW, **body}
    return api.post(f"/units/departments/{dept_id}/force-delete", token=token, json=payload)


def _health(api, token):
    body = api.get("/settings/health", token=token).json()
    return ({c["key"]: c for c in body["checks"]}, {i["key"]: i for i in body["issues"]})


# ---------------------------------------------------------------------------
# 1. live_department
# ---------------------------------------------------------------------------

def test_live_department_rejects_missing_archived_inactive(api):
    from services.structure import live_department
    w = _world(api)
    with Session(engine) as s:
        assert live_department(s, w["dep"]).id == w["dep"]
        for bad in (None, 999999, BIG, -BIG - 1):
            with pytest.raises(HTTPException) as e:
                live_department(s, bad)
            assert e.value.status_code == 400 and "nie istnieje" in e.value.detail
        d = s.get(Department, w["dep"]); d.is_active = False; s.add(d); s.commit()
        with pytest.raises(HTTPException) as e:
            live_department(s, w["dep"])
        assert e.value.status_code == 400 and "nieaktywna" in e.value.detail
        d.is_active = True; d.archived_at = datetime.utcnow(); s.add(d); s.commit()
        with pytest.raises(HTTPException) as e:
            live_department(s, w["dep"])
        assert e.value.status_code == 400 and "zlikwidowana" in e.value.detail


# ---------------------------------------------------------------------------
# 2. Usunięcie komórki przez superadmina
# ---------------------------------------------------------------------------

def test_force_delete_clears_draft_and_notifies_department_managers(api, monkeypatch):
    w = _world(api)
    rid = _hr_request(api, w, items=[{"system_id": w["sid"], "permission_id": w["pid"]}])
    kier = api.login("kier")
    r = api.post(f"/requests/{rid}/draft", token=kier, json={
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}], "comment": "TAJNE"})
    assert r.status_code == 200, r.text
    jobs = _capture_jobs(monkeypatch)

    r = _force_delete(api, w["sup"], w["dep"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["rejected_request_ids"] == [rid]
    assert out["detached_user_ids"] == [w["worker"]]
    with Session(engine) as s:
        req = s.get(AccessRequest, rid)
        assert req.status == RequestStatus.rejected
        assert req.manager_comment == "Komórka usunięta: Reorganizacja urzędu"
        assert req.draft_saved_at is None
    # Ani IT, ani administrator nie widzą notatki z wersji roboczej.
    det = api.get(f"/requests/{rid}", token=api.login("it"))
    if det.status_code == 200:
        assert "TAJNE" not in json.dumps(det.json(), ensure_ascii=False)
    to = {kw["requester_email"] for name, kw in jobs if name == "notify_request_rejected"}
    assert {"hr@t.local", "kier@t.local", "zast@t.local"} <= to


def test_force_delete_completes_partially_fulfilled_it_request(api):
    w = _world(api)
    rid = _hr_request(api, w)
    kier = api.login("kier")
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": [
            {"system_id": w["sid"], "permission_id": w["pid"]},
            {"system_id": w["sid"], "permission_id": w["pid2"]}]})
    assert r.status_code == 200, r.text
    assert api.node_type(rid, kier) == "it_execute"
    with Session(engine) as s:
        items = {i.permission_id: i.id for i in s.exec(
            select(RequestItem).where(RequestItem.request_id == rid)).all()}
    it = api.login("it")
    r = api.post(f"/requests/{rid}/items/{items[w['pid']]}/fulfill", token=it,
                 json={"fulfilled": True})
    assert r.status_code == 200, r.text
    # Zwykłe odrzucenie po częściowej realizacji jest zablokowane (409)…
    assert api.post(f"/requests/{rid}/workflow/action", token=it, json={
        "action": "reject", "comment": "nie"}).status_code == 409

    # …a usunięcie komórki go nie obchodzi: wniosek zamknięty, reszta odmówiona.
    r = _force_delete(api, w["sup"], w["dep"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["completed_request_ids"] == [rid] and rid not in out["rejected_request_ids"]
    with Session(engine) as s:
        req = s.get(AccessRequest, rid)
        assert req.status == RequestStatus.completed
        done = s.get(RequestItem, items[w["pid"]])
        rest = s.get(RequestItem, items[w["pid2"]])
        assert done.fulfilled and not done.denied
        assert rest.denied and not rest.fulfilled
        assert "Reorganizacja urzędu" in rest.deny_comment
        from services.workflow import instance_of, verify_chain
        assert verify_chain(s, instance_of(s, req).id)
    reg = api.get("/registry/granted", token=it).json()["items"]
    assert [(x["request_id"], x["permission_name"]) for x in reg if x["request_id"] == rid] \
        == [(rid, "Odczyt")]
    details = json.loads(_audit("department.force_archived")[0].details)
    assert details["completed_request_ids"] == [rid]
    assert details["denied_item_ids"] == {str(rid): [items[w["pid2"]]]}


def test_force_delete_validation_overflow_and_reason_length(api):
    w = _world(api)
    assert _force_delete(api, w["sup"], BIG).status_code == 404
    assert api.patch(f"/units/departments/{BIG}", token=w["sup"],
                     json={"name": "x"}).status_code == 404
    assert api.patch(f"/units/{BIG}", token=w["sup"], json={"name": "x"}).status_code == 404
    assert api.delete(f"/units/{BIG}", token=w["sup"]).status_code == 404
    r = _force_delete(api, w["sup"], w["dep"], reason="x" * 1001)
    assert r.status_code == 400 and "1000" in r.json()["detail"]
    assert _force_delete(api, w["sup"], w["dep"], reason="x" * 1000).status_code == 200


# ---------------------------------------------------------------------------
# 3. Usunięcie posiadanej grupy uprawnień
# ---------------------------------------------------------------------------

def _group_world(api):
    w = _world(api)
    sup = w["sup"]
    s = api.post("/systems/", token=sup,
                 json={"name": "Płace", "access_only": False, "all_units": True})
    gsid = s.json()["id"]
    r = api.post(f"/systems/{gsid}/permissions/import/commit", token=sup, json={
        "group_name": "G",
        "items": [{"permission_name": "Listy płac"}, {"permission_name": "Kartoteki"}]})
    assert r.status_code == 200, r.text
    perms = {p["permission_name"]: p["id"]
             for p in api.get(f"/systems/{gsid}/permissions", token=sup).json()
             if p["group_name"] == "G"}
    return dict(w, gsid=gsid, gp=perms)


def _it_execute(api, rid):
    """IT realizuje (systemowy) wniosek o odebranie z kolejki IT."""
    r = api.post(f"/requests/{rid}/workflow/action", token=api.login("it"),
                 json={"action": "execute"})
    assert r.status_code == 200, r.text
    return r


def _group_delete(api, g, token=None, **body):
    payload = {"group_name": "G", "reason": "Moduł wycofany", "password": PW, **body}
    return api.post(f"/systems/{g['gsid']}/permissions/group-delete",
                    token=token or g["sup"], json=payload)


def test_held_group_delete_requires_superadmin_password(api):
    g = _group_world(api)
    _grant(g["unit"], g["dep"], g["gsid"], g["gp"]["Listy płac"], user_id=g["worker"])
    assert _group_delete(api, g, password=None).status_code == 403
    assert _group_delete(api, g, password="złe").status_code == 403
    assert _group_delete(api, g, reason="x" * 1001).status_code == 400
    eff = api.get(f"/users/{g['worker']}/permissions", token=g["sup"]).json()["permissions"]
    assert [p["permission_name"] for p in eff] == ["Listy płac"]
    r = _group_delete(api, g)
    assert r.status_code == 200, r.text
    # 3.11: odebranie czeka w kolejce IT — do realizacji uprawnienie jest.
    rev = r.json()["revoke_request_ids"]
    assert len(rev) == 1
    assert [p["permission_name"] for p in api.get(
        f"/users/{g['worker']}/permissions", token=g["sup"]).json()["permissions"]] \
        == ["Listy płac"]
    _it_execute(api, rev[0])
    assert api.get(f"/users/{g['worker']}/permissions",
                   token=g["sup"]).json()["permissions"] == []


def test_held_group_delete_covers_holders_without_account(api, monkeypatch):
    g = _group_world(api)
    src = _grant(g["unit"], g["dep"], g["gsid"], g["gp"]["Listy płac"],
                 worker_name="Zleceniobiorca Bez Konta")
    usage = api.get(f"/systems/{g['gsid']}/permissions/group-usage", token=api.login("it"),
                    params={"group_name": "G"}).json()
    assert usage["holders"] == []
    assert usage["unlinked_holders"] == [{"request_id": src,
                                          "worker_name": "Zleceniobiorca Bez Konta",
                                          "permissions": ["Listy płac"]}]
    # Posiadacz bez konta też wymaga superadmina.
    assert _group_delete(api, g, token=api.login("it")).status_code == 403

    jobs = _capture_jobs(monkeypatch)
    r = _group_delete(api, g)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["unlinked_request_ids"] == [src] and len(out["revoke_request_ids"]) == 1
    rev_id = out["revoke_request_ids"][0]
    from services.structure import is_system_request
    with Session(engine) as s:
        rev = s.get(AccessRequest, rev_id)
        assert rev.kind == "revoke" and rev.status == RequestStatus.pending_it
        assert rev.worker_user_id is None and rev.worker_name == "Zleceniobiorca Bez Konta"
        assert is_system_request(rev)
        assert not is_system_request(s.get(AccessRequest, src))
        granted = s.exec(select(RequestItem).where(RequestItem.request_id == src)).one()
        assert granted.revoked_by_request_id == rev_id
    # Do realizacji przez IT rejestr pokazuje uprawnienie jako posiadane.
    row = next(x for x in api.get("/registry/granted", token=api.login("it")).json()["items"]
               if x["request_id"] == src)
    assert row["revoked"] is False
    # IT i helpdesk dostają zadanie.
    assert any(name == "notify_helpdesk_new_request" and kw["request_id"] == rev_id
               for name, kw in jobs)
    _it_execute(api, rev_id)
    reg = api.get("/registry/granted", token=api.login("it")).json()["items"]
    row = next(x for x in reg if x["request_id"] == src)
    assert row["revoked"] is True and row["revoked_by_request_id"] == rev_id
    assert not [x for x in api.get("/registry/granted", token=api.login("it"),
                                   params={"only_effective": True}).json()["items"]
                if x["request_id"] == src]
    csv = api.get("/registry/granted.csv", token=api.login("it")).text
    assert "Odebrano" in csv and f"wniosek #{rev_id}" in csv
    mails = [kw for name, kw in jobs if name == "_send_group_revoked_mail"]
    to = {m["to_address"] for m in mails}
    # Osoba bez konta (adres z wniosku) i kierownik oraz zastępca jej komórki.
    assert {"zlecenie@t.local", "kier@t.local", "zast@t.local"} <= to
    assert all("Zleceniobiorca Bez Konta" in m["body"] for m in mails)
    # Drugi raz nie ma już czego odbierać (grupa usunięta).
    assert _group_delete(api, g).status_code == 404


def test_held_group_delete_moves_fulfilled_in_progress_items_to_revoke(api, monkeypatch):
    g = _group_world(api)
    _grant(g["unit"], g["dep"], g["gsid"], g["gp"]["Kartoteki"], user_id=g["worker"])
    rid = _hr_request(api, g, worker_name="Grażyna Nowa")
    kier = api.login("kier")
    assert api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select", "items": [
            {"system_id": g["gsid"], "permission_id": g["gp"]["Listy płac"]},
            {"system_id": g["sid"], "permission_id": g["pid"]}]}).status_code == 200
    with Session(engine) as s:
        item = s.exec(select(RequestItem).where(RequestItem.request_id == rid)
                      .where(RequestItem.permission_id == g["gp"]["Listy płac"])).one()
    it = api.login("it")
    assert api.post(f"/requests/{rid}/items/{item.id}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 200

    jobs = _capture_jobs(monkeypatch)
    r = _group_delete(api, g)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["affected_user_ids"] == [g["worker"]]
    assert out["revoked_in_progress_item_ids"] == [item.id]
    assert out["updated_request_ids"] == [rid]
    assert len(out["revoke_request_ids"]) == 2
    with Session(engine) as s:
        x = s.get(RequestItem, item.id)
        assert x.denied and not x.fulfilled and x.revoked_by_request_id
        assert x.fulfilled_at is not None          # ślad realizacji IT zostaje
        rev = s.get(AccessRequest, x.revoked_by_request_id)
        assert rev.worker_name == "Grażyna Nowa" and rev.worker_user_id is None
        assert (rev.manager_comment or "").startswith("[SYSTEM] ")
        rev_items = s.exec(select(RequestItem).where(RequestItem.request_id == rev.id)).all()
        assert [(i.permission_id, i.kind) for i in rev_items] == \
            [(g["gp"]["Listy płac"], "revoke")]
    # Dokończenie realizacji nie przywraca uprawnienia z usuniętej grupy —
    # nadaje tylko pozostałą pozycję (Odczyt), Kartoteki prac traci dopiero
    # po realizacji przez IT systemowego wniosku o odebranie.
    with Session(engine) as s:
        hold_rev = s.exec(select(AccessRequest).where(AccessRequest.worker_user_id == g["worker"])
                          .where(AccessRequest.kind == "revoke")).one()
        assert hold_rev.status == RequestStatus.pending_it
        hold_rev_id = hold_rev.id
        req = s.get(AccessRequest, rid); req.worker_user_id = g["worker"]; s.add(req); s.commit()
    r = api.post(f"/requests/{rid}/workflow/action", token=it, json={"action": "execute"})
    assert r.status_code == 200, r.text

    def _eff():
        return sorted(p["permission_name"] for p in api.get(
            f"/users/{g['worker']}/permissions", token=g["sup"]).json()["permissions"])
    assert _eff() == ["Kartoteki", "Odczyt"]
    _it_execute(api, hold_rev_id)
    assert _eff() == ["Odczyt"]
    mails = {kw["to_address"] for name, kw in jobs if name == "_send_group_revoked_mail"}
    assert {"prac@t.local", "kier@t.local"} <= mails
    entry = json.loads(_audit("permission_group.deleted")[0].details)
    assert entry["revoked_in_progress_item_ids"] == [item.id]


def test_registry_marks_revocations_of_linked_workers(api):
    g = _group_world(api)
    src = _grant(g["unit"], g["dep"], g["sid"], g["pid"], user_id=g["worker"])
    now = datetime.utcnow()
    with Session(engine) as s:
        rev = AccessRequest(worker_name="Piotr Pracownik", worker_user_id=g["worker"],
                            unit_id=g["unit"], department_id=g["dep"], kind="revoke",
                            status=RequestStatus.completed, created_at=now,
                            approved_at=now, completed_at=now)
        s.add(rev); s.flush()
        s.add(RequestItem(request_id=rev.id, system_id=g["sid"], permission_id=g["pid"],
                          kind="revoke", fulfilled=True))
        s.commit()
        rev_id = rev.id
    row = next(x for x in api.get("/registry/granted", token=api.login("it")).json()["items"]
               if x["request_id"] == src)
    assert row["revoked"] is True and row["revoked_by_request_id"] == rev_id


# ---------------------------------------------------------------------------
# 4. Akceptacja wyższa bez osoby uprawnionej
# ---------------------------------------------------------------------------

def test_higher_approval_orphan_reported_not_blocking(api):
    w = _world(api, two_stage=True)
    sup = w["sup"]
    checks, _ = _health(api, sup)
    assert checks["higher_approval"]["ok"] is True

    # Rodzic traci kierownika — dziecko z akceptacją wyższą nie ma już nikogo.
    assert api.patch(f"/units/departments/{w['parent']}", token=sup,
                     json={"manager_user_id": None}).status_code == 200
    # Edycja dziecka (np. nazwy) nadal działa — także z pełnym formularzem.
    r = api.patch(f"/units/departments/{w['dep']}", token=sup,
                  json={"name": "K-nowa", "requires_higher_approval": True})
    assert r.status_code == 200, r.text
    checks, _ = _health(api, sup)
    c = checks["higher_approval"]
    assert c["ok"] is False and c["level"] == "required" and c["blocking"] is True
    assert c["label"] == "Akceptacja wyższa bez osoby uprawnionej"
    assert c["departments"] == [{"id": w["dep"], "name": "K-nowa"}]
    entry = _audit("department.higher_approval_unreachable")
    assert entry and json.loads(entry[0].details)["department_ids"] == [w["dep"]]

    # Włączenie akceptacji wyższej tam, gdzie nikt jej nie wykona — 400.
    other = api.mk_department(sup, w["unit"], None, name="Inna", parent_dept_id=w["parent"])
    r = api.patch(f"/units/departments/{other}", token=sup,
                  json={"requires_higher_approval": True})
    assert r.status_code == 400 and "akceptacji wyższego rzędu" in r.json()["detail"]

    # Dyrektor jednostki może ją wykonać — problem znika, a włączenie działa.
    did = api.mk_user(sup, "dyr", ["manager"], "Dyrektor")
    assert api.patch(f"/units/{w['unit']}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    assert _health(api, sup)[0]["higher_approval"]["ok"] is True
    assert api.patch(f"/units/departments/{other}", token=sup,
                     json={"requires_higher_approval": True}).status_code == 200
    # Komórka najwyższego poziomu z dyrektorem jednostki — dozwolona.
    assert api.post("/units/departments", token=sup, json={
        "unit_id": w["unit"], "name": "Top", "requires_higher_approval": True}
    ).status_code == 201


def test_same_person_managing_child_and_parent_is_orphan(api):
    w = _world(api, two_stage=True)
    sup = w["sup"]
    assert api.patch(f"/units/departments/{w['parent']}", token=sup,
                     json={"manager_user_id": w["kid"]}).status_code == 200
    c = _health(api, sup)[0]["higher_approval"]
    assert c["ok"] is False and [d["id"] for d in c["departments"]] == [w["dep"]]


def test_force_delete_parent_reports_orphaned_child(api):
    w = _world(api, two_stage=True)
    sup = w["sup"]
    # P jest na najwyższym poziomie: po jego usunięciu K nie ma rodzica ani dyrektora.
    r = _force_delete(api, sup, w["parent"])
    assert r.status_code == 200, r.text
    assert r.json()["higher_approval_unreachable_ids"] == [w["dep"]]
    with Session(engine) as s:
        assert s.get(Department, w["dep"]).requires_higher_approval is True
    assert api.patch(f"/units/departments/{w['dep']}", token=sup,
                     json={"description": "opis"}).status_code == 200
    assert _health(api, sup)[0]["higher_approval"]["ok"] is False


# ---------------------------------------------------------------------------
# 5. Lista kontrolna
# ---------------------------------------------------------------------------

def test_health_hr_department_check(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    checks, _ = _health(api, sup)
    c = checks["hr_department"]
    assert c["ok"] is False and c["level"] == "required" and c["link"] == "/units"
    hid = api.mk_user(sup, "kadry", ["hr"], "Kadrowa", unit_ids=[unit])
    assert _health(api, sup)[0]["hr_department"]["ok"] is True
    # Komórka kadrowa bez aktywnego pracownika — znowu błąd.
    with Session(engine) as s:
        u = s.get(User, hid); u.is_active = False; s.add(u); s.commit()
    c = _health(api, sup)[0]["hr_department"]
    assert c["ok"] is False and "aktywnych pracowników" in c["detail"]


def test_health_warning_level_is_not_blocking(api):
    sup = api.setup_superadmin()
    checks, _ = _health(api, sup)
    assert checks["superadmin_operational"]["level"] == "warning"
    assert checks["superadmin_operational"]["blocking"] is False
    assert checks["ldap"]["blocking"] is True


def test_health_lists_people_who_lost_hr_capability(api):
    from services.audit import record_event
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    old = api.mk_user(sup, "dawnahr", ["viewer"], "Dawna Kadrowa")
    api.mk_user(sup, "inna", ["viewer"], "Inna")
    with Session(engine) as s:
        record_event(s, action="user.hr_role_removed", target_type="user",
                     username="system", details={
                         "usernames": ["dawnahr", "inna", "zniknal"],
                         "lost_hr_capability": ["dawnahr", "zniknal"]})
    issue = _health(api, sup)[1]["hr_capability_lost"]
    assert issue["count"] == 1 and issue["usernames"] == ["dawnahr"]
    assert issue["link"] == "/units" and "dawnahr" in issue["detail"]
    # Po przeniesieniu do komórki kadrowej pozycja znika.
    hr_dept = api.hr_department(unit)
    _set_dept(old, hr_dept)
    assert _health(api, sup)[1]["hr_capability_lost"]["count"] == 0


# ---------------------------------------------------------------------------
# 6. Przeniesienie osoby do innej komórki
# ---------------------------------------------------------------------------

def test_after_department_change_releases_old_post_and_adopts_vacant(api):
    from services.org_sync import after_department_change
    w = _world(api)
    sup = w["sup"]
    vacant = api.mk_department(sup, w["unit"], None, name="Wolna")
    with Session(engine) as s:
        u = s.get(User, w["kid"]); old = u.department_id; u.department_id = vacant
        s.add(u); s.flush()
        res = after_department_change(s, u, w["dep"])
        s.commit()
        assert res["released_dept_ids"] == [w["dep"]] and res["adopted"] is True
        assert s.get(Department, w["dep"]).manager_user_id is None
        assert s.get(Department, vacant).manager_user_id == w["kid"]
        assert "manager" in json.loads(s.get(User, w["kid"]).roles)
        assert old is None or old != vacant


def test_after_department_change_to_staffed_department_drops_role(api):
    from services.org_sync import after_department_change
    w = _world(api)
    with Session(engine) as s:
        u = s.get(User, w["kid"]); u.department_id = w["parent"]; s.add(u); s.flush()
        res = after_department_change(s, u, w["dep"])
        s.commit()
        assert res["released_dept_ids"] == [w["dep"]] and res["adopted"] is False
        assert res["warning"] and "ma już kierownika" in res["warning"]
        assert res["role_revoked"] is True
        assert "manager" not in json.loads(s.get(User, w["kid"]).roles)
        assert s.get(Department, w["parent"]).manager_user_id == w["kp"]
        # Zastępca przeniesiony gdzie indziej przestaje być zastępcą.
        z = s.get(User, w["zid"]); z.department_id = w["parent"]; s.add(z); s.flush()
        res = after_department_change(s, z, w["dep"])
        s.commit()
        assert res["released_dept_ids"] == [w["dep"]]
    assert api.get(f"/units/departments/{w['dep']}/deputies",
                   token=w["sup"]).json() == []


# ---------------------------------------------------------------------------
# 7. Migawka — konta nieaktywne z uprawnieniami
# ---------------------------------------------------------------------------

def test_snapshot_includes_inactive_accounts_with_permissions(api):
    w = _world(api)
    _grant(w["unit"], w["dep"], w["sid"], w["pid"], user_id=w["worker"])
    with Session(engine) as s:
        u = s.get(User, w["worker"]); u.is_active = False; s.add(u); s.commit()
    snap = api.post("/snapshots/run", token=api.login("adm"), params={"force": True})
    assert snap.status_code == 200, snap.text
    date = snap.json()["snapshot_date"]
    rows = api.get(f"/snapshots/{date}", token=api.login("it")).json()["rows"]
    mine = [r for r in rows if r["username"] == "prac"]
    assert [(r["permission_name"], r["account_active"]) for r in mine] == [("Odczyt", False)]
    csv = api.get(f"/snapshots/{date}.csv", token=api.login("it")).text
    assert "nieaktywne" in csv


# ---------------------------------------------------------------------------
# 8. Migracje
# ---------------------------------------------------------------------------

def _indexes() -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index'"))}


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_migrations_create_indexes_on_upgraded_db(api):
    from database import _run_migrations
    names = ("ix_department_archived_at", "ix_systempermission_deleted_at",
             "ix_requestitem_revoked_by_request_id")
    with engine.connect() as conn:
        for n in names:
            conn.execute(text(f"DROP INDEX IF EXISTS {n}"))
        conn.commit()
    assert not set(names) & _indexes()
    _run_migrations()
    assert set(names) <= _indexes()


@pytest.mark.parametrize("with_row", [False, True])
def test_ldap_tls_warning_only_with_configured_ldap(api, with_row):
    from database import _run_migrations
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM ldapsettings"))
        conn.execute(text("ALTER TABLE ldapsettings DROP COLUMN tls_verify"))
        if with_row:
            conn.execute(text(
                "INSERT INTO ldapsettings (enabled, host, port, use_ssl, base_dn, bind_dn, "
                "user_search_base, user_filter, sso_enabled, sso_auto, use_starttls, "
                "allow_insecure) VALUES (1, 'dc.local', 389, 0, '', '', '', "
                "'(sAMAccountName={username})', 0, 0, 0, 0)"))
        conn.commit()
    handler = _Collect()
    log = logging.getLogger("szup.migrations")
    log.addHandler(handler)
    try:
        _run_migrations()
    finally:
        log.removeHandler(handler)
    warned = any("weryfikacja certyfikatu" in m for m in handler.messages)
    assert warned is with_row


def test_hr_flag_change_emits_security_event(api):
    from models import SecurityEvent
    from sqlmodel import Session, select
    from database import engine
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "UH", "UH")
    api.mk_user(sup, "adm", ["admin"])
    adm = api.login("adm")
    r = api.post("/units/departments", token=adm, json={
        "unit_id": unit, "name": "Kadry X", "kind": "department", "is_hr": True})
    assert r.status_code in (200, 201), r.text
    dep = r.json()["id"]
    assert api.patch(f"/units/departments/{dep}", token=adm, json={"is_hr": False}).status_code == 200
    with Session(engine) as s:
        evs = s.exec(select(SecurityEvent).where(
            SecurityEvent.event_type == "department.hr_flag_changed")).all()
    assert len(evs) == 2
