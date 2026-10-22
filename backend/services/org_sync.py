"""
Synchronizacja struktury organizacyjnej z rolą „kierownik" (manager).

Problem: kierownictwo komórki było trzymane w DWÓCH miejscach, które trzeba
było ustawiać ręcznie osobno:
  1. `Department.manager_user_id` (kto kieruje komórką) — plus `DepartmentDeputy`,
  2. rola `manager` w `User.roles` (czy user w ogóle widzi widoki kierownika).

Ten moduł spina je w jedną spójną całość — w obie strony:

  • Struktura → rola:  przypisanie użytkownika jako kierownika (lub zastępcy)
    komórki NADAJE mu rolę `manager`. Zdjęcie z funkcji ODBIERA rolę, o ile
    nie kieruje już żadną inną komórką i nie jest nigdzie zastępcą.

  • Rola → struktura:  gdy użytkownik ma rolę `manager` i jest przypisany do
    komórki (`User.department_id`), a ta komórka NIE MA jeszcze kierownika —
    zostaje jej kierownikiem.

Świadomie NIE nadpisujemy istniejącego kierownika komórki: przypisanie drugiej
osoby z rolą `manager` do komórki, która ma już kierownika, nie „kradnie" mu
funkcji po cichu. Taka zmiana wymaga jawnej edycji w strukturze.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from models import Department, DepartmentDeputy, User, parse_roles, roles_to_json

_log = logging.getLogger("szup.org_sync")


# Słowa w stanowisku (AD `title`) wskazujące, że osoba KIERUJE komórką.
# „kierownicz" łapie kierowniczka/kierownicze; unikamy samego „kier" (kierowca).
MANAGER_TITLE_KEYWORDS = ("kierownik", "kierownicz", "dyrektor", "naczelnik")


def title_indicates_manager(title: str | None) -> bool:
    t = (title or "").lower()
    return any(k in t for k in MANAGER_TITLE_KEYWORDS)


# ---------------------------------------------------------------------------
# Struktura → rola
# ---------------------------------------------------------------------------

def _manages_anything(session: Session, user_id: int) -> bool:
    """True, jeśli user kieruje jakąkolwiek komórką, jest gdzieś zastępcą albo
    jest kierownikiem całej jednostki (`Unit.manager_user_id`)."""
    if session.exec(
        select(Department).where(Department.manager_user_id == user_id)
    ).first():
        return True
    if session.exec(
        select(DepartmentDeputy).where(DepartmentDeputy.user_id == user_id)
    ).first():
        return True
    from models import Unit
    if session.exec(
        select(Unit).where(Unit.manager_user_id == user_id)
    ).first():
        return True
    return False


def sync_after_unit_manager_change(session: Session, old_manager_id: int | None,
                                   new_manager_id: int | None) -> None:
    """Wywołaj po zmianie `Unit.manager_user_id`. Nadaje rolę `manager` nowemu
    kierownikowi jednostki i sprząta rolę po poprzednim (jeśli nic już nie
    prowadzi)."""
    if old_manager_id == new_manager_id:
        if new_manager_id:
            grant_manager_role(session, new_manager_id)
        return
    if new_manager_id:
        grant_manager_role(session, new_manager_id)
    if old_manager_id:
        revoke_manager_role_if_unused(session, old_manager_id)


def grant_manager_role(session: Session, user_id: int | None) -> bool:
    """Nadaje rolę `manager`, jeśli user jej jeszcze nie ma. Zwraca True gdy zmieniono."""
    if not user_id:
        return False
    user = session.get(User, user_id)
    if not user:
        return False
    roles = parse_roles(user.roles)
    if "manager" in roles:
        return False
    roles.append("manager")
    user.roles = roles_to_json(roles)
    session.add(user)
    _log.info("Nadano rolę 'manager' użytkownikowi %s (kierownik w strukturze)", user.username)
    return True


def revoke_manager_role_if_unused(session: Session, user_id: int | None) -> bool:
    """Odbiera rolę `manager`, jeśli user nie kieruje już niczym i nie jest zastępcą.

    Nie rusza kont superadmin/admin ani ról innych niż `manager`.
    """
    if not user_id:
        return False
    user = session.get(User, user_id)
    if not user:
        return False
    roles = parse_roles(user.roles)
    if "manager" not in roles:
        return False
    if _manages_anything(session, user_id):
        return False
    roles = [r for r in roles if r != "manager"]
    # Nie zostawiaj konta zupełnie bez roli — degraduj do podglądu.
    if not roles:
        roles = ["viewer"]
    user.roles = roles_to_json(roles)
    session.add(user)
    _log.info("Odebrano rolę 'manager' użytkownikowi %s (nie kieruje już żadną komórką)",
              user.username)
    return True


def sync_after_manager_change(session: Session, old_manager_id: int | None,
                              new_manager_id: int | None) -> None:
    """Wywołaj po zmianie `Department.manager_user_id` (lub dodaniu/usunięciu zastępcy).

    Nadaje rolę nowemu kierownikowi i sprząta rolę po poprzednim.
    """
    if old_manager_id == new_manager_id:
        # I tak zweryfikuj — komórka mogła zostać usunięta.
        if new_manager_id:
            grant_manager_role(session, new_manager_id)
        return
    if new_manager_id:
        grant_manager_role(session, new_manager_id)
    if old_manager_id:
        revoke_manager_role_if_unused(session, old_manager_id)


# ---------------------------------------------------------------------------
# Rola → struktura
# ---------------------------------------------------------------------------

def release_manager_posts(session: Session, user_id: int | None) -> bool:
    """Wywołaj po ODEBRANIU roli `manager` — zwalnia wszystkie funkcje w strukturze.

    Bez tego komórka miałaby „kierownika", który nie ma już roli kierownika i nie
    wejdzie do panelu — wniosek utknąłby bez osoby zdolnej go obsłużyć.

    Wołane także przy dezaktywacji konta (ręcznej i z importu AD). Zwalnia
    również przejęcia wniosków tej osoby, które wciąż czekają na etapie
    kierownika komórki — wracają do kierownika komórki (z powiadomieniem).
    """
    if not user_id:
        return False
    changed = False
    from services.workflow import release_take_overs_of
    if release_take_overs_of(session, user_id,
                             "Przejmujący stracił stanowisko lub konto zostało wyłączone"):
        changed = True
    for dept in session.exec(
        select(Department).where(Department.manager_user_id == user_id)
    ).all():
        dept.manager_user_id = None
        session.add(dept)
        changed = True
        _log.info("Zwolniono stanowisko kierownika komórki '%s' (odebrano rolę)", dept.name)
    for row in session.exec(
        select(DepartmentDeputy).where(DepartmentDeputy.user_id == user_id)
    ).all():
        session.delete(row)
        changed = True
    from models import Unit
    for unit in session.exec(
        select(Unit).where(Unit.manager_user_id == user_id)
    ).all():
        unit.manager_user_id = None
        session.add(unit)
        changed = True
        _log.info("Zwolniono stanowisko kierownika jednostki '%s' (odebrano rolę)", unit.name)
    return changed


def sync_after_user_change(session: Session, user: User) -> tuple[bool, str | None]:
    """Wywołaj po zmianie ról / komórki użytkownika.

    Gdy user ma rolę `manager` i jest przypisany do komórki BEZ kierownika —
    zostaje jej kierownikiem.

    Zwraca `(zmieniono_strukturę, ostrzeżenie_dla_użytkownika)`. Ostrzeżenie
    pojawia się, gdy stanowisko jest już obsadzone — świadomie NIE podmieniamy
    kierownika po cichu, ale administrator musi się o tym dowiedzieć.
    """
    if not user or not user.department_id or not user.is_active:
        return False, None
    if "manager" not in parse_roles(user.roles):
        return False, None
    dept = session.get(Department, user.department_id)
    if not dept:
        return False, None

    if dept.manager_user_id and dept.manager_user_id != user.id:
        current = session.get(User, dept.manager_user_id)
        who = (current.full_name or current.username) if current else f"id={dept.manager_user_id}"
        return False, (
            f"Komórka „{dept.name}” ma już kierownika ({who}). "
            f"Rola kierownika została nadana, ale stanowisko NIE zostało zmienione. "
            f"Aby zmienić kierownika, edytuj komórkę w strukturze organizacyjnej."
        )

    if dept.manager_user_id == user.id:
        return False, None

    dept.manager_user_id = user.id
    session.add(dept)
    _log.info("Użytkownik %s ustawiony kierownikiem komórki '%s' (miała wolne stanowisko)",
              user.username, dept.name)
    return True, None
