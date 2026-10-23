"""E2E: równoważność widoczności listy wniosków (SQL) z regułą dla pojedynczego
wniosku (porządki 3.5).

Lista (`GET /requests/`) wycina wnioski na etapie roboczym kierownika już
w zapytaniu (`manager_stage_hidden_clause`), a podgląd pojedynczego wniosku
liczy regułę z instancji obiegu (`manager_stage_visibility` /
`can_view_request`). Dla KAŻDEGO użytkownika bogatszej struktury (zastępcy,
samodzielne stanowisko, nieaktywny kierownik, akceptacja dwustopniowa,
dyrektor jednostki, kierownik spoza jednostki) oba zbiory muszą się zgadzać."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from database import engine
from models import AccessRequest, User


# Konta zakładane w `_world` (kierN jest nieaktywny — nie loguje się).
USERS = ("root", "adm", "it", "itkier", "hr", "prac", "kierP", "zastP", "kier",
         "zastK", "kier2", "kierN", "dyr", "obcy")
# Widzą wszystko poza ukrytym etapem roboczym — lista == can_view_request.
SEE_ALL = ("root", "adm", "it", "itkier")


def _world(api):
    """Jednostka U (dyrektor `dyr`):

        P  (kierP, zastępca zastP)
        ├── K   (kier, zastępca zastK)            — 1-stopniowa
        ├── K2  (kier2, wymaga akceptacji wyższej) — 2-stopniowa
        ├── S   samodzielne stanowisko
        └── N   (kierN — konto nieaktywne)
    Jednostka V: komórka X (obcy). Do tego IT, kierownik IT, admin, HR, pracownik.
    Wnioski w różnych stanach: robocze, u kierownika, przejęty, akceptacja
    wyższa, realizacja IT, zakończony, odrzucony."""
    sup = api.setup_superadmin()
    u = api.mk_unit(sup, "U", "U")
    v = api.mk_unit(sup, "V", "V")
    ids = {name: api.mk_user(sup, name, roles, name) for name, roles in (
        ("kierP", ["manager"]), ("zastP", ["manager"]), ("kier", ["manager"]),
        ("zastK", ["manager"]), ("kier2", ["manager"]), ("kierN", ["manager"]),
        ("dyr", ["manager"]), ("obcy", ["manager"]), ("it", ["it_staff"]),
        ("itkier", ["manager", "it_staff"]), ("adm", ["admin"]), ("prac", ["viewer"]),
    )}
    api.mk_user(sup, "hr", ["hr"], "hr", unit_ids=[u, v])
    p = api.mk_department(sup, u, ids["kierP"], name="P")
    k = api.mk_department(sup, u, ids["kier"], name="K", parent_dept_id=p)
    k2 = api.mk_department(sup, u, ids["kier2"], name="K2", parent_dept_id=p,
                           requires_higher_approval=True)
    r = api.post("/units/departments", token=sup, json={
        "unit_id": u, "name": "S", "kind": "standalone", "parent_dept_id": p})
    assert r.status_code == 201, r.text
    s_dept = r.json()["id"]
    n = api.mk_department(sup, u, ids["kierN"], name="N", parent_dept_id=p)
    x = api.mk_department(sup, v, ids["obcy"], name="X")
    for dept, deputy in ((p, "zastP"), (k, "zastK")):
        assert api.post(f"/units/departments/{dept}/deputies", token=sup,
                        json={"user_id": ids[deputy]}).status_code == 201
    assert api.patch(f"/units/{u}", token=sup, json={"manager_user_id": ids["dyr"]}
                     ).status_code == 200
    # Nieaktywny kierownik komórki N (bez zwalniania stanowiska — stan „zastany”).
    with Session(engine) as s:
        row = s.get(User, ids["kierN"])
        row.is_active = False
        s.add(row); s.commit()

    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    rtype = api.request_type(sup, "NEW_EMP")
    items = [{"system_id": sid, "permission_id": pid}]

    def create(token, unit, dept, **extra):
        body = {"worker_name": "Ola", "unit_id": unit, "department_id": dept,
                "request_type_id": rtype, "items": items, **extra}
        res = api.post("/requests/", token=token, json=body)
        assert res.status_code == 201, res.text
        return res.json()["id"]

    hr, kier, kier2 = api.login("hr"), api.login("kier"), api.login("kier2")
    for dept in (k, k2, s_dept, n):
        create(hr, u, dept)                                  # u kierownika / wyżej
    create(hr, v, x)                                         # jednostka V
    create(kier, u, k, draft=True)                           # wersja robocza K
    create(kier2, u, k2)                                     # akceptacja wyższa
    it_req = create(kier, u, k)                              # realizacja IT
    taken = create(hr, u, k)
    assert api.post(f"/requests/{taken}/take-over", token=api.login("kierP")
                    ).status_code == 200
    it = api.login("it")
    done = create(kier, u, k)
    assert api.post(f"/requests/{done}/workflow/action", token=it,
                    json={"action": "execute"}).status_code == 200
    rejected = create(hr, u, k)
    assert api.post(f"/requests/{rejected}/workflow/action", token=kier,
                    json={"action": "reject", "comment": "nie"}).status_code == 200
    assert api.node_type(it_req, it) == "it_execute"
    return sup


@pytest.mark.parametrize("username", USERS)
def test_list_visibility_equals_single_request_rule(api, username):
    from services.workflow import can_view_request, manager_stage_hidden_clause
    _world(api)
    with Session(engine) as s:
        user = s.exec(select(User).where(User.username == username)).one()
        all_rows = s.exec(select(AccessRequest)).all()
        can = {r.id for r in all_rows if can_view_request(s, r, user)}
        clause = manager_stage_hidden_clause(s, user)
        stmt = select(AccessRequest.id)
        if clause is not None:
            stmt = stmt.where(clause)
        sql_visible = set(s.exec(stmt).all())
    # Równoważność warunku SQL z regułą dla pojedynczego wniosku.
    assert sql_visible == can, username
    # Coś faktycznie jest ukryte przed osobami spoza kręgu kierownika.
    if username in ("adm", "it", "itkier", "obcy", "kier2"):
        assert can != {r.id for r in all_rows}, username

    if username == "kierN":
        return   # konto nieaktywne — nie zaloguje się
    listed = {x["id"] for x in api.get("/requests/", token=api.login(username)).json()}
    assert listed <= can, username
    if username in SEE_ALL:
        assert listed == can, username
    # Podgląd pojedynczego wniosku zgadza się z regułą (403 = ukryty etap roboczy).
    tok = api.login(username)
    for rid in {r.id for r in all_rows} - can:
        assert api.get(f"/requests/{rid}", token=tok).status_code == 403, (username, rid)
