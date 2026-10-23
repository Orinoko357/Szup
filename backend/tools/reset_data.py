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
  - jednostki i wydziały       (unit, department, zastępcy, przypisania HR)
  - systemy, uprawnienia i dostawcy
                               (permissionsystem, systempermission,
                                permissionsystemunit, softwarevendor, vendorcontract)
  - konfiguracja SMTP / LDAP   (emailsettings, ldapsettings)
  - audit log                  (auditlog — triggery są ściągane, założą się
                                ponownie przy starcie backendu)
  - tokeny unieważnione        (revokedtoken)
  - zdarzenia bezpieczeństwa   (securityevent)

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
    "securityevent",
]

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
    from database import _DB_URL, drop_auditlog_triggers, engine
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
    try:
        with engine.begin() as conn:
            existing = {r[0] for r in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'")}

            # 1) Zdejmij append-only triggery z auditlog. Zostaną ponownie
            #    utworzone przy starcie backendu (init_db()).
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
                conn.execute(text(f'DELETE FROM "{table}"'))

            # 4) Zresetuj sekwencje (autoincrement) dla wyczyszczonych tabel.
            #    sqlite_sequence istnieje tylko przy AUTOINCREMENT.
            if "sqlite_sequence" in existing:
                placeholders = ", ".join(f"'{t}'" for t in TABLES_TO_WIPE)
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
    print("  • Triggery append-only na auditlog zostaną odtworzone przy")
    print("    najbliższym starcie backendu (init_db()).")
    print("  • Użytkownikom wyczyszczono pole department_id — przypisz ich")
    print("    ponownie do wydziałów po ich założeniu.")
    print("  • Konta LDAP mają wyczyszczone ldap_dn — przy kolejnym logowaniu")
    print("    przez LDAP binding zostanie odtworzony automatycznie.")
    print()


if __name__ == "__main__":
    main()
