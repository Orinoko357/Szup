"""E2E: odmowa i realizacja pojedynczych pozycji (porządki 3.5).

`POST /requests/{id}/items/{item_id}/deny` i `/fulfill` — częściowa (etapowa)
realizacja przez IT, odmowa przy akceptacji wyższej i w IT, statusy pozycji
i wniosku po zamknięciu realizacji oraz odmowy przekazane w akcji obiegu."""
from __future__ import annotations

from sqlmodel import Session, select

from database import engine
from models import RequestItem


def _world(api, two_stage=False):
    """Jednostka U: komórka P (kierownik `kierP`), pod nią K (kierownik `kier`;
    opcjonalnie z akceptacją wyższą). Dwóch pracowników IT, HR. System z trzema
    uprawnieniami."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    api.mk_user(sup, "it", ["it_staff"], "Ida IT")
    api.mk_user(sup, "it2", ["it_staff"], "Igor IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    sid, p1 = api.mk_system_perm(sup, "FK", "Odczyt")
    perms = [p1]
    for name in ("Zapis", "Admin modułu"):
        r = api.post(f"/systems/{sid}/permissions", token=sup, json={"permission_name": name})
        assert r.status_code in (200, 201), r.text
        perms.append(r.json()["id"])
    return dict(sup=sup, unit=unit, dep=dep, sid=sid, perms=perms,
                rtype=api.request_type(sup, "NEW_EMP"))


def _create(api, w, token, kind_per_item=None):
    items = [{"system_id": w["sid"], "permission_id": p,
              **({"kind": kind_per_item[i]} if kind_per_item else {})}
             for i, p in enumerate(w["perms"])]
    r = api.post("/requests/", token=token, json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": items})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _items(api, rid, token):
    return {x["permission_id"]: x for x in
            api.get(f"/requests/{rid}", token=token).json()["items"]}


def _item_ids(api, rid, token):
    return [x["id"] for x in api.get(f"/requests/{rid}", token=token).json()["items"]]


# ---------------------------------------------------------------------------
# Realizacja etapowa przez IT
# ---------------------------------------------------------------------------

def test_partial_it_realization_then_execute_closes_remaining(api):
    w = _world(api)
    rid = _create(api, w, api.login("kier"))
    it, it2 = api.login("it"), api.login("it2")
    assert api.node_type(rid, it) == "it_execute"
    a, b, c = _item_ids(api, rid, it)

    # Odhaczenie jednej pozycji — zapis od razu, wniosek dalej w realizacji.
    r = api.post(f"/requests/{rid}/items/{a}/fulfill", token=it, json={"fulfilled": True})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["fulfilled"] is True
    assert r.json()["item"]["fulfilled_by_name"] == "Ida IT"
    det = api.get(f"/requests/{rid}", token=it).json()
    assert det["status"] == "pending_it" and det["current_node_type"] == "it_execute"

    # Cofnięcie i ponowne odhaczenie.
    r = api.post(f"/requests/{rid}/items/{a}/fulfill", token=it, json={"fulfilled": False})
    assert r.json()["item"]["fulfilled"] is False
    assert r.json()["item"]["fulfilled_by_name"] is None
    assert api.post(f"/requests/{rid}/items/{a}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 200

    # Odmowa drugiej pozycji; odmówionej nie da się odhaczyć.
    r = api.post(f"/requests/{rid}/items/{b}/deny", token=it,
                 json={"denied": True, "comment": "  brak licencji "})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["denied"] is True
    assert r.json()["item"]["deny_comment"] == "brak licencji"
    assert r.json()["item"]["denied_by_name"] == "Ida IT"
    assert api.post(f"/requests/{rid}/items/{b}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 400

    # Zamknięcie realizacji przez innego pracownika IT: reszta pozycji nadania
    # zostaje odhaczona przez niego, wcześniej odhaczona zachowuje realizatora.
    r = api.post(f"/requests/{rid}/workflow/action", token=it2, json={"action": "execute"})
    assert r.status_code == 200, r.text
    det = api.get(f"/requests/{rid}", token=it2).json()
    assert det["status"] == "completed" and det["current_node_type"] is None
    by_id = {x["id"]: x for x in det["items"]}
    assert by_id[a]["fulfilled"] is True and by_id[a]["fulfilled_by_name"] == "Ida IT"
    assert by_id[b]["denied"] is True and by_id[b]["fulfilled"] is False
    assert by_id[c]["fulfilled"] is True and by_id[c]["fulfilled_by_name"] == "Igor IT"

    # Po zakończeniu obiegu pozycji nie da się już zmieniać.
    assert api.post(f"/requests/{rid}/items/{c}/fulfill", token=it,
                    json={"fulfilled": False}).status_code == 409
    assert api.post(f"/requests/{rid}/items/{c}/deny", token=it,
                    json={"denied": True}).status_code == 409


def test_denial_clears_fulfilment_and_revoking_denial_clears_metadata(api):
    w = _world(api)
    rid = _create(api, w, api.login("kier"))
    it = api.login("it")
    a = _item_ids(api, rid, it)[0]
    assert api.post(f"/requests/{rid}/items/{a}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 200
    item = api.post(f"/requests/{rid}/items/{a}/deny", token=it, json={}).json()["item"]
    # Odmowa i „zrealizowano” wykluczają się.
    assert item["denied"] is True and item["fulfilled"] is False
    assert item["fulfilled_by_name"] is None and item["deny_comment"] is None
    item = api.post(f"/requests/{rid}/items/{a}/deny", token=it,
                    json={"denied": False, "comment": "ignorowany"}).json()["item"]
    assert item["denied"] is False and item["deny_comment"] is None
    assert item["denied_by_name"] is None and item["denied_at"] is None


def test_item_endpoints_enforce_node_actor_and_ownership(api):
    w = _world(api, two_stage=True)
    kier, kierP, it = api.login("kier"), api.login("kierP"), api.login("it")
    rid = _create(api, w, kier)
    assert api.node_type(rid, kier) == "higher_manager_approve"
    a = _item_ids(api, rid, kier)[0]

    # Odhaczanie realizacji — tylko na etapie IT.
    assert api.post(f"/requests/{rid}/items/{a}/fulfill", token=kierP,
                    json={"fulfilled": True}).status_code == 400
    # Odmowa na akceptacji wyższej: kierownik komórki i IT nie działają na tym kroku.
    assert api.post(f"/requests/{rid}/items/{a}/deny", token=kier, json={}).status_code == 403
    assert api.post(f"/requests/{rid}/items/{a}/deny", token=it, json={}).status_code == 403

    # Pozycja z innego wniosku → 404; nieistniejący wniosek → 404.
    other = _create(api, w, kier)
    foreign = _item_ids(api, other, kier)[0]
    assert api.post(f"/requests/{rid}/items/{foreign}/deny", token=kierP,
                    json={}).status_code == 404
    assert api.post(f"/requests/999999/items/{a}/deny", token=kierP, json={}).status_code == 404

    # Na kroku wyboru (wniosek od kadr) odmowa pozycji niedozwolona.
    hr_req = _create(api, w, api.login("hr"))
    assert api.node_type(hr_req, kier) == "select_permissions"
    x = _item_ids(api, hr_req, kier)[0]
    assert api.post(f"/requests/{hr_req}/items/{x}/deny", token=kier, json={}).status_code == 400


def test_revoke_items_cannot_be_denied(api):
    w = _world(api)
    # Wniosek o zmianę: część pozycji odbiera — tych nie da się „odmówić”.
    worker = api.mk_user(w["sup"], "ola", ["viewer"], "Ola Nowa")
    with Session(engine) as s:
        from models import User
        u = s.get(User, worker)
        u.department_id = w["dep"]
        s.add(u); s.commit()
    items = [{"system_id": w["sid"], "permission_id": w["perms"][0], "kind": "grant"},
             {"system_id": w["sid"], "permission_id": w["perms"][1], "kind": "revoke"}]
    r = api.post("/requests/", token=api.login("kier"), json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "kind": "change", "worker_user_id": worker,
        "items": items})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    it = api.login("it")
    by_perm = _items(api, rid, it)
    revoke_id = by_perm[w["perms"][1]]["id"]
    assert by_perm[w["perms"][1]]["kind"] == "revoke"
    assert api.post(f"/requests/{rid}/items/{revoke_id}/deny", token=it,
                    json={}).status_code == 400
    # Zamknięcie realizacji odhacza tylko pozycje NADANIA.
    assert api.post(f"/requests/{rid}/workflow/action", token=it,
                    json={"action": "execute"}).status_code == 200
    by_perm = _items(api, rid, it)
    assert by_perm[w["perms"][0]]["fulfilled"] is True
    assert by_perm[w["perms"][1]]["fulfilled"] is False


# ---------------------------------------------------------------------------
# Odmowy w akcji obiegu: akceptacja wyższa i IT
# ---------------------------------------------------------------------------

def test_denials_at_higher_approval_and_it_through_workflow_action(api):
    w = _world(api, two_stage=True)
    kier, kierP, it = api.login("kier"), api.login("kierP"), api.login("it")
    rid = _create(api, w, kier)
    a, b, c = _item_ids(api, rid, kierP)

    # Odmowa od ręki na akceptacji wyższej (kierownik nadrzędny).
    r = api.post(f"/requests/{rid}/items/{a}/deny", token=kierP,
                 json={"denied": True, "comment": "zbędne"})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["denied_by_name"] == "Anna Przełożona"

    # Pozycja spoza wniosku w `denials` → 400, nic się nie zmienia.
    other = _create(api, w, kier)
    foreign = _item_ids(api, other, kier)[0]
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "approve", "denials": [{"item_id": foreign}]})
    assert r.status_code == 400
    assert api.node_type(rid, kierP) == "higher_manager_approve"

    # Akceptacja z odmową kolejnej pozycji → realizacja IT.
    r = api.post(f"/requests/{rid}/workflow/action", token=kierP, json={
        "action": "approve", "denials": [{"item_id": b, "comment": "nadmiarowe"}]})
    assert r.status_code == 200, r.text
    det = api.get(f"/requests/{rid}", token=it).json()
    assert det["status"] == "pending_it"
    by_id = {x["id"]: x for x in det["items"]}
    assert by_id[a]["denied"] and by_id[b]["denied"] and not by_id[c]["denied"]
    assert by_id[b]["deny_comment"] == "nadmiarowe"
    assert by_id[b]["denied_by_name"] == "Anna Przełożona"

    # IT: odmowy dozwolone tylko przy „execute” (approve na it_execute → 400).
    assert api.post(f"/requests/{rid}/workflow/action", token=it, json={
        "action": "approve", "denials": [{"item_id": c}]}).status_code == 400
    # IT odhacza ostatnią pozycję, potem jednak jej odmawia przy zamknięciu.
    assert api.post(f"/requests/{rid}/items/{c}/fulfill", token=it,
                    json={"fulfilled": True}).status_code == 200
    r = api.post(f"/requests/{rid}/workflow/action", token=it, json={
        "action": "execute", "denials": [{"item_id": c, "comment": "konflikt ról"}]})
    assert r.status_code == 200, r.text

    det = api.get(f"/requests/{rid}", token=it).json()
    assert det["status"] == "completed"
    with Session(engine) as s:
        rows = s.exec(select(RequestItem).where(RequestItem.request_id == rid)).all()
        assert all(x.denied for x in rows)
        # Odmowa wyklucza „zrealizowano” — także dla pozycji odhaczonej wcześniej.
        assert not any(x.fulfilled for x in rows)
        assert next(x for x in rows if x.id == c).deny_comment == "konflikt ról"


def test_denials_rejected_on_select_step(api):
    w = _world(api)
    kier = api.login("kier")
    rid = _create(api, w, api.login("hr"))
    assert api.node_type(rid, kier) == "select_permissions"
    a = _item_ids(api, rid, kier)[0]
    r = api.post(f"/requests/{rid}/workflow/action", token=kier, json={
        "action": "select",
        "items": [{"system_id": w["sid"], "permission_id": p} for p in w["perms"]],
        "denials": [{"item_id": a}]})
    assert r.status_code == 400
    assert api.node_type(rid, kier) == "select_permissions"
