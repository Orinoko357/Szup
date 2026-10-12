"""
SQLite database setup for SZUP.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

_DATA_DIR = Path(os.getenv("SZUP_DATA_DIR", "/opt/szup/data"))
_DB_PATH  = _DATA_DIR / "szup.db"
_DB_URL   = os.getenv("SZUP_DB_URL", f"sqlite:///{_DB_PATH}")

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


# M1 — SQLite domyślnie NIE egzekwuje kluczy obcych. Bez tego usunięcie
# User/Department/Unit powiązanego z wnioskiem osieroca wniosek i czyni go
# nieakcjonowalnym (brak kierownika/pracownika → obieg utyka). Włączamy
# egzekwowanie FK na KAŻDYM połączeniu (pula wątków FastAPI otwiera wiele) —
# usunięcie zasobu związanego z aktywnym wnioskiem zostanie odrzucone (RESTRICT),
# zamiast po cichu zepsuć dane.
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # Nie-SQLite (albo sterownik bez cursor) — pomijamy po cichu.
        pass


def init_db():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    _install_auditlog_triggers()
    _seed_default_workflow()
    _backfill_admin_permissions()
    _migrate_custom_fields_to_permissions()


def _backfill_admin_permissions():
    """Dopisz syntetyczne „Uprawnienia administratora" tam, gdzie ich brak.

    Opcja jest domyślnie włączona dla KAŻDEGO oprogramowania, więc programy
    wprowadzone przed tą zmianą też muszą ją dostać — inaczej byłaby widoczna
    tylko przy nowo dodanych. Idempotentne: wstawia wyłącznie braki.
    """
    import logging
    from sqlmodel import Session, select
    from models import PermissionSystem, SystemPermission
    from routers.systems import ADMIN_PERM_NAME

    log = logging.getLogger("szup.seed")
    try:
        with Session(engine) as s:
            have = set(s.exec(
                select(SystemPermission.system_id)
                .where(SystemPermission.permission_name == ADMIN_PERM_NAME)
            ).all())
            added = 0
            for sys_row in s.exec(select(PermissionSystem)).all():
                if sys_row.id in have or not getattr(sys_row, "admin_option", True):
                    continue
                s.add(SystemPermission(
                    system_id=sys_row.id,
                    permission_name=ADMIN_PERM_NAME,
                    description="Pełne uprawnienia administracyjne w tym systemie",
                ))
                added += 1
            if added:
                s.commit()
                log.info("Dodano uprawnienia administratora do %d systemow", added)
    except Exception as e:
        log.warning("Backfill uprawnien administratora nieudany: %s", e)


def _migrate_custom_fields_to_permissions():
    """Pola definiowane przy PROGRAMIE → uprawnienia z kontrolką.

    Wcześniej program mógł mieć ALBO listę uprawnień, ALBO „pola wnioskodawcy".
    Ten podział okazał się sztuczny: dla użytkownika i jedno, i drugie to po
    prostu uprawnienie — raz zwykły checkbox, raz checkbox z listą albo polem.
    Przenosimy więc każde pole na osobne `SystemPermission` z tą samą nazwą,
    typem kontrolki i listą opcji.

    Wartości wpisane na ISTNIEJĄCYCH wnioskach zostają nietknięte — siedzą
    w `RequestItem.custom_values` i dalej się wyświetlają. Syntetyczny „Dostęp",
    który obsługiwał te programy, kasujemy (gdy nieużywany) albo wygaszamy
    (gdy jest w historii), żeby nie dublował się z przeniesionymi pozycjami.
    """
    import logging
    from sqlmodel import Session, select
    from models import PermissionSystem, RequestItem, SystemPermission

    log = logging.getLogger("szup.seed")
    try:
        from routers.systems import ACCESS_PERM_NAME, _parse_custom_fields
    except Exception:                       # pragma: no cover
        return

    try:
        with Session(engine) as s:
            moved = 0
            for sys_row in s.exec(select(PermissionSystem)).all():
                fields = _parse_custom_fields(sys_row.custom_fields)
                if not fields:
                    continue

                existing = {
                    p.permission_name: p for p in s.exec(
                        select(SystemPermission)
                        .where(SystemPermission.system_id == sys_row.id)
                    ).all()
                }
                for f in fields:
                    label = f.get("label")
                    if not label or label in existing:
                        continue
                    opts = f.get("options") or []
                    s.add(SystemPermission(
                        system_id=sys_row.id,
                        permission_name=label,
                        description=f.get("description") or None,
                        input_type=f.get("type") or "text",
                        options=json.dumps(opts, ensure_ascii=False) if opts else None,
                        input_required=bool(f.get("required")),
                    ))
                    moved += 1

                access = existing.get(ACCESS_PERM_NAME)
                if access is not None and not sys_row.access_only:
                    used = s.exec(select(RequestItem)
                                  .where(RequestItem.permission_id == access.id)).first()
                    if used:
                        access.is_active = False
                        s.add(access)
                    else:
                        s.delete(access)

                sys_row.custom_fields = None
                s.add(sys_row)
            if moved:
                s.commit()
                log.info("Przeniesiono %d pol wnioskodawcy na uprawnienia", moved)
            else:
                s.commit()
    except Exception as e:
        log.warning("Migracja pol wnioskodawcy nieudana: %s", e)


def _seed_default_workflow():
    """Utwórz domyślny szablon obiegu i podstawowe typy wniosków — tylko
    jeśli baza jest jeszcze pusta (żadnego szablonu). Idempotentne.
    """
    import json
    import logging
    from sqlmodel import Session, select
    from models import RequestType, WorkflowTemplate

    log = logging.getLogger("szup.seed")
    try:
        with Session(engine) as s:
            existing = s.exec(select(WorkflowTemplate)).first()
            if existing:
                return

            default_graph = {
                "nodes": [
                    {"id": "n1", "type": "start",
                     "label": "Zgłoszenie pracownika (HR)", "x": 50, "y": 100,
                     "props": {}},
                    {"id": "n2", "type": "select_permissions",
                     "label": "Wybór uprawnień i zatwierdzenie (kierownik)", "x": 250, "y": 100,
                     "props": {"actor": "department_manager"}},
                    {"id": "n3", "type": "higher_manager_approve",
                     "label": "Akceptacja kierownika wyższego rzędu", "x": 450, "y": 100,
                     "props": {"skip_if_not_required": True}},
                    {"id": "n4", "type": "it_execute",
                     "label": "Realizacja przez IT", "x": 650, "y": 100,
                     "props": {}},
                    {"id": "n5", "type": "end",
                     "label": "Zakończenie procesu", "x": 850, "y": 100,
                     "props": {}},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                    {"from": "n4", "to": "n5"},
                ],
            }
            tpl = WorkflowTemplate(
                name="Standardowy — nowy pracownik",
                description=("Domyślny obieg dla wniosków o uprawnienia. Kierownik "
                             "bezpośredni wybiera uprawnienia i tym samym je zatwierdza; "
                             "kierownik wyższego rzędu jest pomijany, jeśli komórka nie ma "
                             "flagi 'wymaga akceptacji wyższego rzędu'. Bez podpisu papierowego."),
                version=1,
                graph_json=json.dumps(default_graph, ensure_ascii=False),
                is_active=True,
            )
            s.add(tpl); s.commit(); s.refresh(tpl)

            # Kilka podstawowych typów wniosków.
            defaults = [
                {"name": "Nowy pracownik",       "code": "NEW_EMP",
                 "description": "Wniosek o uprawnienia dla nowo zatrudnionej osoby.",
                 "icon": "user-plus"},
                {"name": "Zmiana uprawnień",     "code": "MODIFY",
                 "description": "Modyfikacja lub rozszerzenie zakresu uprawnień istniejącego pracownika.",
                 "icon": "pencil"},
                {"name": "Cofnięcie uprawnień",  "code": "REVOKE",
                 "description": "Wniosek o odebranie wybranych lub wszystkich uprawnień.",
                 "icon": "user-minus"},
            ]
            for d in defaults:
                s.add(RequestType(
                    name=d["name"], code=d["code"], description=d["description"],
                    workflow_template_id=tpl.id, is_active=True, icon=d["icon"],
                ))
            s.commit()
            log.info("Seeded default workflow template + %d request types", len(defaults))
    except Exception as exc:
        log.warning("Seeding default workflow failed: %s", exc)


def _install_auditlog_triggers():
    from sqlalchemy import text
    triggers = [
        "CREATE TRIGGER IF NOT EXISTS auditlog_no_update "
        "BEFORE UPDATE ON auditlog BEGIN "
        "SELECT RAISE(ABORT, 'auditlog is append-only'); END",

        "CREATE TRIGGER IF NOT EXISTS auditlog_no_delete "
        "BEFORE DELETE ON auditlog BEGIN "
        "SELECT RAISE(ABORT, 'auditlog is append-only'); END",
    ]
    with engine.connect() as conn:
        for sql in triggers:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                conn.rollback()


def _run_migrations():
    """Idempotentne ALTERy dla istniejących baz."""
    import logging
    _mlog = logging.getLogger("szup.migrations")

    simple_migrations = [
        ("user", "full_name",           "VARCHAR"),
        ("user", "email",               "VARCHAR"),
        ("user", "failed_login_count",  "INTEGER DEFAULT 0"),
        ("user", "locked_until",        "DATETIME"),
        ("user", "password_changed_at", "DATETIME"),
        ("user", "must_change_password","BOOLEAN DEFAULT 0"),
        ("user", "tokens_valid_from",   "DATETIME"),
        ("accessrequest", "it_comment", "VARCHAR"),
        ("department",    "parent_dept_id", "INTEGER"),
        ("unit",          "ldap_dn",        "VARCHAR"),
        ("department",    "ldap_dn",        "VARCHAR"),
        ("user",          "department_id",  "INTEGER"),
        ("user",          "ldap_dn",        "VARCHAR"),
        ("department",    "requires_higher_approval", "BOOLEAN DEFAULT 0"),
        ("accessrequest", "selector_by_id",   "INTEGER"),
        ("accessrequest", "selector_comment", "VARCHAR"),
        ("accessrequest", "selected_at",      "DATETIME"),
        ("accessrequest", "worker_user_id",   "INTEGER"),
        ("accessrequest", "kind",             "VARCHAR DEFAULT 'grant'"),
        ("requestitem",   "kind",             "VARCHAR DEFAULT 'grant'"),
        ("requestitem",   "custom_values",    "VARCHAR"),
        ("requestitem",   "added_by_user_id", "INTEGER"),
        ("appsettings",   "helpdesk_email",   "VARCHAR"),
        ("appsettings",   "declaration_text", "VARCHAR"),
        ("appsettings",   "snapshot_enabled", "BOOLEAN DEFAULT 1"),
        ("appsettings",   "snapshot_hour",    "INTEGER DEFAULT 23"),
        ("appsettings",   "snapshot_minute",  "INTEGER DEFAULT 50"),
        ("user",          "title",           "VARCHAR"),
        ("requestitem",   "denied",          "BOOLEAN DEFAULT 0"),
        ("requestitem",   "deny_comment",    "VARCHAR"),
        ("requestitem",   "denied_by_user_id", "INTEGER"),
        ("requestitem",   "denied_at",       "DATETIME"),
        ("requestitem",   "fulfilled",       "BOOLEAN DEFAULT 0"),
        ("requestitem",   "fulfilled_by_user_id", "INTEGER"),
        ("requestitem",   "fulfilled_at",    "DATETIME"),
        ("ldapsettings",  "sso_enabled",     "BOOLEAN DEFAULT 0"),
        ("ldapsettings",  "sso_auto",        "BOOLEAN DEFAULT 0"),
        ("unit",          "manager_user_id", "INTEGER"),
        ("emailsettings", "to_address",      "VARCHAR DEFAULT ''"),
        ("emailsettings", "sender_as_actor", "BOOLEAN DEFAULT 1"),
        ("accessrequest", "assigned_to_user_id", "INTEGER"),
        ("systempermission", "group_order",   "INTEGER"),
        ("permissionsystem", "require_scope",  "BOOLEAN DEFAULT 0"),
        ("permissionsystem", "access_only",   "BOOLEAN DEFAULT 0"),
        ("permissionsystem", "all_units",     "BOOLEAN DEFAULT 1"),
        ("permissionsystem", "custom_fields", "VARCHAR"),
        ("permissionsystem", "display_order",   "INTEGER"),
        ("permissionsystem", "default_checked", "BOOLEAN DEFAULT 0"),
        ("permissionsystem", "vendor_id",       "INTEGER"),
        ("permissionsystem", "admin_option",    "BOOLEAN DEFAULT 1"),
        # Import list uprawnień z plików — grupy i wygaszanie pozycji
        ("systempermission", "group_name",    "VARCHAR"),
        ("systempermission", "external_code", "VARCHAR"),
        ("systempermission", "is_active",     "BOOLEAN DEFAULT 1"),
        # Kontrolka przy uprawnieniu (lista / pole) — zamiast pól na programie
        ("systempermission", "input_type",     "VARCHAR DEFAULT 'none'"),
        ("systempermission", "options",        "VARCHAR"),
        ("systempermission", "input_required", "BOOLEAN DEFAULT 0"),
        ("department",       "kind",          "VARCHAR DEFAULT 'department'"),
        # Workflow engine — konfigurowalny obieg wniosków
        ("accessrequest",    "request_type_id", "INTEGER"),
        # PDF/EZD tracking dla bieżącego węzła instancji obiegu
        ("workflowinstance", "pending_pdf_at",         "DATETIME"),
        ("workflowinstance", "pending_ezd_confirmed",  "BOOLEAN DEFAULT 0"),
        ("workflowinstance", "pending_pdf_by_user_id", "INTEGER"),
        ("workflowinstance", "pending_ezd_by_user_id", "INTEGER"),
    ]
    from sqlalchemy import text
    with engine.connect() as conn:
        for table, column, col_def in simple_migrations:
            try:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {col_def}'))
                conn.commit()
            except Exception:
                conn.rollback()

        # H4 — UNIQUE(instance_id, step_index) na istniejących bazach. Tworzymy
        # przez CREATE UNIQUE INDEX (idempotentne). Jeśli w bazie są już duplikaty
        # (stare, niepoprawne dane), utworzenie się nie powiedzie — logujemy i
        # zostawiamy bez indeksu, żeby nie blokować startu.
        try:
            conn.execute(text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_step_instance_index '
                'ON "workflowstep" (instance_id, step_index)'
            ))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _mlog.warning("Nie udało się utworzyć uq_step_instance_index "
                          "(możliwe duplikaty kroków): %s", exc)

        # Backfill: accessrequest.worker_user_id dla starych rekordów (best-effort).
        # Dopasowujemy po (worker_name, department_id) do aktywnego użytkownika.
        # L4 — dopasowujemy TYLKO gdy kandydat jest DOKŁADNIE JEDEN. Przy kolizji
        # imion (dwie osoby o tym samym nazwisku w komórce) dawne `LIMIT 1`
        # przypisywało losową osobę — teraz zostawiamy NULL zamiast zgadywać.
        try:
            match_cond = (
                'u.is_active = 1 '
                'AND u.department_id = "accessrequest".department_id '
                'AND (lower(u.full_name) = lower("accessrequest".worker_name) '
                '     OR lower(u.username)  = lower("accessrequest".worker_name))'
            )
            conn.execute(text(f"""
                UPDATE "accessrequest"
                   SET worker_user_id = (
                         SELECT u.id FROM "user" u WHERE {match_cond}
                       )
                 WHERE worker_user_id IS NULL
                   AND (SELECT COUNT(*) FROM "user" u WHERE {match_cond}) = 1
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Migracja: single role → roles JSON array
        # Dodaj kolumnę roles jeśli nie istnieje
        cols = [r[1] for r in conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()]
        if "roles" not in cols:
            try:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN roles TEXT'))
                conn.commit()
            except Exception:
                conn.rollback()
            # Przepisz wartości z kolumny role (jeśli istnieje) do roles JSON
            if "role" in cols:
                try:
                    conn.execute(text(
                        'UPDATE "user" SET roles = \'["\' || role || \'"]\'  WHERE roles IS NULL'
                    ))
                    conn.commit()
                except Exception:
                    conn.rollback()
            # Fallback: ustaw viewer dla rekordów bez roles
            try:
                conn.execute(text(
                    'UPDATE "user" SET roles = \'["viewer"]\' WHERE roles IS NULL'
                ))
                conn.commit()
            except Exception:
                conn.rollback()

        # Drop LEGACY single-role column 'role' (zastąpionej przez 'roles' JSON).
        # Bez tego INSERTy z nowego modelu (który nie zna kolumny 'role') dostają
        # NULL w NOT NULL → IntegrityError. SQLite ≥3.35 wspiera ALTER ... DROP COLUMN.
        cols_after = [r[1] for r in conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()]
        if "role" in cols_after and "roles" in cols_after:
            try:
                conn.execute(text('ALTER TABLE "user" DROP COLUMN role'))
                conn.commit()
                _mlog.info("Dropped legacy 'role' column from user table")
            except Exception as exc:
                conn.rollback()
                _mlog.warning(
                    "Cannot DROP COLUMN role (SQLite <3.35?): %s. "
                    "Próbuję recreate-table fallback.", exc
                )
                _drop_role_via_recreate(conn)


