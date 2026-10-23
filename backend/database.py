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
    # Rejestracja tabel w metadanych — bez tego create_all nie utworzy nic, gdy
    # wołający (np. narzędzie z tools/) nie zaimportował wcześniej `models`.
    import importlib
    importlib.import_module("models")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    _install_auditlog_triggers()
    _seed_default_workflow()
    _backfill_admin_permissions()
    _migrate_custom_fields_to_permissions()
    _strip_hr_role()


def _strip_hr_role() -> list[str]:
    """v3.9 — usunięcie roli „hr” z kont (rola zniesiona).

    Zdolność kadrową daje teraz wyłącznie przynależność do komórki kadrowej
    (Department.is_hr). Konta z zapisaną rolą „hr” tracą ją; jeśli nie są
    w komórce kadrowej, tracą też dostęp do funkcji kadr. Lista loginów trafia
    do audit logu (`user.hr_role_removed`) i do logu aplikacji — administrator
    przenosi te osoby do komórki kadrowej albo oznacza ich komórkę jako kadrową.
    Idempotentne: przy kolejnym starcie nie ma już czego usuwać. Zwraca loginy.
    """
    import json
    import logging
    from sqlmodel import Session, select
    from models import User, Department

    _mlog = logging.getLogger("szup.migrations")
    affected: list[dict] = []
    with Session(engine) as session:
        hr_dept_ids = {d.id for d in session.exec(
            select(Department).where(Department.is_hr == True)).all()}  # noqa: E712
        for u in session.exec(select(User)).all():
            try:
                stored = json.loads(u.roles or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(stored, list) or "hr" not in stored:
                continue
            remaining = [r for r in stored if r != "hr"] or ["viewer"]
            u.roles = json.dumps(remaining)
            session.add(u)
            affected.append({"username": u.username,
                             "in_hr_department": u.department_id in hr_dept_ids})
        if not affected:
            return []
        session.commit()
        lost = sorted(a["username"] for a in affected if not a["in_hr_department"])
        from services.audit import record_event
        record_event(session, action="user.hr_role_removed", target_type="user",
                     username="system", details={
                         "reason": "Rola „hr” zniesiona — zdolność kadrową daje "
                                   "przynależność do komórki kadrowej",
                         "usernames": sorted(a["username"] for a in affected),
                         "lost_hr_capability": lost,
                     })
    _mlog.warning("Usunięto rolę „hr” z %d kont(a): %s. Bez dostępu do funkcji kadr "
                  "(nie należą do komórki kadrowej): %s", len(affected),
                  ", ".join(sorted(a["username"] for a in affected)),
                  ", ".join(lost) or "brak")
    return sorted(a["username"] for a in affected)


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


# Triggery wymuszające append-only na tabeli auditlog.
AUDITLOG_TRIGGERS = ("auditlog_no_update", "auditlog_no_delete")

# Triggery chroniące ślady czyszczeń w tabeli securityevent (3.10). Zwykłe
# zdarzenia można zamykać i czyścić, ale wierszy-śladów (`audit.purged`,
# `security.purged`, `settings.factory_reset`) nie da się usunąć ani zmienić —
# wolno tylko je zamknąć (kolumny resolved_*).
SECURITYEVENT_TRIGGERS = ("securityevent_trace_no_update", "securityevent_trace_no_delete")


def _log_trigger_sql() -> dict[str, str]:
    """{nazwa: CREATE TRIGGER} — triggery append-only dzienników."""
    from services.audit import PURGE_TRACE_ACTIONS
    traces = ", ".join("'" + t.replace("'", "''") + "'" for t in PURGE_TRACE_ACTIONS)
    return {
        "auditlog_no_update":
            "CREATE TRIGGER auditlog_no_update "
            "BEFORE UPDATE ON auditlog BEGIN "
            "SELECT RAISE(ABORT, 'auditlog is append-only'); END",
        "auditlog_no_delete":
            "CREATE TRIGGER auditlog_no_delete "
            "BEFORE DELETE ON auditlog BEGIN "
            "SELECT RAISE(ABORT, 'auditlog is append-only'); END",
        "securityevent_trace_no_update":
            "CREATE TRIGGER securityevent_trace_no_update "
            "BEFORE UPDATE OF created_at, event_type, severity, source, summary, "
            "details, user_id, ip ON securityevent "
            f"WHEN old.event_type IN ({traces}) BEGIN "
            "SELECT RAISE(ABORT, 'securityevent purge traces are append-only'); END",
        "securityevent_trace_no_delete":
            "CREATE TRIGGER securityevent_trace_no_delete "
            f"BEFORE DELETE ON securityevent WHEN old.event_type IN ({traces}) BEGIN "
            "SELECT RAISE(ABORT, 'securityevent purge traces are append-only'); END",
    }


def drop_auditlog_triggers(conn) -> list[tuple[str, Exception]]:
    """Zdejmij triggery append-only z auditlog (przed czyszczeniem tabeli).

    `conn` to sesja albo połączenie SQLAlchemy — zdejmowanie dzieje się w jego
    transakcji. Zwraca listę (trigger, wyjątek) dla tych, których nie udało się
    usunąć. Triggery odtwarza `_install_auditlog_triggers()` (także przy starcie).
    """
    from sqlalchemy import text
    failed: list[tuple[str, Exception]] = []
    for trg in AUDITLOG_TRIGGERS:
        try:
            conn.execute(text(f'DROP TRIGGER IF EXISTS "{trg}"'))
        except Exception as exc:
            failed.append((trg, exc))
    return failed


def _install_auditlog_triggers():
    """Zakłada (albo odświeża) triggery append-only: auditlog oraz ochronę
    śladów czyszczeń w securityevent. Trigger o innej treści niż oczekiwana
    (np. po zmianie listy śladów w nowej wersji) jest zakładany od nowa.
    Woła to `init_db()` przy każdym starcie, czyszczenie dzienników i reset
    fabryczny. Błąd nie przechodzi po cichu — trafia do logu."""
    import logging
    from sqlalchemy import text
    log = logging.getLogger("szup.migrations")
    expected = _log_trigger_sql()
    with engine.connect() as conn:
        present = {r[0]: r[1] for r in conn.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger'").fetchall()}
        for name, sql in expected.items():
            if present.get(name) == sql:
                continue
            try:
                if name in present:
                    conn.execute(text(f'DROP TRIGGER IF EXISTS "{name}"'))
                conn.execute(text(sql))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                log.error("Nie udało się założyć triggera append-only %s: %s", name, exc)


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
        ("department",    "is_hr",          "BOOLEAN DEFAULT 0"),
        ("accessrequest", "employment_from", "DATE"),
        ("accessrequest", "work_until",      "DATE"),
        ("unit",          "description",     "VARCHAR"),
        ("department",    "description",     "VARCHAR"),
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
        ("user",          "title",           "VARCHAR DEFAULT ''"),
        ("requestitem",   "denied",          "BOOLEAN DEFAULT 0"),
        ("requestitem",   "deny_comment",    "VARCHAR"),
        ("requestitem",   "denied_by_user_id", "INTEGER"),
        ("requestitem",   "denied_at",       "DATETIME"),
        ("systempermission", "subgroup_name",  "VARCHAR"),
        ("systempermission", "subgroup_order", "INTEGER"),
        ("systempermission", "input_prompt",   "VARCHAR"),
        ("requestitem",   "fulfilled",       "BOOLEAN DEFAULT 0"),
        ("requestitem",   "fulfilled_by_user_id", "INTEGER"),
        ("requestitem",   "fulfilled_at",    "DATETIME"),
        ("ldapsettings",  "sso_enabled",     "BOOLEAN DEFAULT 0"),
        ("ldapsettings",  "sso_auto",        "BOOLEAN DEFAULT 0"),
        # Weryfikacja certyfikatu LDAPS / STARTTLS (3.8)
        ("ldapsettings",  "tls_verify",      "BOOLEAN DEFAULT 1"),
        ("ldapsettings",  "ca_cert_file",    "VARCHAR DEFAULT NULL"),
        ("ldapsettings",  "use_starttls",    "BOOLEAN DEFAULT 0"),
        ("ldapsettings",  "allow_insecure",  "BOOLEAN DEFAULT 0"),
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
        # Obieg papierowy PDF/EZD (usunięty) — kolumny zostają dla starszych baz
        ("workflowinstance", "pending_pdf_at",         "DATETIME"),
        ("workflowinstance", "pending_ezd_confirmed",  "BOOLEAN DEFAULT 0"),
        ("workflowinstance", "pending_pdf_by_user_id", "INTEGER"),
        ("workflowinstance", "pending_ezd_by_user_id", "INTEGER"),
        # Wersje robocze kierownika i przejęcie wniosku przez przełożonego
        ("accessrequest",    "draft_saved_at",      "DATETIME DEFAULT NULL"),
        ("accessrequest",    "taken_over_by_id",    "INTEGER DEFAULT NULL"),
        ("accessrequest",    "taken_over_by_name",  "VARCHAR DEFAULT NULL"),
        ("accessrequest",    "taken_over_at",       "DATETIME DEFAULT NULL"),
        # Typ bieżącego węzła obiegu (filtr widoczności etapu kierownika w SQL)
        ("accessrequest",    "current_node_type",   "VARCHAR DEFAULT NULL"),
        # Archiwizacja komórki i miękkie usunięcie uprawnień (superadmin, 3.9)
        ("department",       "archived_at",         "DATETIME DEFAULT NULL"),
        ("department",       "archived_reason",     "VARCHAR DEFAULT NULL"),
        ("systempermission", "deleted_at",          "DATETIME DEFAULT NULL"),
        ("systempermission", "deleted_reason",      "VARCHAR DEFAULT NULL"),
        # objectGUID konta z AD — weryfikacja zmiany loginu (3.10)
        ("user",             "ldap_guid",           "VARCHAR DEFAULT NULL"),
        # Odebranie pozycji przy usunięciu grupy uprawnień (3.10)
        ("requestitem",      "revoked_by_request_id", "INTEGER DEFAULT NULL"),
    ]
    from sqlalchemy import text
    with engine.connect() as conn:
        # Zabezpieczenia LDAP (3.8) na istniejącej instalacji: zachowujemy dotychczasowe
        # działanie (bez weryfikacji certyfikatu, LDAP bez SSL dozwolony), żeby
        # wdrożenie nie odcięło logowania AD. Lista kontrolna ostrzega, a superadmin
        # włącza weryfikację po wskazaniu pliku CA. Nowe instalacje: bezpieczne domyślne.
        ldap_cols_before = _table_columns(conn, "ldapsettings")
        for table, column, col_def in simple_migrations:
            _add_column(conn, table, column, col_def, _mlog)
        if ldap_cols_before and "tls_verify" not in ldap_cols_before:
            res = conn.execute(text('UPDATE "ldapsettings" SET tls_verify = 0'))
            conn.commit()
            # Bez skonfigurowanego LDAP (pusta tabela) nie ma czego ostrzegać.
            if res.rowcount:
                _mlog.warning("LDAP: weryfikacja certyfikatu wyłączona dla istniejącej "
                              "instalacji — włącz ją w Ustawieniach po wskazaniu pliku CA")
        if ldap_cols_before and "allow_insecure" not in ldap_cols_before:
            conn.execute(text('UPDATE "ldapsettings" SET allow_insecure = 1 '
                              'WHERE COALESCE(use_ssl, 0) = 0'))
            conn.commit()

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

        try:
            conn.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_accessrequest_current_node_type '
                'ON "accessrequest" (current_node_type)'
            ))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _mlog.warning("Nie udało się utworzyć ix_accessrequest_current_node_type: %s", exc)

        try:
            conn.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_user_ldap_guid ON "user" (ldap_guid)'))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _mlog.warning("Nie udało się utworzyć ix_user_ldap_guid: %s", exc)

        # Indeksy kolumn dodanych migracją (świeża baza ma je z modelu) — 3.9/3.10.
        for ix_name, table, column in (
            ("ix_department_archived_at", "department", "archived_at"),
            ("ix_systempermission_deleted_at", "systempermission", "deleted_at"),
            ("ix_requestitem_revoked_by_request_id", "requestitem", "revoked_by_request_id"),
        ):
            try:
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS {ix_name} ON "{table}" ({column})'))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                _mlog.warning("Nie udało się utworzyć %s: %s", ix_name, exc)

        _backfill_current_node_type(conn, _mlog)

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
        except Exception as exc:
            conn.rollback()
            _mlog.warning("Uzupełnienie accessrequest.worker_user_id pominięte: %s", exc)

        # Migracja: single role → roles JSON array
        # Dodaj kolumnę roles jeśli nie istnieje
        cols = [r[1] for r in conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()]
        if "roles" not in cols:
            _add_column(conn, "user", "roles", "TEXT", _mlog)
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
                # Bez usunięcia kolumny INSERT-y nowego modelu nie przejdą (NOT NULL),
                # więc przerywamy start z jasną przyczyną. SQLite ≥3.35 (2021)
                # obsługuje DROP COLUMN — starsza wersja wymaga aktualizacji systemu.
                raise MigrationError(
                    f"Nie udało się usunąć przestarzałej kolumny user.role: {exc}. "
                    "Wymagany SQLite 3.35 lub nowszy.") from exc


