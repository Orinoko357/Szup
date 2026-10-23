"""Migracje i siatka bezpieczeństwa `current_node_type` (porządki 3.5).

- backfill `AccessRequest.current_node_type` z aktywnej instancji obiegu,
- ostrzeżenie przy starcie, gdy aktywna instancja nadal ma pusty typ węzła,
- nieudany ALTER nie przechodzi po cichu (`MigrationError`),
- lista wniosków ukrywa wniosek w toku z pustym typem węzła w komórce z etapem
  kierownika (zamiast ujawniać możliwą wersję roboczą),
- cache „wniosek → instancja” w sesji jest czyszczony po flushu."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine
from models import AccessRequest, User, WorkflowInstance


class _Log:
    """Zastępczy logger (testy chodzą z `-p no:logging`, bez caplog)."""

    def __init__(self):
        self.records: list[tuple[str, str]] = []

    def _rec(self, level, msg, *args):
        self.records.append((level, msg % args if args else msg))

    def info(self, msg, *args):
        self._rec("info", msg, *args)

    def warning(self, msg, *args):
        self._rec("warning", msg, *args)

    def error(self, msg, *args):
        self._rec("error", msg, *args)


def _world(api):
    """Jednostka U: komórka K (kierownik `kier`), IT, HR; system z uprawnieniem."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Jan Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid, pid = api.mk_system_perm(sup, "FK", "Odczyt")
    return dict(sup=sup, unit=unit, dep=dep, sid=sid, pid=pid,
                rtype=api.request_type(sup, "NEW_EMP"))


