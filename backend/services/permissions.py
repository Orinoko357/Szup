"""
Role/permission helpers dla SZUP.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlmodel import Session

from models import User, has_role
from services.auth_service import get_current_user


def user_is_hr(session: Session, user: User) -> bool:
    """Zdolność HR = przynależność do komórki oznaczonej jako KADROWA
    (Department.is_hr, „komórka kadrowa”). Roli „hr” już nie ma — nie nadaje się
    jej per osoba; wystarczy oznaczyć komórkę. Pracownik komórki kadrowej
    obsługuje WSZYSTKIE jednostki (patrz `hr_scoped_unit_ids`)."""
    dept_id = getattr(user, "department_id", None)
    if not dept_id:
        return False
    from models import Department
    d = session.get(Department, dept_id)
    return bool(d and getattr(d, "is_hr", False))


# Role operacyjne, których nie łączy się z rolą superadmin — superadmin to konto
# awaryjne (break-glass) do konfiguracji, a nie do pracy w obiegu wniosków.
SUPERADMIN_FORBIDDEN_ROLES = frozenset({"manager", "it_staff"})


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
# dostaje właściwą rolę operacyjną (manager / it_staff) albo — dla kadr —
# trafia do komórki kadrowej (Department.is_hr).
def require_manager(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "superadmin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wymagana rola kierownika")
    return current_user


# Operacje wyłącznie dla pracownika IT (rozwiązywanie zgłoszeń zmiany nazwiska,
# dowiązanie wniosku do konta pracownika). Rola admin/superadmin SAMA nie
# wystarcza — administrator konfiguruje system, nie działa operacyjnie. Admin,
# który ma też rolę it_staff, działa jako pracownik IT.
def require_it_operator(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "it_staff"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Operację wykonuje wyłącznie pracownik IT (rola it_staff)")
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

    # Samodzielne stanowiska (kind="standalone") i komórki BEZ (aktywnego)
    # kierownika „podlegają" najbliższemu kierownikowi wyżej — doliczamy je do
    # zakresu tego kierownika (widzi ich pracowników, zatwierdza i składa za
    # nich wnioski).
    if direct_ids:
        direct_set = set(direct_ids)
        inherited: list[int] = []
        for d in session.exec(select(Department)).all():
            if d.id in direct_set:
                continue
            if d.kind == "standalone" or not has_active_manager(session, d):
                resp = effective_manager_dept(session, d)
                if resp and resp.id in direct_set:
                    inherited.append(d.id)
        if inherited:
            direct_ids_list = sorted(direct_set | set(inherited))
    return direct_ids_list, escalated_ids


def has_active_manager(session, dept) -> bool:
    """Czy komórka ma przypisanego kierownika z AKTYWNYM kontem.

    Kierownik wyłączony (np. dezaktywowany importem z AD) nie może działać ani
    odbierać powiadomień — komórka jest wtedy traktowana jak komórka bez
    kierownika (odpowiada najbliższy kierownik wyżej)."""
    if dept is None or not dept.manager_user_id:
        return False
    mgr = session.get(User, dept.manager_user_id)
    return bool(mgr and mgr.is_active)


def effective_manager_dept(session, dept):
    """Komórka, której kierownik faktycznie ODPOWIADA za `dept`.

    Dla samodzielnego stanowiska (kind="standalone") albo komórki bez (aktywnego)
    kierownika wspinamy się po rodzicach do najbliższej komórki, która NIE jest
    samodzielnym stanowiskiem i MA aktywnego kierownika. Zwraca `Department`
    albo None (brak w górę)."""
    from models import Department
    seen: set[int] = set()
    cur = dept
    while cur and cur.id not in seen:
        seen.add(cur.id)
        if getattr(cur, "kind", None) != "standalone" and has_active_manager(session, cur):
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
    """Wszystkie komórki jednostek, których user jest kierownikiem (dyrektor
    jednostki) — podgląd uprawnień i wnioskowanie za pracowników.

    Osobno od `managed_dept_ids` (nie czyni go kierownikiem komórek). Dyrektor
    jednostki jest „przełożonym” (`is_superior_for` / `superior_dept_ids`):
    w komórce z własnym kierownikiem działa na etapie kierownika dopiero po
    przejęciu wniosku, w komórce bez kierownika i na samodzielnym stanowisku —
    od razu; akceptację wyższą wykonuje bezpośrednio.
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


def superior_dept_ids(session, user: "User") -> list[int]:
    """Komórki z „kręgu” usera — kieruje nimi (lub jest zastępcą) albo jest ich
    PRZEŁOŻONYM:
      - całe poddrzewo komórek, którymi kieruje (lub jest zastępcą),
      - wszystkie komórki jednostek, których jest kierownikiem (dyrektor jednostki).
    To dokładnie te komórki, dla których `is_superior_for(..., include_self=True)`.
    Przełożony widzi w nich wnioski; na etapie kierownika komórki, która ma
    własnego kierownika, działa dopiero po przejęciu wniosku (patrz
    `services.workflow.can_act`).
    """
    from sqlmodel import select
    from models import Department, DepartmentDeputy
    roots = {d.id for d in session.exec(
        select(Department).where(Department.manager_user_id == user.id)).all()}
    roots.update(int(x) for x in session.exec(
        select(DepartmentDeputy.department_id).where(DepartmentDeputy.user_id == user.id)).all())
    out: set[int] = set(unit_manager_dept_ids(session, user))
    if roots:
        children: dict[int, list[int]] = {}
        for d in session.exec(select(Department)).all():
            if d.parent_dept_id is not None:
                children.setdefault(d.parent_dept_id, []).append(d.id)
        stack = list(roots)
        while stack:
            cur = stack.pop()
            if cur in out:
                continue
            out.add(cur)
            stack.extend(children.get(cur, []))
    return sorted(out)


