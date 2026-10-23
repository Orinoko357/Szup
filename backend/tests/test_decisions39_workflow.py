"""E2E: decyzje właściciela produktu 3.9 — obieg wniosków.

- superadmin to konto konfiguracyjne (break-glass): wnioski widzi, ale w obiegu
  nie działa (wybór / akceptacja / realizacja / przejęcie / oddanie → 403);
  jedyny wyjątek — akceptacja wyższa wniosku „dla siebie” dyrektora jednostki,
  nad którym nie ma nikogo,
- automatyczna akceptacja wyższa: krok kierownika wysłany przez osobę, która sama
  może wykonać akceptację wyższą (przełożony po przejęciu, przełożony składający
  wniosek), zalicza też akceptację wyższą — wniosek trafia od razu do IT,
- nigdy dla wniosku „dla siebie” ani dla kierownika samej komórki,
- `next_node_type` odzwierciedla automatyczną akceptację,
- dowiązanie konta pracownika — tylko IT."""
from __future__ import annotations

from sqlmodel import Session, select

from database import engine
from models import User, WorkflowInstance, WorkflowStep
from services.workflow import AUTO_HIGHER_COMMENT


def _world(api, two_stage=True):
    """Jednostka U: komórka P (kierownik `kierP`), pod nią K (kierownik `kier`,
    dwustopniowa). Dyrektor jednostki `dyr`, IT, kadry."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    pid_user = api.mk_user(sup, "kierP", ["manager"], "Anna Przełożona")
    did = api.mk_user(sup, "dyr", ["manager"], "Dorota Dyrektor")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    parent = api.mk_department(sup, unit, pid_user, name="P")
    dep = api.mk_department(sup, unit, kid, name="K", parent_dept_id=parent,
                            requires_higher_approval=two_stage)
    assert api.patch(f"/units/{unit}", token=sup,
                     json={"manager_user_id": did}).status_code == 200
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, parent=parent, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"), kid=kid,
                pid_user=pid_user, did=did)


def _items(w):
    return [{"system_id": w["sid"], "permission_id": w["pid"]}]


def _create(api, w, token, dep=None, items=True, **extra):
    body = {"worker_name": "Ola Nowa", "unit_id": w["unit"],
            "department_id": dep or w["dep"], "request_type_id": w["rtype"], **extra}
    if items:
        body["items"] = _items(w)
    r = api.post("/requests/", token=token, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _det(api, rid, token):
    r = api.get(f"/requests/{rid}", token=token)
    assert r.status_code == 200, r.text
    return r.json()


def _act(api, rid, token, action, **extra):
    body = {"action": action, **extra}
    if action == "select" and "items" not in extra:
        body["items"] = []
        body["allow_empty"] = True
    return api.post(f"/requests/{rid}/workflow/action", token=token, json=body)


def _steps(rid):
    with Session(engine) as s:
        inst = s.exec(select(WorkflowInstance).where(WorkflowInstance.request_id == rid)).one()
        return [(st.node_type, st.action.value, st.actor_name, st.comment)
                for st in s.exec(select(WorkflowStep)
                                 .where(WorkflowStep.instance_id == inst.id)
                                 .order_by(WorkflowStep.step_index)).all()]


def _set_department(username, dept_id):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).one()
        u.department_id = dept_id
        s.add(u); s.commit()
        return u.id


# ---------------------------------------------------------------------------
# Superadmin nie działa w obiegu
# ---------------------------------------------------------------------------

def test_superadmin_sees_requests_but_cannot_act_anywhere(api):
    w = _world(api)
    sup, kier, kierP, it = (w["sup"], api.login("kier"), api.login("kierP"),
                            api.login("it"))
    rid = _create(api, w, api.login("hr"), items=False)

    # Podgląd — także na etapie roboczym kierownika komórki.
    d = _det(api, rid, sup)
    assert d["current_node_type"] == "select_permissions"
    assert d["can_act"] is False and d["can_take_over"] is False
    assert rid in [x["id"] for x in api.get("/requests/", token=sup).json()]
    assert api.get(f"/requests/{rid}/workflow", token=sup).status_code == 200

    # Wybór uprawnień, przejęcie, wersja robocza → 403.
    r = _act(api, rid, sup, "select", items=_items(w))
    assert r.status_code == 403 and "Superadmin" in r.json()["detail"]
    assert api.post(f"/requests/{rid}/take-over", token=sup).status_code == 403
    assert api.post(f"/requests/{rid}/draft", token=sup,
                    json={"items": _items(w)}).status_code == 403

    # Oddanie cudzego przejęcia → 403 (oddać może tylko przejmujący).
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    assert _det(api, rid, sup)["can_release"] is False
    r = api.post(f"/requests/{rid}/release", token=sup)
    assert r.status_code == 403, r.text
    assert api.post(f"/requests/{rid}/release", token=kierP).status_code == 200

    # Kierownik komórki wybiera → akceptacja wyższa; superadmin jej nie wykona.
    assert _act(api, rid, kier, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, sup) == "higher_manager_approve"
    assert _det(api, rid, sup)["can_act"] is False
    assert _act(api, rid, sup, "approve").status_code == 403
    assert _act(api, rid, sup, "reject", comment="nie").status_code == 403

    # Realizacja IT — superadmin też nie.
    assert _act(api, rid, kierP, "approve").status_code == 200
    assert api.node_type(rid, sup) == "it_execute"
    assert _act(api, rid, sup, "execute").status_code == 403
    item_id = _det(api, rid, it)["items"][0]["id"]
    assert api.post(f"/requests/{rid}/items/{item_id}/fulfill", token=sup,
                    json={"fulfilled": True}).status_code == 403
    assert api.post(f"/requests/{rid}/link-worker", token=sup,
                    json={"ad_username": "ola.nowa"}).status_code == 403
    assert _act(api, rid, it, "execute").status_code == 200
    assert _det(api, rid, sup)["status"] == "completed"


def test_link_worker_is_it_only(api):
    w = _world(api, two_stage=False)
    rid = _create(api, w, api.login("kier"))   # od razu w IT
    assert api.node_type(rid, api.login("it")) == "it_execute"
    admin_id = api.mk_user(w["sup"], "adm", ["admin"], "Admin")
    assert admin_id
    r = api.post(f"/requests/{rid}/link-worker", token=api.login("adm"),
                 json={"ad_username": "ola.nowa"})
    assert r.status_code == 403
    r = api.post(f"/requests/{rid}/link-worker", token=api.login("it"),
                 json={"ad_username": "ola.nowa"})
    assert r.status_code == 200, r.text
    assert r.json()["worker_user_id"]


def test_unit_director_self_request_approved_by_superadmin(api):
    """Dyrektor jednostki kieruje komórką najwyższego poziomu i składa wniosek
    „dla siebie” — nad nim nie ma nikogo, akceptację wyższą wykona superadmin."""
    w = _world(api)
    sup = w["sup"]
    top = api.mk_department(sup, w["unit"], w["did"], name="Sekretariat")
    did = _set_department("dyr", top)
    dyr = api.login("dyr")
    rid = _create(api, w, api.login("hr"), dep=top, items=False, worker_user_id=did)

    assert _act(api, rid, dyr, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, sup) == "higher_manager_approve"
    d = _det(api, rid, sup)
    assert "superadmin" in (d["waiting_for"] or "")
    assert d["can_act"] is True
    # Wniosek trafia na pulpit superadmina.
    dash = api.get("/requests/dashboard", token=sup).json()
    assert rid in [p["request_id"] for p in dash["pending_approvals_list"]]
    # Dyrektor sam siebie nie zatwierdzi.
    assert _act(api, rid, dyr, "approve").status_code == 403
    assert _act(api, rid, sup, "approve").status_code == 200
    assert api.node_type(rid, sup) == "it_execute"


# ---------------------------------------------------------------------------
# Automatyczna akceptacja wyższa
# ---------------------------------------------------------------------------

def test_take_over_in_two_stage_dept_auto_approves_higher(api):
    w = _world(api)
    kier, kierP = api.login("kier"), api.login("kierP")
    rid = _create(api, w, api.login("hr"), items=False)

    # Kierownik komórki wysyła do akceptacji wyższej, przełożony (przed
    # przejęciem) nie może działać.
    assert _det(api, rid, kier)["next_node_type"] == "higher_manager_approve"
    assert _det(api, rid, kierP)["can_act"] is False

    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    d = _det(api, rid, kierP)
    assert d["can_act"] is True
    assert d["next_node_type"] == "it_execute"     # „Wyślij do realizacji”

    # Oświadczenie wymagane jak przy każdym kroku kierującym do IT.
    r = _act(api, rid, kierP, "select", items=_items(w), declaration=None)
    assert r.status_code == 428, r.text
    assert _act(api, rid, kierP, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, kierP) == "it_execute"

    steps = _steps(rid)
    auto = [s for s in steps if s[0] == "higher_manager_approve"]
    assert auto == [("higher_manager_approve", "approve", "Anna Przełożona",
                     AUTO_HIGHER_COMMENT)]
    # Krok wyboru i automatyczna akceptacja — ten sam aktor, w tej kolejności.
    kinds = [(s[0], s[1]) for s in steps]
    assert kinds.index(("select_permissions", "select")) + 1 == \
        kinds.index(("higher_manager_approve", "approve"))
    assert api.get(f"/requests/{rid}/workflow/verify",
                   token=kierP).json()["chain_valid"] is True


def test_request_created_by_superior_for_two_stage_dept_lands_in_it(api):
    w = _world(api)
    kierP = api.login("kierP")
    r = api.post("/requests/", token=kierP, json={
        "worker_name": "Ola Nowa", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"], "items": _items(w), "declaration": None})
    assert r.status_code == 428, r.text

    rid = _create(api, w, kierP)
    assert api.node_type(rid, kierP) == "it_execute"
    steps = _steps(rid)
    assert ("higher_manager_approve", "approve", "Anna Przełożona",
            AUTO_HIGHER_COMMENT) in steps


def test_director_taking_over_auto_approves(api):
    w = _world(api)
    dyr = api.login("dyr")
    rid = _create(api, w, api.login("hr"), items=False)
    assert api.post(f"/requests/{rid}/take-over", token=dyr).status_code == 200
    assert _det(api, rid, dyr)["next_node_type"] == "it_execute"
    assert _act(api, rid, dyr, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, dyr) == "it_execute"
    assert ("higher_manager_approve", "approve", "Dorota Dyrektor",
            AUTO_HIGHER_COMMENT) in _steps(rid)


def test_dept_manager_selection_still_needs_higher_approval(api):
    w = _world(api)
    kier = api.login("kier")
    rid = _create(api, w, kier)   # kierownik komórki składa z pozycjami
    assert api.node_type(rid, kier) == "higher_manager_approve"
    assert not [s for s in _steps(rid) if s[3] == AUTO_HIGHER_COMMENT]


def test_no_auto_approval_for_self_request(api):
    """Przełożony (kierownik P) jest pracownikiem komórki K i przejmuje wniosek,
    który dotyczy jego samego — akceptacji wyższej nie zalicza (wykona ją
    dyrektor jednostki)."""
    w = _world(api)
    kierP_id = _set_department("kierP", w["dep"])
    kierP, dyr = api.login("kierP"), api.login("dyr")
    rid = _create(api, w, api.login("hr"), items=False, worker_user_id=kierP_id)
    assert api.post(f"/requests/{rid}/take-over", token=kierP).status_code == 200
    assert _det(api, rid, kierP)["next_node_type"] == "higher_manager_approve"
    assert _act(api, rid, kierP, "select", items=_items(w)).status_code == 200
    assert api.node_type(rid, kierP) == "higher_manager_approve"
    assert not [s for s in _steps(rid) if s[3] == AUTO_HIGHER_COMMENT]
    assert _act(api, rid, kierP, "approve").status_code == 403
    assert _act(api, rid, dyr, "approve").status_code == 200
    assert api.node_type(rid, dyr) == "it_execute"