def _create(api, w, token, **extra):
    r = api.post("/requests/", token=token, json={
        "worker_name": "Ola", "unit_id": w["unit"], "department_id": w["dep"],
        "request_type_id": w["rtype"],
        "items": [{"system_id": w["sid"], "permission_id": w["pid"]}], **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _set_node_type(rid, value):
    with engine.begin() as conn:
        conn.execute(text('UPDATE "accessrequest" SET current_node_type = :v WHERE id = :id'),
                     {"v": value, "id": rid})


def _node_type(rid):
    with engine.connect() as conn:
        return conn.execute(text(
            'SELECT current_node_type FROM "accessrequest" WHERE id = :id'), {"id": rid}
        ).scalar()


# ---------------------------------------------------------------------------
# Backfill i ostrzeżenie
# ---------------------------------------------------------------------------

def test_run_migrations_backfills_current_node_type(api):
    import database
    w = _world(api)
    at_select = _create(api, w, api.login("hr"))
    at_it = _create(api, w, api.login("kier"))
    done = _create(api, w, api.login("kier"))
    assert api.post(f"/requests/{done}/workflow/action", token=api.login("it"),
                    json={"action": "execute"}).status_code == 200
    for rid in (at_select, at_it, done):
        _set_node_type(rid, None)

    database._run_migrations()   # idempotentne — także na zmigrowanej bazie

    assert _node_type(at_select) == "select_permissions"
    assert _node_type(at_it) == "it_execute"
    assert _node_type(done) is None   # zakończony obieg — kolumna zostaje pusta


def test_backfill_function_fills_row_inserted_with_null(api):
    from database import _backfill_current_node_type
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    _set_node_type(rid, None)
    log = _Log()
    with engine.connect() as conn:
        _backfill_current_node_type(conn, log)
    assert _node_type(rid) == "select_permissions"
    assert not [m for lvl, m in log.records if lvl in ("warning", "error")]


def test_startup_warns_when_active_instance_keeps_null_node_type(api):
    from database import _backfill_current_node_type, _warn_missing_current_node_type
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    # Uszkodzony stan: bieżący węzeł instancji nie istnieje w grafie → backfill
    # nie ma z czego wyliczyć typu.
    with engine.begin() as conn:
        conn.execute(text('UPDATE "workflowinstance" SET current_node_id = :n '
                          'WHERE request_id = :id'), {"n": "nie-ma-takiego", "id": rid})
    _set_node_type(rid, None)
    log = _Log()
    with engine.connect() as conn:
        _backfill_current_node_type(conn, log)
        assert _warn_missing_current_node_type(conn, _Log()) == 1
    assert _node_type(rid) is None
    warnings = [m for lvl, m in log.records if lvl == "warning"]
    assert len(warnings) == 1 and "pusty current_node_type" in warnings[0]


# ---------------------------------------------------------------------------
# ALTER nie przechodzi po cichu
# ---------------------------------------------------------------------------

def test_add_column_is_idempotent_and_fails_loudly(api):
    from database import MigrationError, _add_column, _table_columns
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "zz_migr" (id INTEGER PRIMARY KEY)'))
    log = _Log()
    with engine.connect() as conn:
        _add_column(conn, "zz_migr", "note", "VARCHAR", log)
        assert "note" in _table_columns(conn, "zz_migr")
        # Kolumna już jest — bez ALTER, bez wpisu w logu.
        n = len(log.records)
        _add_column(conn, "zz_migr", "note", "VARCHAR", log)
        assert len(log.records) == n
        # ALTER, którego SQLite nie wykona (ADD COLUMN z ograniczeniem UNIQUE).
        with pytest.raises(MigrationError):
            _add_column(conn, "zz_migr", "required_col", "INTEGER UNIQUE", log)
        assert "required_col" not in _table_columns(conn, "zz_migr")
    errors = [m for lvl, m in log.records if lvl == "error"]
    assert len(errors) == 1 and "zz_migr.required_col" in errors[0]


def test_run_migrations_aborts_startup_when_column_cannot_be_added(api, monkeypatch):
    import database
    real = database._add_column

    def broken(conn, table, column, col_def, log):
        if (table, column) == ("accessrequest", "current_node_type"):
            # Symulacja bazy, w której kolumny brak, a ALTER się nie udaje.
            return real(conn, "accessrequest", "zz_missing", "INTEGER UNIQUE", log)
        return real(conn, table, column, col_def, log)

    monkeypatch.setattr(database, "_add_column", broken)
    with pytest.raises(database.MigrationError):
        database._run_migrations()


# ---------------------------------------------------------------------------
# Siatka bezpieczeństwa listy
# ---------------------------------------------------------------------------

def test_list_hides_active_request_with_null_node_type_in_manager_stage_dept(api):
    w = _world(api)
    kier, it = api.login("kier"), api.login("it")
    draft = _create(api, w, kier, draft=True)
    at_it = _create(api, w, kier)
    done = _create(api, w, kier)
    assert api.post(f"/requests/{done}/workflow/action", token=it,
                    json={"action": "execute"}).status_code == 200
    listed = {x["id"] for x in api.get("/requests/", token=it).json()}
    assert draft not in listed and {at_it, done} <= listed

    # Kolumna niewypełniona (np. nieudany backfill): wniosek w toku znika z listy
    # IT, zakończony (pusty typ — normalny stan) zostaje widoczny.
    _set_node_type(at_it, None)
    _set_node_type(done, None)
    listed = {x["id"] for x in api.get("/requests/", token=it).json()}
    assert at_it not in listed and done in listed and draft not in listed
    # Podgląd pojedynczego wniosku liczy regułę z instancji — dalej dostępny.
    assert api.get(f"/requests/{at_it}", token=it).status_code == 200
    # Kierownik komórki (jego krąg) widzi wszystko jak wcześniej.
    listed = {x["id"] for x in api.get("/requests/", token=kier).json()}
    assert {draft, at_it, done} <= listed


# ---------------------------------------------------------------------------
# Wspólny helper „wniosek → aktywny węzeł” i jego cache
# ---------------------------------------------------------------------------

def test_request_workflow_cache_is_cleared_after_flush(api):
    from services.workflow import instance_of, request_workflow
    w = _world(api)
    rid = _create(api, w, api.login("hr"))
    with Session(engine) as s:
        r = s.get(AccessRequest, rid)
        inst, node = request_workflow(s, r)
        assert node["type"] == "select_permissions"
        assert s.info["_wf_rows"][rid] is inst
        # Węzeł liczony na bieżąco z obiektu instancji (nie z zapamiętanej kopii).
        graph_ids = {n["id"]: n["type"] for n in
                     json.loads(inst.template_snapshot)["nodes"]}
        it_node = next(k for k, v in graph_ids.items() if v == "it_execute")
        inst.current_node_id = it_node
        assert request_workflow(s, rid)[1]["type"] == "it_execute"
        s.flush()
        assert "_wf_rows" not in s.info and "_wf_graphs" not in s.info
        s.rollback()
        assert instance_of(s, rid).current_node_id != it_node

        # Wniosek bez obiegu: (None, None), wpis None trafia do cache.
        u = s.exec(select(User).where(User.username == "kier")).one()
        bare = AccessRequest(worker_name="X", unit_id=w["unit"], department_id=w["dep"],
                             created_by_id=u.id, created_by_name="kier")
        s.add(bare); s.flush()
        assert request_workflow(s, bare) == (None, None)
        assert s.info["_wf_rows"][bare.id] is None
        s.rollback()
    with Session(engine) as s:
        assert s.exec(select(WorkflowInstance).where(
            WorkflowInstance.request_id == rid)).one().current_node_id != it_node
