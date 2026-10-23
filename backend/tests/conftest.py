"""
Wspólna infrastruktura testów E2E (pytest) dla SZUP.

Sieć bezpieczeństwa regresji (audyt G1). Testy uruchamiają PRAWDZIWĄ aplikację
FastAPI na tymczasowej bazie SQLite (świeżej dla każdego testu) przez
starlette TestClient — bez sieci, bez osobnego procesu uvicorn.

WAŻNE: zmienne środowiskowe MUSZĄ być ustawione ZANIM zaimportujemy `database`
/ `main`, bo silnik SQLite jest tworzony przy imporcie na podstawie env.

Szybkość: `init_db()` (create_all, migracje, triggery, seed) wykonujemy RAZ
na sesję do pliku-wzorca, a każdy test dostaje jego kopię. bcrypt w testach
liczy 4 rundy zamiast 12 — hasła i tak się weryfikują, tylko szybciej.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid

import pytest

# --- env PRZED importem aplikacji -------------------------------------------
_TMP_DIR = tempfile.mkdtemp(prefix="szup-tests-")
_DB_FILE = os.path.join(_TMP_DIR, "test.db")
_TEMPLATE_DB = os.path.join(_TMP_DIR, "template.db")
# Katalog tymczasowy (baza, wzorzec, klucz sekretu obiegu) sprzątamy przy wyjściu.
atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)
os.environ["SZUP_DATA_DIR"] = _TMP_DIR
os.environ["SZUP_DB_URL"] = f"sqlite:///{_DB_FILE}"
os.environ["SZUP_WORKFLOW_SECRET"] = "pytest-secret"
# Domyślnie tryb testowy (passwordless) WYŁĄCZONY — testy C2 włączają go jawnie.
os.environ.pop("SZUP_ALLOW_TEST_MODE", None)

from fastapi.testclient import TestClient  # noqa: E402

from database import engine, init_db       # noqa: E402
from main import app                       # noqa: E402
from services import auth_service          # noqa: E402

# Minimalna liczba rund bcrypt — produkcja zostaje przy domyślnych 12.
auth_service.pwd_context.update(bcrypt__rounds=4)

PW = "Testowe123!@#XYZ"   # spełnia politykę siły hasła
# Domyślne oświadczenie wnioskującego wstrzykiwane automatycznie w akcje
# select/approve i tworzenie wniosku z pozycjami (patrz Api.post).
DEFAULT_DECLARATION = {"declared_by_name": "Testowy Kierownik", "declared_date": "2026-07-23"}


def _remove_db_files() -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(_DB_FILE + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture(scope="session")
def _template_db():
    """Zaseedowana baza-wzorzec: jeden `init_db()` na całą sesję testów."""
    engine.dispose()
    _remove_db_files()
    init_db()   # create_all + migracje + triggery + seed domyślnego obiegu
    engine.dispose()   # zamknij połączenia, zanim skopiujemy plik
    shutil.copyfile(_DB_FILE, _TEMPLATE_DB)
    yield _TEMPLATE_DB


def _reset_module_state() -> None:
    """Wyzeruj stan modułowy (poza bazą), który przeciekałby między testami."""
    from routers import auth as _auth
    from routers import settings as _settings
    # Limiter prób logowania per-IP — inaczej po ~10 logowaniach kolejne
    # testy dostają 429/403.
    _auth._ip_hits.clear()
    _auth._sso_codes.clear()
    _settings._factory_reset_failures.clear()
    from services import audit as _audit_svc
    if hasattr(_audit_svc, "_confirm_failures"):
        _audit_svc._confirm_failures.clear()


@pytest.fixture(autouse=True)
def _sync_after_commit(monkeypatch):
    """Zadania po commicie (powiadomienia) wykonujemy SYNCHRONICZNIE w wątku
    testu — inaczej wątki puli `after_commit` mogłyby sięgać do bazy już po
    końcu testu (w trakcie podmiany pliku dla następnego). Testy, które chcą
    przechwycić zadania, nadpisują `_submit` własnym monkeypatchem."""
    import services.after_commit as ac
    monkeypatch.setattr(ac, "_submit", lambda fn, kwargs: ac._safe_run(fn, kwargs))


@pytest.fixture(autouse=True)
def _fresh_db(_template_db):
    """Każdy test dostaje świeżą kopię zaseedowanej bazy."""
    # Pula nie może trzymać połączeń do podmienianego pliku.
    engine.dispose()
    _remove_db_files()
    shutil.copyfile(_template_db, _DB_FILE)
    _reset_module_state()
    yield
    engine.dispose()


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
        """Zakłada konto i zdejmuje must_change_password.

        Roli „hr” już nie ma (v3.9) — `roles` zawierające „hr” oznacza
        pracownika kadr: konto trafia do komórki kadrowej (Department.is_hr)
        w jednostce `unit_ids[0]` (albo w pomocniczej jednostce „Kadry”).
        `unit_ids` nie ogranicza już zakresu kadr — kadry widzą wszystko."""
        wants_hr = "hr" in roles
        roles = [r for r in roles if r != "hr"] or ["viewer"]
        body = {"username": username, "password": PW,
                "full_name": full_name or username, "email": f"{username}@t.local",
                "roles": roles}
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
            if wants_hr:
                u.department_id = self.hr_department(unit_ids[0] if unit_ids else None)
            s.add(u); s.commit()
        return uid

    def hr_department(self, unit_id=None):
        """Komórka kadrowa (is_hr) w danej jednostce — tworzona leniwie, jedna
        na jednostkę. Bez `unit_id` — w pomocniczej jednostce „Kadry”."""
        from sqlmodel import Session as _S, select as _sel
        from models import Department as _D, Unit as _Un
        with _S(engine) as s:
            if unit_id is None:
                unit = s.exec(_sel(_Un).where(_Un.name == "Kadry")).first()
                if unit is None:
                    unit = _Un(name="Kadry", code="KADRY")
                    s.add(unit); s.commit(); s.refresh(unit)
                unit_id = unit.id
            dept = s.exec(_sel(_D).where(_D.unit_id == unit_id)
                          .where(_D.is_hr == True)).first()  # noqa: E712
            if dept is None:
                dept = _D(unit_id=unit_id, name="Komórka kadrowa", is_hr=True)
                s.add(dept); s.commit(); s.refresh(dept)
            return dept.id

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
