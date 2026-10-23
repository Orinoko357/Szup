"""
Narzędzie konsolowe — reset hasła użytkownika (domyślnie superadmin).

Użycie:
  python -m tools.reset_password
  python -m tools.reset_password --username jan.kowalski
  python -m tools.reset_password --username jan.kowalski --password "NoweSilneHaslo1!"

Uruchamiać z katalogu backend/ z aktywnym virtualenv:
  cd /opt/szup/backend
  source /opt/szup/venv/bin/activate
  python -m tools.reset_password
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# Dodaj backend/ do PYTHONPATH żeby importy działały bez instalacji pakietu
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SZUP_DATA_DIR", "/opt/szup/data")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset hasła użytkownika SZUP")
    parser.add_argument("--username", default=None,
                        help="Login użytkownika (domyślnie: pierwszy superadmin)")
    parser.add_argument("--password", default=None,
                        help="Nowe hasło (jeśli nie podano — zapyta interaktywnie)")
    parser.add_argument("--force-change", action="store_true",
                        help="Wymagaj zmiany hasła przy następnym logowaniu")
    args = parser.parse_args()

    # ------------------------------------------------------------------ import
    from database import engine, init_db
    from models import User, parse_roles
    from services.auth_service import hash_password, validate_password_strength
    from sqlmodel import Session, select

    init_db()

    with Session(engine) as session:
        # Znajdź użytkownika
        if args.username:
            user = session.exec(
                select(User).where(User.username == args.username)
            ).first()
            if not user:
                print(f"[BŁĄD] Użytkownik '{args.username}' nie istnieje.")
                sys.exit(1)
        else:
            # Domyślnie: pierwszy superadmin
            user = session.exec(
                select(User).where(User.roles.like('%"superadmin"%'))
            ).first()
            if not user:
                print("[BŁĄD] Nie znaleziono żadnego konta superadmin.")
                sys.exit(1)

        if user.auth_type.value == "ldap":
            print(f"[BŁĄD] Konto '{user.username}' jest kontem LDAP — "
                  "hasło zarządza Active Directory.")
            sys.exit(1)

        roles_str = ", ".join(parse_roles(user.roles))
        print(f"\nUżytkownik  : {user.username}")
        print(f"Imię/nazwisko: {user.full_name or '—'}")
        print(f"Role        : {roles_str}")
        print(f"Aktywny     : {'tak' if user.is_active else 'NIE'}")
        print()

        # Pobierz/zwaliduj nowe hasło
        if args.password:
            new_password = args.password
        else:
            print("Polityka haseł: min. 12 znaków, co najmniej 3 z 4 klas")
            print("(małe litery, WIELKIE, cyfry, znaki specjalne).")
            print()
            while True:
                new_password = getpass.getpass("Nowe hasło        : ")
                confirm      = getpass.getpass("Potwierdź hasło   : ")
                if new_password != confirm:
                    print("[!] Hasła nie są identyczne. Spróbuj ponownie.\n")
                    continue
                try:
                    validate_password_strength(new_password)
                    break
                except Exception as exc:
                    print(f"[!] {exc}\n")

        # Walidacja jeszcze raz (gdy podano przez --password)
        try:
            validate_password_strength(new_password)
        except Exception as exc:
            print(f"[BŁĄD] Hasło nie spełnia wymagań: {exc}")
            sys.exit(1)

        # Zapisz
        from datetime import datetime
        from services.auth_service import invalidate_tokens_now
        user.password_hash         = hash_password(new_password)
        user.password_changed_at   = datetime.utcnow()
        user.must_change_password  = args.force_change
        user.failed_login_count    = 0
        user.locked_until          = None
        # Unieważnij wszystkie dotychczasowe tokeny JWT konta (pełna sekunda —
        # token z logowania zaraz po resecie pozostaje ważny).
        invalidate_tokens_now(user)

        session.add(user)
        session.commit()

        print(f"\n[OK] Hasło użytkownika '{user.username}' zostało zmienione.")
        if user.must_change_password:
            print("     Użytkownik będzie musiał zmienić hasło przy pierwszym logowaniu.")
        else:
            print("     Użytkownik może zalogować się nowym hasłem bez wymuszonej zmiany.")
        print()


if __name__ == "__main__":
    main()
