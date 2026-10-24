"""
Narzędzie konsolowe — wyczyszczenie bazy danych SZUP z danych operacyjnych.

Co ZOSTAJE:
  - użytkownicy (tabela user)      — z wyczyszczonymi polami department_id
                                     i ldap_dn (bo ich cele przestają istnieć)
  - ustawienia aplikacji (appsettings) — w szczególności flaga test_mode

Co JEST USUWANE:
  - wnioski z pozycjami, obiegiem, historią i oświadczeniami
                               (accessrequest, requestitem, workflowinstance,
                                workflowstep, requestevent, permissiondeclaration)
  - zmiany nazwiska i migawki  (namechangerequest, permissionsnapshot)
  - jednostki i wydziały       (unit, department, zastępcy, dawne przypisania
                                jednostek kadr — userunit)
  - systemy, uprawnienia i dostawcy
                               (permissionsystem, systempermission,
                                permissionsystemunit, softwarevendor, vendorcontract)
  - konfiguracja SMTP / LDAP   (emailsettings, ldapsettings)
  - audit log i zdarzenia bezpieczeństwa (auditlog, securityevent) — WYŁĄCZNIE
                               wpisy starsze niż obowiązkowa retencja
                               (24 miesiące, jak czyszczenie w aplikacji);
                               triggery append-only auditlog są zdejmowane
                               i zakładane ponownie w tej samej transakcji
  - tokeny unieważnione        (revokedtoken), aktywność sesji (sessionactivity)
                               i licznik prób hasła (passwordconfirmfailure)

  WYJĄTEK: ślady czyszczeń dzienników i resetów fabrycznych (audit.purged,
  security.purged, settings.factory_reset) zostają w auditlog i securityevent —
  są nieusuwalne (tak samo jak w resecie fabrycznym z aplikacji).

  ŚLAD: w tej samej transakcji powstaje wpis `settings.factory_reset`
  w auditlog i zdarzenie krytyczne (source="tools") — nie ma czyszczenia
  bez śladu.

Użycie:
  cd /opt/szup/backend
  source /opt/szup/venv/bin/activate
  python -m tools.reset_data              # zapyta o potwierdzenie
  python -m tools.reset_data --yes        # bez pytania (do skryptów)
  python -m tools.reset_data --dry-run    # pokaż co zostałoby zrobione

UWAGA: operacja jest nieodwracalna. Zrób kopię pliku bazy przed uruchomieniem:
  cp /opt/szup/data/szup.db /opt/szup/data/szup.db.bak-$(date +%F)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Dodaj backend/ do PYTHONPATH żeby importy działały bez instalacji pakietu
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SZUP_DATA_DIR", "/opt/szup/data")


# Kolejność DELETE uwzględnia klucze obce — najpierw dzieci, potem rodzice.
# Klucze obce są WŁĄCZONE (PRAGMA foreign_keys w otwartej transakcji nic nie
# zmienia), więc pominięta tabela-dziecko przerwie całą operację, zamiast
# zostawić osierocone rekordy przypięte potem do nowych wniosków.
TABLES_TO_WIPE = [
    "requestevent",
    "permissiondeclaration",
    "workflowstep",
    "workflowinstance",
    "requestitem",
    "accessrequest",
    "namechangerequest",
    "permissionsnapshot",
    "departmentdeputy",
    "userunit",
    "permissionsystemunit",
    "systempermission",
    "permissionsystem",
    "vendorcontract",
    "softwarevendor",
    "department",
    "unit",
    "emailsettings",
    "ldapsettings",
    "auditlog",
    "revokedtoken",
    "passwordconfirmfailure",
    "sessionactivity",
    "securityevent",
]

# Tabele dzienników: ślady czyszczeń zostają (kolumna klucza → warunek).
LOG_KEY_COLUMNS = {"auditlog": "action", "securityevent": "event_type"}

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wyczyść bazę SZUP zachowując użytkowników i ustawienia aplikacji."
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Nie pytaj o potwierdzenie (do automatyzacji).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Pokaż co zostałoby zrobione, bez modyfikowania bazy.")
    args = parser.parse_args()

    # ------------------------------------------------------------------ import
    import getpass
    import json
    from datetime import datetime
    from database import _DB_URL, _log_trigger_sql, AUDITLOG_TRIGGERS, \
        drop_auditlog_triggers, engine
    from services.audit import PURGE_TRACE_ACTIONS, RETENTION_MONTHS, retention_limit
    from sqlalchemy import text

    print(f"Baza danych : {_DB_URL}")
    print()

    # --------------------------------------------------------------- podsumowanie
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in ["user", "appsettings", *TABLES_TO_WIPE]:
            try:
                row = conn.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                counts[table] = int(row[0]) if row else 0
            except Exception:
                counts[table] = -1  # tabela nie istnieje lub inny błąd

    print("Stan bazy przed operacją:")
    print("  ZACHOWANE:")
    print(f"    user                = {counts.get('user', 0)}")
    print(f"    appsettings         = {counts.get('appsettings', 0)}")
    print("  DO WYCZYSZCZENIA:")
    for t in TABLES_TO_WIPE:
        n = counts.get(t, 0)
        if n < 0:
            continue
        print(f"    {t:20s}= {n}")
    print()

    # Pokaż test_mode (jedna z rzeczy, które chcemy zachować)
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql(
                'SELECT id, test_mode FROM "appsettings" LIMIT 1'
            ).fetchone()
            if row:
                print(f"Zachowany tryb testowy: test_mode = "
                      f"{'WŁĄCZONY' if row[1] else 'wyłączony'}")
            else:
                print("Zachowany tryb testowy: (brak rekordu appsettings)")
    except Exception as exc:
        print(f"[!] Nie udało się odczytać appsettings: {exc}")
    print()

    if args.dry_run:
        print("[DRY-RUN] Żadna zmiana nie została zapisana.")
        return

    # ------------------------------------------------------------- potwierdzenie
    if not args.yes:
        print("UWAGA: operacja jest NIEODWRACALNA. Upewnij się, że masz kopię bazy.")
        reply = input("Wpisz 'TAK' aby kontynuować: ").strip()
        if reply != "TAK":
            print("Przerwano.")
            return

    # -------------------------------------------------------------- wykonanie
    # Całość w jednej transakcji: błąd na którejkolwiek tabeli wycofuje wszystko
    # (także zdjęcie triggerów — DDL w SQLite podlega transakcji).
    cutoff = retention_limit()
    cutoff_sql = cutoff.strftime("%Y-%m-%d %H:%M:%S.%f")
    log_time_columns = {"auditlog": "timestamp", "securityevent": "created_at"}
    deleted: dict[str, int] = {}
    try:
        with engine.begin() as conn:
            existing = {r[0] for r in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'")}

            # 1) Zdejmij append-only triggery z auditlog — wracają w kroku 3b,
            #    w tej samej transakcji.
            for trg, exc in drop_auditlog_triggers(conn):
                print(f"[!] Nie udało się usunąć triggera {trg}: {exc}")

            # 2) Odepnij od usuwanych obiektów rekordy, które zostają.
            #    department_id/ldap_dn użytkownika wskazywałyby nieistniejące cele.
            conn.execute(text('UPDATE "user" SET department_id = NULL, ldap_dn = NULL'))
            conn.execute(text('UPDATE "department" SET parent_dept_id = NULL'))

            # 3) Wyczyść tabele (pomijamy tylko te, których na starej bazie nie ma).
            for table in TABLES_TO_WIPE:
                if table not in existing:
                    print(f"[i] Tabela {table} nie istnieje — pominięta.")
                    continue
                if table in LOG_KEY_COLUMNS:
                    # Obowiązkowa retencja: tylko wpisy starsze niż 24 miesiące.
                    keep = ", ".join("'" + a.replace("'", "''") + "'"
                                     for a in PURGE_TRACE_ACTIONS)
                    res = conn.execute(text(
                        f'DELETE FROM "{table}" '
                        f"WHERE COALESCE({LOG_KEY_COLUMNS[table]}, '') NOT IN ({keep}) "
                        f'AND "{log_time_columns[table]}" < :cutoff'),
                        {"cutoff": cutoff_sql})
                else:
                    res = conn.execute(text(f'DELETE FROM "{table}"'))
                if res.rowcount:
                    deleted[table] = int(res.rowcount)

            # 3b) Ochrona append-only auditlog wraca od razu (ta sama transakcja).
            trg_sql = _log_trigger_sql()
            for trg in AUDITLOG_TRIGGERS:
                conn.execute(text(f'DROP TRIGGER IF EXISTS "{trg}"'))
                conn.execute(text(trg_sql[trg]))

            # 3c) Ślad operacji — wpis audytu i zdarzenie krytyczne.
            try:
                operator = getpass.getuser()
            except Exception:  # noqa: BLE001
                operator = None
            trace = {"source": "tools", "tool": "tools/reset_data.py",
                     "os_user": operator, "deleted": deleted,
                     "audit_retention_months": RETENTION_MONTHS,
                     "audit_cutoff": cutoff.isoformat()}
            payload = json.dumps(trace, ensure_ascii=False, default=str)
            now_sql = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
            conn.execute(text(
                'INSERT INTO "auditlog" (timestamp, user_id, username, action, '
                'target_type, details) VALUES (:t, NULL, :u, :a, :tt, :d)'),
                {"t": now_sql, "u": f"tools:{operator or '?'}",
                 "a": "settings.factory_reset", "tt": "database", "d": payload})
            conn.execute(text(
                'INSERT INTO "securityevent" (created_at, event_type, severity, source, '
                'summary, details) VALUES (:t, :e, :s, :src, :sum, :d)'),
                {"t": now_sql, "e": "settings.factory_reset", "s": "critical",
                 "src": "tools",
                 "sum": (f"Wyczyszczono bazę narzędziem tools/reset_data.py "
                         f"(konto systemowe: {operator or 'nieznane'}); dzienniki — tylko "
                         f"wpisy starsze niż {RETENTION_MONTHS} miesiące"),
                 "d": payload})

            # 4) Zresetuj sekwencje (autoincrement) dla wyczyszczonych tabel.
            #    sqlite_sequence istnieje tylko przy AUTOINCREMENT.
            if "sqlite_sequence" in existing:
                # Bez dzienników — zachowane ślady mają swoje id.
                placeholders = ", ".join(f"'{t}'" for t in TABLES_TO_WIPE
                                         if t not in LOG_KEY_COLUMNS)
                conn.execute(text(
                    f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})"))
    except Exception as exc:
        print(f"[BŁĄD] Czyszczenie przerwane, żadne dane nie zostały usunięte: {exc}")
        sys.exit(1)

    # 5) VACUUM — odzyskaj miejsce w pliku bazy. Musi być poza transakcją.
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
    except Exception as exc:
        print(f"[!] VACUUM pominięty: {exc}")

    # ------------------------------------------------------------ podsumowanie
    print()
    print("[OK] Baza wyczyszczona.")
    print()
    print("Uwagi:")
    print("  • Triggery append-only na auditlog zostały odtworzone; ślad operacji")
    print("    (settings.factory_reset, source=tools) zapisano w dziennikach.")
    print(f"  • Wpisy dzienników z ostatnich {RETENTION_MONTHS} miesięcy zostały zachowane.")
    print("  • Użytkownikom wyczyszczono pole department_id — przypisz ich")
    print("    ponownie do wydziałów po ich założeniu.")
    print("  • Konta LDAP mają wyczyszczone ldap_dn — przy kolejnym logowaniu")
    print("    przez LDAP binding zostanie odtworzony automatycznie.")
    print()


if __name__ == "__main__":
    main()