class MigrationError(RuntimeError):
    """Migracja schematu nie powiodła się — start aplikacji jest przerywany."""


def _table_columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()}


def _add_column(conn, table: str, column: str, col_def: str, _mlog) -> None:
    """Idempotentne `ALTER TABLE … ADD COLUMN`.

    Kolumnę, która już istnieje, pomijamy. Błąd ALTER nie przechodzi po cichu:
    po próbie sprawdzamy `PRAGMA table_info` i jeśli kolumny nadal brak, logujemy
    błąd i rzucamy `MigrationError` — aplikacja nie wystartuje na niepełnym
    schemacie (inaczej pierwsze zapytanie o tę kolumnę wywróciłoby się dopiero
    w trakcie pracy, np. przy liście wniosków)."""
    from sqlalchemy import text
    if column in _table_columns(conn, table):
        return
    error: Exception | None = None
    try:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {col_def}'))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        error = exc
    if column not in _table_columns(conn, table):
        _mlog.error("Migracja nieudana: brak kolumny %s.%s po ALTER TABLE (%s)",
                    table, column, error or "brak błędu sterownika")
        raise MigrationError(f"Nie udało się dodać kolumny {table}.{column}: {error}")
    _mlog.info("Dodano kolumnę %s.%s", table, column)


def _backfill_current_node_type(conn, _mlog) -> None:
    """Uzupełnia `accessrequest.current_node_type` dla wniosków w toku.

    Kolumna (3.5) jest kopią bieżącego węzła aktywnej instancji obiegu,
    utrzymywaną odtąd przez silnik. Na bazach sprzed migracji wyliczamy ją raz
    z zamrożonego grafu instancji. Idempotentne — dotyka tylko wierszy z NULL.

    Na koniec (niezależnie od /settings/health) ostrzegamy w logu, jeśli jakaś
    aktywna instancja nadal ma pusty typ węzła — lista wniosków ukrywa wtedy
    taki wniosek w komórkach z etapem kierownika (patrz
    `services.workflow.manager_stage_hidden_clause`).
    """
    import json
    from sqlalchemy import text
    try:
        rows = conn.execute(text(
            'SELECT wi.request_id, wi.template_snapshot, wi.current_node_id '
            'FROM "workflowinstance" wi JOIN "accessrequest" ar ON ar.id = wi.request_id '
            "WHERE wi.status = 'active' AND ar.current_node_type IS NULL "
            'AND wi.current_node_id IS NOT NULL'
        )).fetchall()
        for request_id, snapshot, node_id in rows:
            try:
                graph = json.loads(snapshot)
                ntype = next((n.get("type") for n in graph.get("nodes", [])
                              if n.get("id") == node_id), None)
            except Exception:
                ntype = None
            if ntype:
                conn.execute(text(
                    'UPDATE "accessrequest" SET current_node_type = :t WHERE id = :id'
                ), {"t": ntype, "id": request_id})
        conn.commit()
    except Exception as exc:
        conn.rollback()
        _mlog.warning("Backfill accessrequest.current_node_type nie powiódł się: %s", exc)
    _warn_missing_current_node_type(conn, _mlog)


def _warn_missing_current_node_type(conn, _mlog) -> int:
    """Liczba aktywnych instancji obiegu, których wniosek ma pusty
    `current_node_type` (z ostrzeżeniem w logu, gdy > 0)."""
    from sqlalchemy import text
    try:
        missing = conn.execute(text(
            'SELECT COUNT(*) FROM "workflowinstance" wi '
            'JOIN "accessrequest" ar ON ar.id = wi.request_id '
            "WHERE wi.status = 'active' AND ar.current_node_type IS NULL"
        )).scalar() or 0
    except Exception as exc:
        conn.rollback()
        _mlog.warning("Nie udało się sprawdzić accessrequest.current_node_type: %s", exc)
        return 0
    if missing:
        _mlog.warning(
            "%d wniosek(-ów) w toku ma pusty current_node_type (uszkodzony graf "
            "instancji?) — lista wniosków ukrywa je w komórkach z etapem "
            "kierownika. Sprawdź instancje obiegu tych wniosków.", missing)
    return missing


def get_session():
    with Session(engine) as session:
        yield session
