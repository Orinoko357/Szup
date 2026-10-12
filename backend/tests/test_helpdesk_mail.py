"""E2E: zgłoszenie na helpdesk, gdy wniosek trafia do realizacji IT."""
from __future__ import annotations

import services.email_alerts as mail


def _capture(monkeypatch):
    """Przechwyć wysyłkę maili zamiast łączyć się z SMTP."""
    sent = []
    monkeypatch.setattr(mail, "_send",
                        lambda to_address, subject, body: sent.append(
                            {"to": to_address, "subject": subject, "body": body}))
    return sent


def _flow(api):
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Agata Młot", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    return dict(sup=sup, rid=rid, sid=sid, pid=pid, kier=api.login("kier"))


def test_helpdesk_mail_on_it_stage(api, monkeypatch):
    sent = _capture(monkeypatch)
    w = _flow(api)

    # kierownik wybiera uprawnienia → wniosek wchodzi w krok realizacji IT
    r = api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    assert r.status_code == 200, r.text

    import time
    time.sleep(0.4)   # wysyłka leci w wątku w tle

    hd = [m for m in sent if m["to"] == "helpdesk@wodzislaw-slaski.pl"]
    assert len(hd) == 1, f"oczekiwano 1 maila na helpdesk, jest {len(hd)}"
    m = hd[0]
    assert m["subject"] == "Nowy wniosek o nadanie uprawnień"
    assert "Jan Kierownik wystąpił z wnioskiem o nadanie uprawnień dla Agata Młot" in m["body"]
    assert "https://szup.intranet.wods.pl" in m["body"]


def test_no_helpdesk_mail_before_it_stage(api, monkeypatch):
    """Sam fakt złożenia wniosku (krok kierownika) nie zgłasza helpdesku."""
    sent = _capture(monkeypatch)
    _flow(api)
    import time
    time.sleep(0.3)
    assert not [m for m in sent if m["to"] == "helpdesk@wodzislaw-slaski.pl"]


def test_only_helpdesk_on_it_stage_no_individual_it_mails(api, monkeypatch):
    """Do realizacji IT leci TYLKO helpdesk — bez imiennych maili do IT."""
    sent = _capture(monkeypatch)
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    # pracownik IT Z ADRESEM e-mail — nie powinien dostać powiadomienia
    api.mk_user(sup, "it", ["it_staff"], "Iga IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Agata Młot", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]

    sent.clear()   # pomiń mail do kierownika o kroku „wybór uprawnień"
    api.post(f"/requests/{rid}/workflow/action", token=api.login("kier"), json={
        "action": "select",
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}]})
    import time; time.sleep(0.4)

    assert [m["to"] for m in sent] == ["helpdesk@wodzislaw-slaski.pl"], \
        f"oczekiwano wyłącznie maila na helpdesk, wysłano: {[m['to'] for m in sent]}"


def test_helpdesk_address_configurable_in_settings(api, monkeypatch):
    """Adres helpdesku z Ustawień nadpisuje domyślny."""
    sent = _capture(monkeypatch)
    w = _flow(api)
    r = api.put("/settings/app", token=w["sup"], json={
        "test_mode": False, "helpdesk_email": "serwis@example.org"})
    assert r.status_code == 200, r.text
    assert r.json()["helpdesk_email_effective"] == "serwis@example.org"

    sent.clear()   # pomiń mail do kierownika o kroku „wybór uprawnień"
    api.post(f"/requests/{w['rid']}/workflow/action", token=w["kier"], json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": w["pid"], "kind": "grant"}]})
    import time; time.sleep(0.4)
    assert [m["to"] for m in sent] == ["serwis@example.org"]


def test_completed_mail_goes_to_selecting_manager(api, monkeypatch):
    """Wniosek zrealizowany → mail do KIEROWNIKA, który wybierał uprawnienia
    (nie do kadrowej, która tylko zgłosiła zatrudnienie)."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kierownik")
    api.mk_user(sup, "it", ["it_staff"], "Iga IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    # adresy e-mail: kier@t.local / hr@t.local (nadawane przez mk_user)
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup)
    rtype = api.request_type(sup, "NEW_EMP")
    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Agata Młot", "unit_id": unit, "department_id": dep,
        "items": [], "request_type_id": rtype}).json()["id"]
    api.post(f"/requests/{rid}/workflow/action", token=api.login("kier"), json={
        "action": "select",
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}]})

    sent = _capture(monkeypatch)   # licz dopiero maile z etapu realizacji
    api.post(f"/requests/{rid}/workflow/action", token=api.login("it"),
             json={"action": "execute", "ad_username": "amlot"})
    import time; time.sleep(0.4)

    done = [m for m in sent if "zrealizowany" in m["subject"]]
    assert len(done) == 1, f"maile: {[(m['to'], m['subject']) for m in sent]}"
    assert done[0]["to"] == "kier@t.local", done[0]["to"]