def _drop_role_via_recreate(conn) -> None:
    """Fallback dla SQLite <3.35 — przepisanie tabeli user bez kolumny 'role'.

    Buduje nową tabelę z kolumn aktualnego modelu, kopiuje dane i podmienia.
    Wykonujemy to TYLKO gdy ALTER ... DROP COLUMN się nie powiódł.
    """
    from sqlalchemy import text
    import logging
    _mlog = logging.getLogger("szup.migrations")
    try:
        cols = conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()
        keep = [c for c in cols if c[1] != "role"]
        col_defs = []
        for c in keep:
            cid, name, ctype, notnull, dflt, pk = c
            parts = [f'"{name}"', ctype or "TEXT"]
            if pk:
                parts.append("PRIMARY KEY")
            if notnull and not pk:
                parts.append("NOT NULL")
            if dflt is not None:
                parts.append(f"DEFAULT {dflt}")
            col_defs.append(" ".join(parts))
        col_names = ", ".join(f'"{c[1]}"' for c in keep)
        ddl = f'CREATE TABLE "user_new" ({", ".join(col_defs)})'
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(ddl))
        conn.execute(text(f'INSERT INTO "user_new" ({col_names}) SELECT {col_names} FROM "user"'))
        conn.execute(text('DROP TABLE "user"'))
        conn.execute(text('ALTER TABLE "user_new" RENAME TO "user"'))
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_user_username ON "user" (username)'))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
        _mlog.info("Recreated user table without legacy 'role' column")
    except Exception as exc:
        conn.rollback()
        _mlog.error("Failed to drop 'role' column via recreate: %s", exc)


def get_session():
    with Session(engine) as session:
        yield session
