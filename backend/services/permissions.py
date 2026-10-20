"""
Role/permission helpers dla SZUP.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlmodel import Session

from database import get_session
from models import User, has_role
from services.auth_service import get_current_user


def user_is_hr(session: Session, user: User) -> bool:
    """Zdolność HR: rola 'hr'/'superadmin' ALBO przynależność do komórki
    oznaczonej jako KADROWA (Department.is_hr). Dzięki temu nie trzeba nadawać
    roli HR per osoba — wystarczy oznaczyć komórkę."""
    if has_role(user, "superadmin", "hr"):
        return True
    dept_id = getattr(user, "department_id", None)
    if dept_id:
        from models import Department
        d = session.get(Department, dept_id)
        if d and getattr(d, "is_hr", False):
            return True
    return False


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "superadmin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tylko superadmin może wykonać tę operację")
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "superadmin", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wymagane uprawnienia administratora")
    return current_user


# Rozdział obowiązków (Wariant A): bramki OPERACYJNE nie wpuszczają zwykłego
# administratora — administrator KONFIGURUJE system, a nie działa operacyjnie.
# Superadmin pozostaje break-glass (może wszystko). Kto ma działać operacyjnie,
# dostaje właściwą rolę operacyjną (hr / manager / it_staff).
def require_hr(current_user: User = Depends(get_current_user),
               session: Session = Depends(get_session)) -> User:
    if not user_is_hr(session, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Wymagana rola HR lub przynależność do komórki kadrowej")
    return current_user


def require_manager(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "superadmin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wymagana rola kierownika")
    return current_user


# UWAGA: require_it_staff celowo WPUSZCZA admina — chroni m.in. rejestr
# oprogramowania (katalog systemów/uprawnień), którym administrator współzarządza.
# Operacyjny krok IT w obiegu (it_execute) i tak egzekwuje `can_act` (bez admina).
def require_it_staff(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "superadmin", "admin", "it_staff"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wymagana rola pracownika IT")
    return current_user


def is_admin(user: User) -> bool:
    return has_role(user, "superadmin", "admin")


def managed_dept_ids(session, user: "User") -> tuple[list[int], list[int]]:
    """
    Zwraca (direct_ids, escalated_ids) — wydziały, w których user pełni
    rolę kierownika:
      - direct_ids   — kierownik bezpośredni (Department.manager_user_id == user.id)
                       LUB zastępca (DepartmentDeputy.user_id == user.id).
      - escalated_ids — kierownik wydziału NADRZĘDNEGO dla subwydziałów
                        z flagą requires_higher_approval=True (2-stopniowo);
                        obejmuje też komórki gdzie user jest zastępcą wydziału
                        nadrzędnego.
    """
    from sqlmodel import select
    from models import Department, DepartmentDeputy

    direct = session.exec(
        select(Department).where(Department.manager_user_id == user.id)
    ).all()
    direct_ids = set(d.id for d in direct)

    # Zastępcy — pełne uprawnienia kierownika w tej komórce.
    deputy_of = session.exec(
        select(DepartmentDeputy.department_id).where(DepartmentDeputy.user_id == user.id)
    ).all()
    direct_ids.update(int(x) for x in deputy_of)

    direct_ids_list = sorted(direct_ids)
    escalated_ids: list[int] = []
    if direct_ids_list:
        esc = session.exec(
            select(Department)
            .where(Department.parent_dept_id.in_(direct_ids_list))
            .where(Department.requires_higher_approval == True)  # noqa: E712
        ).all()
        escalated_ids = [d.id for d in esc]

    # Samodzielne stanowiska (kind="standalone") i komórki BEZ kierownika
    # „podlegają" najbliższemu kierownikowi wyżej — doliczamy je do zakresu
    # tego kierownika (widzi ich pracowników, zatwierdza i składa za nich wnioski).
    if direct_ids:
        direct_set = set(direct_ids)
        inherited: list[int] = []
        for d in session.exec(select(Department)).all():
            if d.id in direct_set:
                continue
            if d.kind == "standalone" or not d.manager_user_id:
                resp = effective_manager_dept(session, d)
                if resp and resp.id in direct_set:
                    inherited.append(d.id)
        if inherited:
            direct_ids_list = sorted(direct_set | set(inherited))
    return direct_ids_list, escalated_ids


def effective_manager_dept(session, dept):
    """Komórka, której kierownik faktycznie ODPOWIADA za `dept`.

    Dla samodzielnego stanowiska (kind="standalone") albo komórki bez kierownika
    wspinamy się po rodzicach do najbliższej komórki, która NIE jest samodzielnym
    stanowiskiem i MA kierownika. Zwraca `Department` albo None (brak w górę)."""
    from models import Department
    seen: set[int] = set()
    cur = dept
    while cur and cur.id not in seen:
        seen.add(cur.id)
        if getattr(cur, "kind", None) != "standalone" and cur.manager_user_id:
            return cur
        if not cur.parent_dept_id:
            return None
        cur = session.get(Department, cur.parent_dept_id)
    return None


def managed_unit_ids(session, user: "User") -> list[int]:
    """Jednostki, których user jest KIEROWNIKIEM CAŁEJ JEDNOSTKI (`Unit.manager_user_id`)."""
    from sqlmodel import select
    from models import Unit
    rows = session.exec(select(Unit.id).where(Unit.manager_user_id == user.id)).all()
    return [int(x) for x in rows]


def unit_manager_dept_ids(session, user: "User") -> list[int]:
    """Wszystkie komórki jednostek, których user jest kierownikiem — do PODGLĄDU
    uprawnień i WNIOSKOWANIA za pracowników (NIE do akceptacji/realizacji).

    Świadomie osobno od `managed_dept_ids`: kierownik jednostki nie staje się
    kierownikiem komórek w obiegu — akceptują nadal kierownicy komórek.
    """
    uids = managed_unit_ids(session, user)
    if not uids:
        return []
    from sqlmodel import select, col
    from models import Department
    rows = session.exec(
        select(Department.id).where(col(Department.unit_id).in_(uids))
    ).all()
    return [int(x) for x in rows]


def users_with_role(session, role: str, *, active_only: bool = True) -> list["User"]:
    """Zwraca użytkowników posiadających daną rolę — filtrowanie przez has_role
    w Pythonie (parsowanie JSON), a nie kruchym `roles LIKE '%\"x\"%'`, które
    dawałoby fałszywe trafienia i zależy od dokładnego formatowania JSON.
    """
    from sqlmodel import select
    from models import User
    q = select(User)
    if active_only:
        q = q.where(User.is_active == True)  # noqa: E712
    return [u for u in session.exec(q).all() if has_role(u, role)]


def hr_scoped_unit_ids(session, user: "User"):
    """Zakres jednostek dla pracownika kadr.

    Zwraca listę id jednostek przypisanych do tego użytkownika (HR), albo None
    gdy zakres jest nieograniczony (superadmin lub użytkownik bez roli HR).
    Administrator NIE jest tu uprzywilejowany — Wariant A: nie działa operacyjnie.
    """
    from sqlmodel import select
    from models import UserUnit
    if has_role(user, "superadmin"):
        return None
    if not has_role(user, "hr"):
        return None
    rows = session.exec(
        select(UserUnit.unit_id).where(UserUnit.user_id == user.id)
    ).all()
    return [int(x) for x in rows]


def is_department_manager_or_deputy(session, user: "User", dept) -> bool:
    """True jeśli user jest głównym kierownikiem TEJ komórki albo jej
    zastępcą (DepartmentDeputy). Używane przez silnik workflow przy
    walidacji akcji na węzłach `select_permissions` / `manager_approve`.
    """
    if dept is None:
        return False
    if dept.manager_user_id == user.id:
        return True
    from sqlmodel import select
    from models import DepartmentDeputy
    row = session.exec(
        select(DepartmentDeputy)
        .where(DepartmentDeputy.department_id == dept.id)
        .where(DepartmentDeputy.user_id == user.id)
    ).first()
    return row is not None