def _cached(session, key: str, fn):
    """Cache wyniku w obrębie jednej sesji (= jednego żądania HTTP).

    Czyszczony po każdym flushu i rollbacku (patrz `_clear_perm_cache`), więc
    zmiana struktury w tym samym żądaniu nie zostawia nieaktualnych wyników."""
    info = getattr(session, "info", None)
    if info is None:
        return fn()
    store = info.setdefault("_perm_cache", {})
    if key not in store:
        store[key] = fn()
    return store[key]


def _clear_perm_cache(session, *_args) -> None:
    session.info.pop("_perm_cache", None)


def _install_cache_invalidation() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _OrmSession
    if not event.contains(_OrmSession, "after_flush", _clear_perm_cache):
        event.listen(_OrmSession, "after_flush", _clear_perm_cache)
        event.listen(_OrmSession, "after_rollback", _clear_perm_cache)


_install_cache_invalidation()


def dept_deputy_ids(session, dept_id: int | None) -> frozenset[int]:
    """Id zastępców kierownika komórki (cache na czas żądania — listy wniosków
    sprawdzają to dla każdego wiersza)."""
    if not dept_id:
        return frozenset()

    def compute():
        from sqlmodel import select
        from models import DepartmentDeputy
        return frozenset(int(x) for x in session.exec(
            select(DepartmentDeputy.user_id).where(DepartmentDeputy.department_id == dept_id)
        ).all())
    return _cached(session, f"deputies:{dept_id}", compute)


def manager_scope(session, user: "User") -> tuple[list[int], list[int]]:
    """Pełny zakres kierownika: (direct_ids, escalated_ids ∪ komórki przełożonego).

    Komórki, w których user jest PRZEŁOŻONYM (poddrzewo swoich komórek i komórki
    jednostki, którą kieruje), dokładamy do drugiej listy — przełożony widzi
    wnioski z podległych komórek (na etapie kierownika komórki z własnym
    kierownikiem działa po przejęciu). Wynik cache'owany na czas żądania
    (wywołuje go m.in. każdy _check_access)."""
    def compute():
        direct_ids, escalated_ids = managed_dept_ids(session, user)
        extra = set(superior_dept_ids(session, user)) - set(direct_ids)
        return list(direct_ids), sorted(set(escalated_ids) | extra)
    return _cached(session, f"scope:{user.id}", compute)


def manager_scope_ids(session, user: "User") -> set[int]:
    """Zbiór wszystkich komórek z zakresu kierownika/przełożonego (do filtrów)."""
    d, e = manager_scope(session, user)
    return {*d, *e}


def is_superior_for(session, user: "User", dept, *, include_self: bool = True) -> bool:
    """True, jeśli user kieruje (lub jest zastępcą) `dept` albo dowolną komórką
    NAD nią w strukturze, albo jest kierownikiem jednostki tej komórki.
    include_self=False — liczymy tylko komórki wyżej (przełożeni kierownika
    komórki: przejęcie wniosku, akceptacja wyższa).

    Uwaga: dyrektor jednostki jest przełożonym niezależnie od `include_self`,
    także gdy sam kieruje tą komórką."""
    if dept is None:
        return False

    def compute():
        from models import Department, Unit
        seen: set[int] = set()
        cur = dept if include_self else (
            session.get(Department, dept.parent_dept_id) if dept.parent_dept_id else None)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            if is_department_manager_or_deputy(session, user, cur):
                return True
            cur = session.get(Department, cur.parent_dept_id) if cur.parent_dept_id else None
        unit = session.get(Unit, dept.unit_id) if getattr(dept, "unit_id", None) else None
        return bool(unit and unit.manager_user_id == user.id)
    return _cached(session, f"superior:{user.id}:{dept.id}:{int(include_self)}", compute)


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
    """Zakres jednostek dla pracownika kadr — zawsze None (wszystkie jednostki).

    Pracownik komórki kadrowej obsługuje całą organizację; dawne przypisania
    do jednostek (UserUnit) zostają w bazie, ale niczego już nie ograniczają.
    Funkcja zostaje dla zgodności wywołań (None = bez ograniczenia)."""
    return None


def is_department_manager_or_deputy(session, user: "User", dept) -> bool:
    """True jeśli user jest głównym kierownikiem TEJ komórki albo jej
    zastępcą (DepartmentDeputy). Używane przez silnik workflow przy
    walidacji akcji na węzłach `select_permissions` / `manager_approve`.
    """
    if dept is None:
        return False
    if dept.manager_user_id == user.id:
        return True
    return user.id in dept_deputy_ids(session, dept.id)
