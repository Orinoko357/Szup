"""
Wspólna infrastruktura testów E2E (pytest) dla SZUP.

Sieć bezpieczeństwa regresji (audyt G1). Testy uruchamiają PRAWDZIWĄ aplikację
FastAPI na tymczasowej bazie SQLite (świeżej dla każdego testu) przez
starlette TestClient — bez sieci, bez osobnego procesu uvicorn.

WAŻNE: zmienne środowiskowe MUSZĄ być ustawione ZANIM zaimportujemy `database`
/ `main`, bo silnik SQLite jest tworzony przy imporcie na podstawie env.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

# --- env PRZED importem aplikacji -------------------------------------------
_TMP_DIR = tempfile.mkdtemp(prefix="szup-tests-")
os.environ["SZUP_DATA_DIR"] = _TMP_DIR
os.environ["SZUP_DB_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'test.db')}"
os.environ["SZUP_WORKFLOW_SECRET"] = "pytest-secret"
# Domyślnie tryb testowy (passwordless) WYŁĄCZONY — testy C2 włączają go jawnie.
os.environ.pop("SZUP_ALLOW_TEST_MODE", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel              # noqa: E402

from database import engine, init_db       # noqa: E402
from main import app                       # noqa: E402

PW = "Testowe123!@#XYZ"   # spełnia politykę siły hasła
# Domyślne oświadczenie wnioskującego wstrzykiwane automatycznie w akcje
# select/approve i tworzenie wniosku z pozycjami (patrz Api.post).
DEFAULT_DECLARATION = {"declared_by_name": "Testowy Kierownik", "declared_date": "2026-07-23"}


def _drop_everything():
    """Usuń wszystkie tabele przy WYŁĄCZONYCH kluczach obcych.

    Z FK=ON `DROP TABLE` robi implicit-DELETE, który przy cyklu department↔user
    narusza więzy. PRAGMA foreign_keys musi być ustawiony poza transakcją, więc
    działamy na surowym połączeniu DBAPI.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        for (name,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{name}"')
        raw.commit()
        # WAŻNE: przywróć egzekwowanie FK PRZED zwrotem połączenia do puli —
        # inaczej pula oddałaby je z foreign_keys=OFF (listener 'connect' nie
        # odpala się przy checkout), fałszywie wyłączając FK w kolejnych żądaniach.
        cur.execute("PRAGMA foreign_keys=ON")
        raw.commit()
        cur.close()
    finally:
        raw.close()
    # Dodatkowa gwarancja: wyrzuć pulę połączeń, by żadne nie zostało z FK=OFF.
    engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_db():
    """Każdy test dostaje świeżą, ponownie zaseedowaną bazę."""
    _drop_everything()
    init_db()   # create_all + migracje + triggery + seed domyślnego obiegu
    # Wyzeruj globalny limiter prób logowania per-IP (stan modułowy, nie w bazie),
    # inaczej po ~10 logowaniach kolejne testy dostają 429/403.
    try:
        from routers import auth as _auth
        _auth._ip_hits.clear()
    except Exception:
        pass
    yield
    _drop_everything()


@pytest.fixture()
def client():
    # Bez context-managera: lifespan (init_db) i tak realizuje fixture _fresh_db.
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpery — skracają setup w testach
# ---------------------------------------------------------------------------

class Api:
    """Cienki wrapper na TestClient z pomocnikami autoryzacji/setupu."""

    def __init__(self, client: TestClient):
        self.c = client

    # --- niskopoziomowe ---
    def _h(self, token: str | None):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path, token=None, **kw):
        return self.c.get(f"/api{path}", headers=self._h(token), **kw)

    def post(self, path, token=None, **kw):
        # Nadanie uprawnień kierowane do IT wymaga teraz oświadczenia
        # wnioskującego (route zwraca 428 bez niego). Żeby nie zaśmiecać
        # dziesiątek istniejących testów, wstrzykujemy domyślne oświadczenie
        # dla akcji select/approve i przy tworzeniu wniosku z pozycjami —
        # CHYBA że test świadomie podał klucz `declaration` (także None, gdy
        # chce sprawdzić bramkę 428).
        body = kw.get("json")
        if isinstance(body, dict) and "declaration" not in body:
            act = body.get("action")
            if act in ("select", "approve") or (
                path.endswith("/requests/") and body.get("items")
            ):
                body = {**body, "declaration": DEFAULT_DECLARATION}
                kw = {**kw, "json": body}
        return self.c.post(f"/api{path}", headers=self._h(token), **kw)

    def patch(self, path, token=None, **kw):
        return self.c.patch(f"/api{path}", headers=self._h(token), **kw)

    def put(self, path, token=None, **kw):
        return self.c.put(f"/api{path}", headers=self._h(token), **kw)

    def delete(self, path, token=None, **kw):
        return self.c.delete(f"/api{path}", headers=self._h(token), **kw)

    # --- setup ---
    def setup_superadmin(self, username="root"):
        st = self.get("/auth/status").json()
        if st.get("first_run"):
            self.post("/auth/setup", json={
                "username": username, "password": PW,
                "full_name": "Super Admin", "email": "root@t.local",
            })
        return self.login(username)

    def login(self, username, password=PW):
        r = self.post("/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def mk_user(self, admin_token, username, roles, full_name=None, unit_ids=None):
        body = {"username": username, "password": PW,
                "full_name": full_name or username, "email": f"{username}@t.local",
                "roles": roles}
        if unit_ids is not None:
            body["unit_ids"] = unit_ids
        r = self.post("/users/", token=admin_token, json=body)
        assert r.status_code in (200, 201), r.text
        uid = r.json()["id"]
        # Konto założone przez admina ma must_change_password=True, a backend
        # egzekwuje zmianę hasła (403 PASSWORD_CHANGE_REQUIRED). Testy obiegu
        # symulują użytkownika po pierwszej zmianie hasła — zdejmujemy flagę.
        from sqlmodel import Session as _S
        from models import User as _U
        with _S(engine) as s:
            u = s.get(_U, uid)
            u.must_change_password = False
            s.add(u); s.commit()
        return uid

    def mk_unit(self, admin_token, name=None, code=None):
        name = name or f"Jednostka-{uuid.uuid4().hex[:6]}"
        r = self.post("/units/", token=admin_token,
                      json={"name": name, "code": code or name[:8]})
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    def mk_department(self, admin_token, unit_id, manager_user_id,
                      requires_higher_approval=False, name="Wydział",
                      parent_dept_id=None):
        body = {"unit_id": unit_id, "name": name, "kind": "department",
                "manager_user_id": manager_user_id,
                "requires_higher_approval": requires_higher_approval}
        if parent_dept_id is not None:
            body["parent_dept_id"] = parent_dept_id
        r = self.post("/units/departments", token=admin_token, json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    def mk_system_perm(self, admin_token, sys_name="System", perm_name="Dostęp"):
        s = self.post("/systems/", token=admin_token,
                      json={"name": sys_name, "access_only": False, "all_units": True})
        assert s.status_code in (200, 201), s.text
        sid = s.json()["id"]
        p = self.post(f"/systems/{sid}/permissions", token=admin_token,
                      json={"permission_name": perm_name})
        assert p.status_code in (200, 201), p.text
        return sid, p.json()["id"]

    def request_type(self, admin_token, code="NEW_EMP"):
        types = {t["code"]: t["id"]
                 for t in self.get("/request-types/", token=admin_token).json()}
        return types[code]

    def node_type(self, rid, token):
        return (self.get(f"/requests/{rid}/workflow", token=token)
                .json().get("current_node", {}) or {}).get("type")


@pytest.fixture()
def api(client):
    return Api(client)
