"""
Narzędzie konsolowe — wyczyszczenie bazy danych SZUP z danych operacyjnych.

Co ZOSTAJE:
  - użytkownicy (tabela user)      — z wyczyszczonymi polami department_id
                                     i ldap_dn (bo ich cele przestają istnieć)
  - ustawienia aplikacji (appsettings) — w szczególności flaga test_mode

Co JEST USUWANE:
  - wnioski i ich pozycje      (accessrequest, requestitem)
  - jednostki i wydziały       (unit, department)
  - systemy i uprawnienia      (permissionsystem, systempermission)
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


# Kolejność DELETE musi uwzględniać klucze obce — najpierw dzieci, potem rodzice.
# Przy SQLite z PRAGMA foreign_keys=OFF kolejność nie ma znaczenia funkcjonalnie,
# ale zachowujemy ją dla czytelności i na wypadek gdyby FK były włączone.
TABLES_TO_WIPE = [
    "requestitem",
    "accessrequest",
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

# Triggery append-only na auditlog — trzeba je ściągnąć żeby móc wyczyścić
# tabelę. Zostaną ponownie utworzone przy starcie backendu (init_db()).
AUDITLOG_TRIGGERS = ["auditlog_no_update", "auditlog_no_delete"]


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
    from database import engine, _DB_URL
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
    print(f"  ZACHOWANE:")
    print(f"    user                = {counts.get('user', 0)}")
    print(f"    appsettings         = {counts.get('appsettings', 0)}")
    print(f"  DO WYCZYSZCZENIA:")
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
    with engine.begin() as conn:
        # FK off — pozwala czyścić tabele w dowolnej kolejności.
        conn.exec_driver_sql("PRAGMA foreign_keys = OFF")

        # 1) Zdejmij append-only triggery z auditlog.
        for trg in AUDITLOG_TRIGGERS:
            try:
                conn.execute(text(f'DROP TRIGGER IF EXISTS "{trg}"'))
            except Exception as exc:
                print(f"[!] Nie udało się usunąć triggera {trg}: {exc}")

        # 2) Wyczyść tabele.
        for table in TABLES_TO_WIPE:
            try:
                conn.execute(text(f'DELETE FROM "{table}"'))
            except Exception as exc:
                # Tabela może nie istnieć na bardzo starej bazie — ignorujemy.
                print(f"[!] DELETE FROM {table} pominięty: {exc}")

        # 3) Zresetuj sekwencje (autoincrement) dla wyczyszczonych tabel.
        #    Nie ruszamy sekwencji dla user/appsettings.
        try:
            placeholders = ", ".join(f"'{t}'" for t in TABLES_TO_WIPE)
            conn.execute(text(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})"
            ))
        except Exception:
            # sqlite_sequence nie istnieje jeśli żadna tabela nie miała AUTOINCREMENT;
            # w SZUP używamy INTEGER PRIMARY KEY, więc to normalne.
            pass

        # 4) Wyczyść na userze referencje do usuniętych obiektów.
        #    department_id wskazuje na wykasowaną tabelę department — musimy
        #    zresetować, inaczej UI/scoping będą odwoływać się do nieistniejących
        #    wydziałów.
        try:
            conn.execute(text(
                'UPDATE "user" SET department_id = NULL, ldap_dn = NULL'
            ))
        except Exception as exc:
            print(f"[!] UPDATE user pominięty: {exc}")

        conn.exec_driver_sql("PRAGMA foreign_keys = ON")

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
