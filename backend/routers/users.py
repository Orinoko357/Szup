"""
Router: Zarządzanie użytkownikami.

Superadmin (break-glass): pełny dostęp, może nadawać/odbierać dowolną rolę.
Admin: może zakładać konta i zarządzać użytkownikami z wyjątkiem kont superadmin;
       nie może nadawać roli superadmin.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from models import (
    User, UserRole, AuthType, Unit, Department,
    parse_roles, roles_to_json, primary_role, VALID_ROLES, has_role,
)
from services.auth_service import hash_password, validate_password_strength
from services.auth_service import get_current_user
from services.permissions import (
    require_admin, require_manager, managed_dept_ids, hr_scoped_unit_ids,
    users_with_role, unit_manager_dept_ids,
)

router = APIRouter()


def _guard_superadmin_target(current_user: User, target: User) -> None:
    """Admin nie może modyfikować ani usuwać kont superadmin."""
    if has_role(current_user, "superadmin"):
        return
    if has_role(target, "superadmin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może zarządzać kontem superadmina",
        )


def _guard_superadmin_role(current_user: User, roles: list[str]) -> None:
    """Admin nie może nadawać roli superadmin."""
    if has_role(current_user, "superadmin"):
        return
    if "superadmin" in roles:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może nadawać roli superadmin",
        )


class UserCreate(BaseModel):
    username: str
    password: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    auth_type: AuthType = AuthType.local
    roles: list[str] = ["viewer"]
    department_id: Optional[int] = None
    # Jednostki obsługiwane przez pracownika kadr (widoczne w jego formularzach).
    unit_ids: Optional[list[int]] = None


class UserRead(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    email: Optional[str]
    roles: list[str]
    role: str              # primary role
    auth_type: AuthType
    is_active: bool
    failed_login_count: int = 0
    locked_until: Optional[datetime] = None
    must_change_password: bool = False
    password_changed_at: Optional[datetime] = None
    created_at: datetime
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    title: str = ""                      # stanowisko z AD (NULL → "")
    is_manager_title: bool = False       # stanowisko wskazuje na kierowanie komórką
    unit_ids: list[int] = []
    # Komunikat informacyjny po zapisie (np. „komórka ma już kierownika”).
    # Nie jest błędem — operacja się powiodła, ale coś wymaga uwagi admina.
    warning: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    roles: Optional[list[str]] = None
    is_active: Optional[bool] = None
    department_id: Optional[int] = None
    unit_ids: Optional[list[int]] = None


class PasswordResetRequest(BaseModel):
    new_password: str


def _user_unit_ids(session, user_id: int) -> list[int]:
    from models import UserUnit
    if session is None:
        return []
    rows = session.exec(select(UserUnit.unit_id).where(UserUnit.user_id == user_id)).all()
    return sorted(int(x) for x in rows)


def _set_user_units(session: Session, user_id: int, unit_ids: list[int]) -> None:
    """Zastąp listę jednostek obsługiwanych przez użytkownika (kadry)."""
    from models import UserUnit
    for uid in unit_ids:
        if not session.get(Unit, uid):
            raise HTTPException(400, f"Jednostka id={uid} nie istnieje")
    current = session.exec(select(UserUnit).where(UserUnit.user_id == user_id)).all()
    for row in current:
        session.delete(row)
    session.flush()
    for uid in set(unit_ids):
        session.add(UserUnit(user_id=user_id, unit_id=uid))


def _user_read(u: User, dept_name: Optional[str] = None, session=None,
               warning: Optional[str] = None) -> UserRead:
    rlist = parse_roles(u.roles)
    if dept_name is None and u.department_id and session is not None:
        d = session.get(Department, u.department_id)
        dept_name = d.name if d else None
    return UserRead(
        id=u.id, username=u.username, full_name=u.full_name, email=u.email,
        roles=rlist, role=primary_role(u),
        auth_type=u.auth_type, is_active=u.is_active,
        failed_login_count=u.failed_login_count or 0,
        locked_until=u.locked_until, must_change_password=bool(u.must_change_password),
        password_changed_at=u.password_changed_at, created_at=u.created_at,
        department_id=u.department_id, department_name=dept_name,
        title=getattr(u, "title", None) or "",
        is_manager_title=_title_is_manager(getattr(u, "title", None)),
        unit_ids=_user_unit_ids(session, u.id),
        warning=warning,
    )


def _title_is_manager(title: Optional[str]) -> bool:
    from services.org_sync import title_indicates_manager
    return title_indicates_manager(title)


def _effective_permissions(session: Session, user_id: int) -> dict:
    """Efektywne uprawnienia pracownika = uprawnienia z ukończonych wniosków
    o NADANIE (kind=grant) MINUS te z ukończonych wniosków o ODEBRANIE
    (kind=revoke, ustanie stosunku pracy). Zwraca {permissions, requests}.
    """
    from sqlmodel import col as _col
    from models import (
        AccessRequest, RequestItem, RequestStatus,
        PermissionSystem, SystemPermission,
    )

    reqs = session.exec(
        select(AccessRequest)
        .where(AccessRequest.worker_user_id == user_id)
        .where(AccessRequest.status == RequestStatus.completed)
        .order_by(AccessRequest.completed_at.desc())
    ).all()
    if not reqs:
        return {"permissions": [], "requests": []}

    req_by_id = {r.id: r for r in reqs}
    req_ids = [r.id for r in reqs]
    items = session.exec(
        select(RequestItem).where(_col(RequestItem.request_id).in_(req_ids))
    ).all()

    sys_ids  = list({it.system_id for it in items})
    perm_ids = list({it.permission_id for it in items})
    sys_map = {s.id: s for s in session.exec(
        select(PermissionSystem).where(_col(PermissionSystem.id).in_(sys_ids))
    ).all()} if sys_ids else {}
    perm_map = {p.id: p for p in session.exec(
        select(SystemPermission).where(_col(SystemPermission.id).in_(perm_ids))
    ).all()} if perm_ids else {}

    def _kind(r) -> str:
        return getattr(r, "kind", "grant") or "grant"

    def _item_kind(it, r) -> str:
        """Kierunek pozycji; dla starych rekordów fallback na kierunek wniosku."""
        k = getattr(it, "kind", None)
        if k in ("grant", "revoke"):
            return k
        return "revoke" if _kind(r) == "revoke" else "grant"

    # Odtwarzamy stan CHRONOLOGICZNIE: nadania dodają, odebrania usuwają.
    # Dzięki temu „nadaj → odbierz → nadaj ponownie" kończy się jako posiadane.
    items_by_req: dict[int, list] = {}
    for it in items:
        items_by_req.setdefault(it.request_id, []).append(it)

    def _ts(r):
        return r.completed_at or r.approved_at or r.created_at

    # M4 — kolejność MUSI być deterministyczna, inaczej przy równym znaczniku
    # czasu (ten sam completed_at) wynik zależy od kolejności z bazy:
    #   - wnioski: sortuj po (_ts, id) — remis rozstrzyga id (chronologia zapisu),
    #   - pozycje w obrębie wniosku: revoke PRZED grant (a więc dla wniosku typu
    #     „zmiana" z tą samą pozycją nadaną i odebraną wygrywa NADANIE = stan
    #     docelowy), a przy dalszym remisie po id pozycji.
    current: dict[tuple[int, int], dict] = {}
    for r in sorted(reqs, key=lambda r: (_ts(r), r.id)):   # od najstarszego
        ordered_items = sorted(
            items_by_req.get(r.id, []),
            key=lambda it: (0 if _item_kind(it, r) == "revoke" else 1, it.id or 0),
        )
        for it in ordered_items:
            key = (it.system_id, it.permission_id)
            # Pozycja odmówiona (kierownik nadrzędny / IT) nie liczy się jako
            # posiadane — nie nadajemy jej, ani nie traktujemy jako odebranie.
            if getattr(it, "denied", False):
                continue
            if _item_kind(it, r) == "revoke":
                current.pop(key, None)
                continue
            s = sys_map.get(it.system_id); p = perm_map.get(it.permission_id)
            # Aktualny zakres/poziom dostępu (pola dodatkowe z ostatniego
            # nadania) — kierownik widzi go i może zmienić przy „zmianie".
            cvals = {}
            raw_cv = getattr(it, "custom_values", None)
            if raw_cv:
                import json as _json
                try:
                    loaded = _json.loads(raw_cv)
                    if isinstance(loaded, dict):
                        cvals = {str(k): str(v) for k, v in loaded.items()}
                except (ValueError, TypeError):
                    cvals = {}
            current[key] = {
                "system_id":   it.system_id,
                "system_name": s.name if s else None,
                "permission_id":   it.permission_id,
                "permission_name": p.permission_name if p else None,
                "description":     p.description if p else None,
                "request_id":  r.id,
                "granted_at":  _ts(r).isoformat(),
                "custom_values": cvals,
            }

    effective = sorted(current.values(),
                       key=lambda x: ((x["system_name"] or "").lower(),
                                      (x["permission_name"] or "").lower()))

    # Lista wniosków (chronologia) — z elementami i kierunkiem każdej pozycji.
    rows_by_req: dict[int, list[dict]] = {}
    for r in reqs:
        for it in items_by_req.get(r.id, []):
            s = sys_map.get(it.system_id); p = perm_map.get(it.permission_id)
            rows_by_req.setdefault(r.id, []).append({
                "system_name": s.name if s else None,
                "permission_name": p.permission_name if p else None,
                "kind": _item_kind(it, r),
            })
    req_rows = []
    for r in reqs:
        req_rows.append({
            "id": r.id,
            "kind": _kind(r),
            "created_at":    r.created_at.isoformat(),
            "completed_at":  r.completed_at.isoformat() if r.completed_at else None,
            "items":         rows_by_req.get(r.id, []),
        })

    return {"permissions": effective, "requests": req_rows}


@router.get("/me/permissions")
def my_permissions(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Uprawnienia zalogowanego użytkownika (NIS2/KSC — transparentność)."""
    return _effective_permissions(session, current_user.id)


@router.get("/{user_id}/permissions")
def user_permissions(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Bieżące uprawnienia wskazanego pracownika — dla kierownika przy wniosku
    o odebranie (ustanie stosunku pracy). Dostęp: sam pracownik, admin lub
    kierownik jego komórki."""
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(404, "Pracownik nie istnieje")
    if current_user.id != user_id and not has_role(current_user, "superadmin", "admin"):
        direct_ids, escalated_ids = managed_dept_ids(session, current_user)
        # Kierownik CAŁEJ jednostki widzi uprawnienia każdego pracownika swojej jednostki.
        unit_ids = unit_manager_dept_ids(session, current_user)
        if target.department_id not in {*direct_ids, *escalated_ids, *unit_ids}:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                "Brak dostępu do uprawnień tego pracownika")
    return _effective_permissions(session, user_id)


@router.get("/it-staff")
def list_it_staff(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Aktywni pracownicy IT — lista do przekazania wniosku przez kierownika IT.
    Dostęp: IT / admin."""
    if not has_role(current_user, "superadmin", "admin", "it_staff"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnień")
    users = users_with_role(session, "it_staff")
    users.sort(key=lambda x: (x.full_name or x.username or "").lower())
    return [
        {"id": u.id, "full_name": u.full_name, "username": u.username, "email": u.email}
        for u in users
    ]


@router.get("/by-department/{department_id}")
def users_by_department(
    department_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Aktywni pracownicy danej komórki — dla formularza HR (ustanie stosunku
    pracy: wybór pracownika z listy). Dostęp operacyjny: HR i kierownik,
    superadmin — break-glass. Administrator (Wariant A) nie działa operacyjnie.

    IDOR/RODO: sam fakt roli nie wystarcza — zakres musi obejmować tę komórkę:
      - kierownik: tylko wydziały, którymi kieruje (bezpośrednio/zastępczo/2-st.),
      - HR: tylko jednostki (unit) przypisane temu pracownikowi kadr.
    """
    from services.permissions import user_is_hr
    hr_cap = user_is_hr(session, current_user)
    if not (has_role(current_user, "superadmin", "manager") or hr_cap):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnień")
    dept = session.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Komórka nie istnieje")

    if not has_role(current_user, "superadmin"):
        allowed = False
        # Ścieżka kierownika — zakres wydziałów.
        if has_role(current_user, "manager"):
            direct_ids, escalated_ids = managed_dept_ids(session, current_user)
            if department_id in {*direct_ids, *escalated_ids}:
                allowed = True
        # Ścieżka HR (rola lub komórka kadrowa) — zakres jednostek (unit).
        if not allowed and hr_cap:
            scoped_units = hr_scoped_unit_ids(session, current_user)
            if scoped_units is None or dept.unit_id in scoped_units:
                allowed = True
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                "Brak dostępu do pracowników tej komórki")

    # Komórki nadrzędne często nie mają bezpośrednich pracowników — ludzie siedzą
    # w podkomórkach. Dla wygody zbieramy pracowników wybranej komórki ORAZ
    # wszystkich komórek pod nią (po `parent_dept_id`).
    all_depts = session.exec(select(Department)).all()
    children_of: dict[int, list[int]] = {}
    for d in all_depts:
        if d.parent_dept_id is not None:
            children_of.setdefault(d.parent_dept_id, []).append(d.id)
    subtree_ids: list[int] = []
    stack = [department_id]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        subtree_ids.append(cur)
        stack.extend(children_of.get(cur, []))

    # Zakres: dla kierownika ogranicz podkomórki do tych, którymi faktycznie
    # zarządza (bezpieczeństwo); HR (zakres po jednostce) i superadmin — całe poddrzewo.
    if not has_role(current_user, "superadmin") and has_role(current_user, "manager") \
            and not hr_cap:
        direct_ids, escalated_ids = managed_dept_ids(session, current_user)
        managed = {*direct_ids, *escalated_ids}
        subtree_ids = [d for d in subtree_ids if d in managed]

    dept_by_id = {d.id: d for d in all_depts}
    users = session.exec(
        select(User).where(User.department_id.in_(subtree_ids))
        .where(User.is_active == True)  # noqa: E712
    ).all()
    users.sort(key=lambda x: (x.full_name or x.username or "").lower())
    return [
        {"id": u.id, "full_name": u.full_name, "username": u.username, "email": u.email,
         "title": u.title or "",
         "department_id": u.department_id,
         "department_name": dept_by_id.get(u.department_id).name if u.department_id in dept_by_id else None}
        for u in users
    ]


@router.get("/search")
def users_search(
    q: str = "",
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Wyszukiwanie aktywnych pracowników po nazwisku/loginie — dla formularza
    HR (ustanie): znajdź osobę bez przeklikiwania drzewa komórek. Zakres jak w
    innych operacjach HR/kierownika; zwraca też komórkę i jednostkę, żeby front
    mógł od razu ustawić miejsce pracy."""
    from services.permissions import user_is_hr
    hr_cap = user_is_hr(session, current_user)
    if not (has_role(current_user, "superadmin", "manager") or hr_cap):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnień")

    # Dopasowanie NIEWRAŻLIWE na wielkość liter i polskie znaki (ogonki) —
    # „sliwka" znajdzie „Śliwka", „zdzislaw" znajdzie „Zdzisław".
    import unicodedata

    def _fold(s: str) -> str:
        s = (s or "").lower().replace("ł", "l")
        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

    ql = _fold((q or "").strip())
    if len(ql) < 2:
        return []

    rows = session.exec(select(User).where(User.is_active == True)).all()  # noqa: E712

    allowed_dept_ids = None     # None = bez ograniczenia
    allowed_unit_ids = None
    if not has_role(current_user, "superadmin"):
        if has_role(current_user, "manager") and not hr_cap:
            direct_ids, escalated_ids = managed_dept_ids(session, current_user)
            allowed_dept_ids = {*direct_ids, *escalated_ids}
        else:
            allowed_unit_ids = hr_scoped_unit_ids(session, current_user)  # None = wszystkie

    dept_map = {d.id: d for d in session.exec(select(Department)).all()}
    unit_map = {u.id: u.name for u in session.exec(select(Unit)).all()}

    out = []
    for u in rows:
        name = (u.full_name or u.username or "")
        if ql not in _fold(name) and ql not in _fold(u.username or ""):
            continue
        d = dept_map.get(u.department_id)
        if allowed_dept_ids is not None and u.department_id not in allowed_dept_ids:
            continue
        if allowed_unit_ids is not None and (not d or d.unit_id not in allowed_unit_ids):
            continue
        out.append({
            "id": u.id, "full_name": u.full_name, "username": u.username, "email": u.email,
            "title": u.title or "",
            "department_id": u.department_id,
            "department_name": d.name if d else None,
            "unit_id": d.unit_id if d else None,
            "unit_name": unit_map.get(d.unit_id) if d else None,
        })
    out.sort(key=lambda x: (x["full_name"] or x["username"] or "").lower())
    return out[:max(1, min(limit, 100))]


@router.get("/my-workers")
def my_workers(
    current_user: User = Depends(require_manager),
    session: Session = Depends(get_session),
):
    """
    Zwraca listę pracowników, dla których zalogowany kierownik może
    składać wnioski:
      - wszyscy z wydziałów, którymi kieruje bezpośrednio,
      - dodatkowo wszyscy z wydziałów podrzędnych 2-stopniowych
        (requires_higher_approval=True).
    """
    direct_ids, escalated_ids = managed_dept_ids(session, current_user)
    # Kierownik całej jednostki może wnioskować za wszystkich jej pracowników —
    # dokładamy komórki jego jednostek (podgląd + wnioskowanie, bez akceptacji).
    unit_scope_ids = unit_manager_dept_ids(session, current_user)
    all_ids = list({*direct_ids, *escalated_ids, *unit_scope_ids})
    if not all_ids:
        return []

    from sqlmodel import col as _col
    workers = session.exec(
        select(User)
        .where(_col(User.department_id).in_(all_ids))
        .where(User.is_active == True)  # noqa: E712
        .where(User.id != current_user.id)
    ).all()

    depts_map = {
        d.id: d for d in session.exec(
            select(Department).where(_col(Department.id).in_(all_ids))
        ).all()
    }
    unit_ids = list({d.unit_id for d in depts_map.values() if d.unit_id})
    units_map = {}
    if unit_ids:
        units_map = {
            u.id: u for u in session.exec(
                select(Unit).where(_col(Unit.id).in_(unit_ids))
            ).all()
        }

    result = []
    for u in workers:
        d = depts_map.get(u.department_id)
        un = units_map.get(d.unit_id) if d else None
        result.append({
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "department_id": u.department_id,
            "department_name": d.name if d else None,
            "unit_id": d.unit_id if d else None,
            "unit_name": un.name if un else None,
            "is_escalated": u.department_id in escalated_ids,
            # 2-stopniowy obieg? Front wie wtedy, że oświadczenie podpisze
            # dopiero kierownik II stopnia, więc nie pokazuje go przy tworzeniu.
            "requires_higher_approval": bool(d.requires_higher_approval) if d else False,
            "is_self": False,
            # Aktualnie posiadane uprawnienia (nadane − odebrane). Kierownik
            # widzi je na liście, a formularz nowego wniosku ma je wstępnie
            # zaznaczone (wniosek o zmianę = modyfikacja obecnego stanu).
            "permissions": _effective_permissions(session, u.id)["permissions"],
        })

    # Kierownik może też wnioskować SAM DLA SIEBIE — dodajemy jego własny wpis
    # (na górze listy), nawet jeśli jego komórka nie jest wśród zarządzanych.
    me = current_user
    md = depts_map.get(me.department_id) or (
        session.get(Department, me.department_id) if me.department_id else None)
    mun = (units_map.get(md.unit_id) if (md and md.unit_id) else None) or (
        session.get(Unit, md.unit_id) if (md and md.unit_id) else None)
    result.insert(0, {
        "id": me.id,
        "username": me.username,
        "full_name": me.full_name,
        "email": me.email,
        "department_id": me.department_id,
        "department_name": md.name if md else None,
        "unit_id": md.unit_id if md else None,
        "unit_name": mun.name if mun else None,
        "is_escalated": False,
        "requires_higher_approval": bool(md.requires_higher_approval) if md else False,
        "is_self": True,
        "permissions": _effective_permissions(session, me.id)["permissions"],
    })

    # posortuj: najpierw SAM kierownik, potem bezpośredni, dalej po nazwisku.
    result.sort(key=lambda r: (not r.get("is_self"), r["is_escalated"],
                               (r["full_name"] or r["username"] or "").lower()))
    return result


@router.get("/my-subtree")
def my_subtree(
    current_user: User = Depends(require_manager),
    session: Session = Depends(get_session),
):
    """
    Zwraca strukturę „w dół" wydziałów, którymi kieruje zalogowany użytkownik
    — rekurencyjnie wszystkie pod-wydziały + ich kierowników i pracowników,
    wraz z efektywnymi uprawnieniami nadanymi na podstawie zrealizowanych
    wniosków.

    Admin/superadmin widzi pełną strukturę (wszystkie jednostki i wydziały).
    """
    from sqlmodel import col as _col
    from services.permissions import is_admin
    from models import (
        AccessRequest, RequestItem, RequestStatus,
        PermissionSystem, SystemPermission,
    )

    # --- 1. Zbierz wszystkie wydziały w sesji (dla rekurencji) ---
    all_depts = session.exec(select(Department)).all()
    by_id     = {d.id: d for d in all_depts}
    children_of: dict[int, list[Department]] = {}
    for d in all_depts:
        children_of.setdefault(d.parent_dept_id, []).append(d)

    # --- 2. Wyznacz wydziały-korzenie ---
    if is_admin(current_user):
        # Korzenie = wydziały bez rodzica (top-level w obrębie każdej jednostki)
        roots = [d for d in all_depts if not d.parent_dept_id]
    else:
        direct_ids, _escalated = managed_dept_ids(session, current_user)
        roots = [by_id[i] for i in direct_ids if i in by_id]

    if not roots:
        return {"roots": []}

    # --- 3. Zbuduj listę wszystkich wydziałów w subtree (BFS) ---
    subtree_depts: list[Department] = []
    seen: set[int] = set()
    stack = list(roots)
    while stack:
        d = stack.pop()
        if d.id in seen:
            continue
        seen.add(d.id)
        subtree_depts.append(d)
        stack.extend(children_of.get(d.id, []))

    subtree_ids = [d.id for d in subtree_depts]

    # --- 4. Dane pomocnicze: jednostki, managerowie, pracownicy ---
    unit_ids = list({d.unit_id for d in subtree_depts if d.unit_id})
    units_map: dict[int, Unit] = {}
    if unit_ids:
        units_map = {u.id: u for u in session.exec(
            select(Unit).where(_col(Unit.id).in_(unit_ids))
        ).all()}

    mgr_ids = list({d.manager_user_id for d in subtree_depts if d.manager_user_id})
    mgr_map: dict[int, User] = {}
    if mgr_ids:
        mgr_map = {u.id: u for u in session.exec(
            select(User).where(_col(User.id).in_(mgr_ids))
        ).all()}

    workers = []
    if subtree_ids:
        workers = session.exec(
            select(User)
            .where(_col(User.department_id).in_(subtree_ids))
            .where(User.is_active == True)  # noqa: E712
        ).all()
    workers_by_dept: dict[int, list[User]] = {}
    for w in workers:
        workers_by_dept.setdefault(w.department_id, []).append(w)

    # --- 5. Efektywne uprawnienia per pracownik (ze zrealizowanych wniosków) ---
    # Zbieramy RequestItem JOIN AccessRequest gdzie worker_user_id ∈ pracownicy
    # i status == completed.
    worker_ids = [w.id for w in workers]
    perms_by_user: dict[int, list[dict]] = {}
    if worker_ids:
        req_rows = session.exec(
            select(AccessRequest)
            .where(_col(AccessRequest.worker_user_id).in_(worker_ids))
            .where(AccessRequest.status == RequestStatus.completed)
        ).all()
        req_by_id = {r.id: r for r in req_rows}
        if req_rows:
            items = session.exec(
                select(RequestItem).where(
                    _col(RequestItem.request_id).in_([r.id for r in req_rows])
                )
            ).all()
            # Słowniki system/permission (jeden batch zapytań)
            sys_ids = list({it.system_id for it in items})
            perm_ids = list({it.permission_id for it in items})
            sys_map: dict[int, PermissionSystem] = {}
            perm_map: dict[int, SystemPermission] = {}
            if sys_ids:
                sys_map = {s.id: s for s in session.exec(
                    select(PermissionSystem).where(_col(PermissionSystem.id).in_(sys_ids))
                ).all()}
            if perm_ids:
                perm_map = {p.id: p for p in session.exec(
                    select(SystemPermission).where(_col(SystemPermission.id).in_(perm_ids))
                ).all()}
            # Agreguj (unikając duplikatów per user+system+permission)
            seen_key: dict[int, set[tuple[int, int]]] = {}
            for it in items:
                req = req_by_id.get(it.request_id)
                if not req or req.worker_user_id is None:
                    continue
                uid = req.worker_user_id
                key = (it.system_id, it.permission_id)
                if key in seen_key.setdefault(uid, set()):
                    continue
                seen_key[uid].add(key)
                s_obj = sys_map.get(it.system_id)
                p_obj = perm_map.get(it.permission_id)
                perms_by_user.setdefault(uid, []).append({
                    "system_id":   it.system_id,
                    "system_name": s_obj.name if s_obj else None,
                    "permission_id":   it.permission_id,
                    "permission_name": p_obj.permission_name if p_obj else None,
                    "request_id": req.id,
                    "granted_at": (req.completed_at or req.approved_at or req.created_at).isoformat(),
                })

    # --- 6. Serializacja rekurencyjna ---
    def _ser_user(u: Optional[User]) -> Optional[dict]:
        if not u:
            return None
        return {
            "id": u.id, "username": u.username,
            "full_name": u.full_name, "email": u.email,
        }

    def _ser_worker(w: User) -> dict:
        perms = perms_by_user.get(w.id, [])
        perms_sorted = sorted(perms, key=lambda p: (p["system_name"] or "", p["permission_name"] or ""))
        return {
            "id": w.id, "username": w.username,
            "full_name": w.full_name, "email": w.email,
            "is_manager_here": False,   # uzupełnimy niżej
            "permissions": perms_sorted,
        }

    def _ser_dept(d: Department) -> dict:
        mgr = mgr_map.get(d.manager_user_id) if d.manager_user_id else None
        u   = units_map.get(d.unit_id) if d.unit_id else None
        ws  = sorted(
            workers_by_dept.get(d.id, []),
            key=lambda x: (x.full_name or x.username or "").lower(),
        )
        ws_ser = [_ser_worker(w) for w in ws]
        # oznacz pracownika który jest kierownikiem tego wydziału
        for item in ws_ser:
            if mgr and item["id"] == mgr.id:
                item["is_manager_here"] = True
        ch = sorted(
            children_of.get(d.id, []),
            key=lambda x: (x.name or "").lower(),
        )
        return {
            "id": d.id, "name": d.name,
            "kind": d.kind or "department",
            "unit_id": d.unit_id, "unit_name": u.name if u else None,
            "requires_higher_approval": bool(d.requires_higher_approval),
            "manager": _ser_user(mgr),
            "workers": ws_ser,
            "children": [_ser_dept(c) for c in ch],
        }

    roots_sorted = sorted(roots, key=lambda d: ((units_map.get(d.unit_id).name if units_map.get(d.unit_id) else ""), d.name or ""))
    return {"roots": [_ser_dept(d) for d in roots_sorted]}


@router.get("/", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    users = session.exec(select(User)).all()
    dept_names = {d.id: d.name for d in session.exec(select(Department)).all()}
    return [_user_read(u, dept_names.get(u.department_id), session=session) for u in users]


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    _guard_superadmin_role(current_user, data.roles)
    if session.exec(select(User).where(User.username == data.username)).first():
        raise HTTPException(400, "Użytkownik o tej nazwie już istnieje")
    if data.auth_type == AuthType.local and not data.password:
        raise HTTPException(400, "Hasło jest wymagane dla konta lokalnego")
    if data.password:
        validate_password_strength(data.password)
    invalid = [r for r in data.roles if r not in VALID_ROLES]
    if invalid:
        raise HTTPException(400, f"Nieznane role: {invalid}")

    if data.department_id is not None:
        if not session.get(Department, data.department_id):
            raise HTTPException(400, "Wskazana komórka organizacyjna nie istnieje")

    # Wybór password_hash:
    #   - lokalne z hasłem  → bcrypt
    #   - LDAP              → sentinel "!ldap-managed!" — login_local i tak odrzuca
    #     wcześniej (auth_type != local), więc ten string nigdy nie trafia do bcrypt.
    #     Sentinel zamiast NULL żeby spełnić ewentualny `NOT NULL` constraint na
    #     starszych bazach, gdzie kolumna password_hash powstała jako wymagana.
    if data.auth_type == AuthType.ldap:
        password_hash_value = "!ldap-managed!"
    elif data.password:
        password_hash_value = hash_password(data.password)
    else:
        password_hash_value = None  # nie powinno się zdarzyć (sprawdzone wyżej)

    user = User(
        username=data.username,
        full_name=data.full_name,
        email=data.email,
        password_hash=password_hash_value,
        roles=roles_to_json(data.roles),
        auth_type=data.auth_type,
        department_id=data.department_id,
        password_changed_at=datetime.utcnow() if data.password else None,
        must_change_password=bool(data.password),
    )
    try:
        session.add(user); session.commit(); session.refresh(user)
    except Exception as exc:
        session.rollback()
        # Loguj pełny powód i daj klientowi czytelny komunikat zamiast surowego 500
        import logging
        logging.getLogger("szup.users").exception("create_user failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Nie udało się utworzyć konta w bazie: {type(exc).__name__}: {exc}",
        )
    if data.unit_ids is not None:
        _set_user_units(session, user.id, data.unit_ids)
        session.commit(); session.refresh(user)
    # Rola → struktura: kierownik przypisany do komórki bez kierownika
    # obejmuje ją automatycznie (bez podmieniania obsadzonego stanowiska).
    from services.org_sync import sync_after_user_change
    changed, warning = sync_after_user_change(session, user)
    if changed:
        session.commit(); session.refresh(user)
    return _user_read(user, session=session, warning=warning)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    data: UserUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    _guard_superadmin_target(current_user, user)
    if data.roles is not None:
        _guard_superadmin_role(current_user, data.roles)
        invalid = [r for r in data.roles if r not in VALID_ROLES]
        if invalid:
            raise HTTPException(400, f"Nieznane role: {invalid}")
        # Ochrona własnego konta — nie można odebrać sobie roli dającej dostęp
        if user.id == current_user.id:
            if has_role(current_user, "superadmin") and "superadmin" not in data.roles:
                raise HTTPException(400, "Nie możesz odebrać sobie roli superadmin")
            if has_role(current_user, "admin") and "admin" not in data.roles and "superadmin" not in data.roles:
                raise HTTPException(400, "Nie możesz odebrać sobie roli admin")
    if data.is_active is not None:
        if user.id == current_user.id and not data.is_active:
            raise HTTPException(400, "Nie możesz dezaktywować własnego konta")

    if data.full_name is not None:  user.full_name = data.full_name
    if data.email is not None:      user.email = data.email
    if data.is_active is not None:  user.is_active = data.is_active
    if data.roles is not None:      user.roles = roles_to_json(data.roles)

    # department_id: obecność pola w żądaniu = intencja zmiany (także na null,
    # by odpiąć od komórki). Rozróżniamy „nie podano" od „podano null".
    if "department_id" in data.model_fields_set:
        if data.department_id:
            if not session.get(Department, data.department_id):
                raise HTTPException(400, "Wskazana komórka organizacyjna nie istnieje")
            user.department_id = data.department_id
        else:
            user.department_id = None

    # Jednostki obsługiwane (kadry) — podanie listy zastępuje całość.
    if data.unit_ids is not None:
        _set_user_units(session, user.id, data.unit_ids)

    session.add(user); session.commit(); session.refresh(user)

    # Synchronizacja ze strukturą po zmianie ról / komórki:
    #  - nadanie roli „manager" + komórka bez kierownika → obejmuje ją,
    #  - odebranie roli „manager" → zwolnij stanowiska, którymi kierował.
    warning = None
    if data.roles is not None or "department_id" in data.model_fields_set:
        from services.org_sync import sync_after_user_change, release_manager_posts
        changed = False
        if "manager" in parse_roles(user.roles):
            changed, warning = sync_after_user_change(session, user)
        else:
            changed = release_manager_posts(session, user.id)
        if changed:
            session.commit(); session.refresh(user)

    return _user_read(user, session=session, warning=warning)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: PasswordResetRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    _guard_superadmin_target(current_user, user)
    if user.auth_type != AuthType.local:
        raise HTTPException(400, "Nie można zresetować hasła konta LDAP")

    validate_password_strength(data.new_password)
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.utcnow()
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    # Margines -5s żeby nowy token wystawiony zaraz po reset'cie miał iat > tokens_valid_from.
    # JWT iat jest w całych sekundach, datetime w bazie ma mikrosekundy.
    user.tokens_valid_from = (datetime.utcnow() - timedelta(seconds=5)).replace(microsecond=0)
    session.add(user); session.commit()
    return {"ok": True, "must_change_password": True}


@router.post("/{user_id}/unlock")
def unlock_account(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    _guard_superadmin_target(current_user, user)
    user.failed_login_count = 0
    user.locked_until = None
    session.add(user); session.commit()
    return {"ok": True}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    if user.id == current_user.id:
        raise HTTPException(400, "Nie możesz usunąć własnego konta")
    _guard_superadmin_target(current_user, user)
    session.delete(user)
    try:
        session.commit()
    except IntegrityError:
        # M1 — FK egzekwowane: użytkownik jest powiązany (kierownik komórki,
        # autor/pracownik wniosku, aktor kroku). Nie osieracamy danych.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Nie można usunąć — użytkownik jest powiązany z komórkami lub wnioskami. "
            "Najpierw przenieś te powiązania (np. zmień kierownika) albo dezaktywuj konto.")


# ---------------------------------------------------------------------------
# Import użytkowników z AD/LDAP
# ---------------------------------------------------------------------------

class LdapUserPreviewRequest(BaseModel):
    search_base: Optional[str] = None


class LdapUserPreviewItem(BaseModel):
    dn: str
    username: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_enabled_in_ad: bool
    # Mapowanie do naszej struktury
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    unit_id: Optional[int] = None
    unit_name: Optional[str] = None
    # Status:
    #   "new"          — nowe konto do utworzenia
    #   "exists_ldap"  — istnieje już jako konto LDAP (re-import zaktualizuje)
    #   "conflict"     — koliduje z kontem lokalnym (pomijane)
    status: str
    # True, gdy ten sam login (sAMAccountName) występuje w AD więcej niż raz —
    # importujemy tylko pierwsze wystąpienie, resztę pomijamy.
    duplicate: bool = False
    # True, gdy OU użytkownika mieści się w ZAIMPORTOWANEJ strukturze (powiązana
    # jednostka/komórka). Tylko tacy użytkownicy są importowalni.
    in_structure: bool = False


class LdapUserImportRequest(BaseModel):
    usernames: list[str]      # lista sAMAccountName do zaimportowania
    search_base: Optional[str] = None


class LdapUserImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    conflicts: int
    details: list[str]


def _build_dn_to_dept_map(session: Session) -> dict[str, int]:
    """Mapa znormalizowany DN OU → Department.id."""
    from services.ldap_service import normalize_dn
    out: dict[str, int] = {}
    for d in session.exec(select(Department)).all():
        if d.ldap_dn:
            out[normalize_dn(d.ldap_dn)] = d.id
    return out


def _build_dn_to_unit_map(session: Session) -> dict[str, int]:
    from services.ldap_service import normalize_dn
    out: dict[str, int] = {}
    for u in session.exec(select(Unit)).all():
        if u.ldap_dn:
            out[normalize_dn(u.ldap_dn)] = u.id
    return out


# Komunikat, gdy struktura organizacyjna nie została jeszcze pobrana z AD.
_NO_STRUCTURE_MSG = (
    "Najpierw pobierz jednostki organizacyjne z AD (Jednostki → import struktury). "
    "Użytkowników można zaimportować/zsynchronizować dopiero po powiązaniu struktury — "
    "importujemy wyłącznie osoby z powiązanych jednostek organizacyjnych."
)


def _require_structure(dept_by_dn: dict, unit_by_dn: dict) -> None:
    """Wymuś, że struktura OU jest już zaimportowana (powiązana po ldap_dn)."""
    if not dept_by_dn and not unit_by_dn:
        raise HTTPException(409, _NO_STRUCTURE_MSG)


@router.post("/ldap/preview", response_model=list[LdapUserPreviewItem])
def ldap_users_preview(
    data: LdapUserPreviewRequest,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """
    Zwraca listę użytkowników z AD wraz z mapowaniem do zaimportowanej struktury OU.
    """
    from models import LdapSettings
    from services.ldap_service import fetch_ldap_users, normalize_dn

    cfg = session.exec(select(LdapSettings)).first()
    if not cfg or not cfg.host:
        raise HTTPException(400, "Brak konfiguracji LDAP")
    if not cfg.enabled:
        raise HTTPException(400, "LDAP nie jest włączone")

    search_base = (data.search_base or "").strip() or cfg.base_dn
    if not search_base:
        raise HTTPException(400, "Podaj search_base lub ustaw base_dn")

    try:
        users_raw = fetch_ldap_users(cfg, search_base)
    except Exception as exc:
        raise HTTPException(502, f"Błąd połączenia z LDAP: {exc}")

    dept_by_dn = _build_dn_to_dept_map(session)
    unit_by_dn = _build_dn_to_unit_map(session)
    _require_structure(dept_by_dn, unit_by_dn)
    dept_names = {d.id: d.name for d in session.exec(select(Department)).all()}
    unit_names = {u.id: u.name for u in session.exec(select(Unit)).all()}
    existing = {u.username: u for u in session.exec(select(User)).all()}

    from services.ldap_service import parent_dn as _parent_of

    def _resolve_dept_unit(start_dn: str) -> tuple[Optional[int], Optional[int]]:
        """Idzie w górę po parent-DN dopóki nie trafi na dopasowany Department/Unit."""
        current = normalize_dn(start_dn)
        while current:
            if current in dept_by_dn:
                d_id = dept_by_dn[current]
                u_id = None
                up = current
                while up:
                    if up in unit_by_dn:
                        u_id = unit_by_dn[up]
                        break
                    up = normalize_dn(_parent_of(up))
                return d_id, u_id
            if current in unit_by_dn:
                return None, unit_by_dn[current]
            current = normalize_dn(_parent_of(current))
        return None, None

    # Wykryj loginy występujące w AD więcej niż raz — pierwsze wystąpienie
    # traktujemy normalnie, kolejne oznaczamy jako duplikat (do pominięcia).
    from collections import Counter
    name_counts = Counter(u["username"] for u in users_raw)
    seen_names: set[str] = set()

    out: list[LdapUserPreviewItem] = []
    for u in users_raw:
        dept_id, unit_id = _resolve_dept_unit(u["parent_dn"])
        existing_user = existing.get(u["username"])
        if existing_user is None:
            status_v = "new"
        elif existing_user.auth_type == AuthType.ldap:
            status_v = "exists_ldap"
        else:
            status_v = "conflict"
        is_dup = name_counts[u["username"]] > 1 and u["username"] in seen_names
        seen_names.add(u["username"])
        out.append(LdapUserPreviewItem(
            dn=u["dn"],
            username=u["username"],
            full_name=u["full_name"],
            email=u["email"],
            is_enabled_in_ad=u["is_enabled_in_ad"],
            department_id=dept_id,
            department_name=dept_names.get(dept_id) if dept_id else None,
            unit_id=unit_id,
            unit_name=unit_names.get(unit_id) if unit_id else None,
            status=status_v,
            duplicate=is_dup,
            in_structure=(dept_id is not None or unit_id is not None),
        ))
    return out


@router.post("/ldap/import", response_model=LdapUserImportResult)
def ldap_users_import(
    data: LdapUserImportRequest,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """
    Importuje wskazanych użytkowników (po sAMAccountName) z AD do bazy.
    - Nowe konta  → auth_type=ldap, rola ['viewer'], department_id po parent-OU.
    - LDAP konta  → aktualizacja full_name, email, is_active, department_id, ldap_dn.
    - Konta lokalne o tym samym loginie → pomijane (konflikt).
    """
    from models import LdapSettings
    from services.ldap_service import fetch_ldap_users, normalize_dn

    cfg = session.exec(select(LdapSettings)).first()
    if not cfg or not cfg.enabled:
        raise HTTPException(400, "LDAP nie jest włączone")
    search_base = (data.search_base or "").strip() or cfg.base_dn
    if not search_base:
        raise HTTPException(400, "Brak search_base")

    try:
        users_raw = fetch_ldap_users(cfg, search_base)
    except Exception as exc:
        raise HTTPException(502, f"Błąd LDAP: {exc}")

    wanted = set(data.usernames)
    dept_by_dn = _build_dn_to_dept_map(session)
    unit_by_dn = _build_dn_to_unit_map(session)
    _require_structure(dept_by_dn, unit_by_dn)

    from services.ldap_service import parent_dn as _parent_of

    def _resolve_dept_unit(start_dn: str) -> tuple[Optional[int], Optional[int]]:
        """Nearest dopasowany Department (+ obejmujący Unit) w górę po DN."""
        current = normalize_dn(start_dn)
        while current:
            if current in dept_by_dn:
                d_id = dept_by_dn[current]
                u_id = None
                up = current
                while up:
                    if up in unit_by_dn:
                        u_id = unit_by_dn[up]; break
                    up = normalize_dn(_parent_of(up))
                return d_id, u_id
            if current in unit_by_dn:
                return None, unit_by_dn[current]
            current = normalize_dn(_parent_of(current))
        return None, None

    created = updated = skipped = conflicts = 0
    details: list[str] = []
    processed_names: set[str] = set()   # ochrona przed duplikatami loginu w tej serii

    for u in users_raw:
        if u["username"] not in wanted:
            continue

        # Pomiń konta WYŁĄCZONE w AD — nie tworzymy dla nich kont w systemie.
        if not u["is_enabled_in_ad"]:
            skipped += 1
            details.append(f"⚠ {u['username']} — wyłączony w AD, pominięty")
            continue

        # Pomiń zduplikowany login — importujemy tylko pierwsze wystąpienie.
        if u["username"] in processed_names:
            skipped += 1
            details.append(f"⚠ {u['username']} — duplikat loginu, pominięty")
            continue
        processed_names.add(u["username"])

        dept_id, unit_id = _resolve_dept_unit(u["parent_dn"])
        # Importujemy WYŁĄCZNIE osoby z powiązanych jednostek organizacyjnych —
        # jeśli OU użytkownika nie mieści się w zaimportowanej strukturze, pomijamy.
        if dept_id is None and unit_id is None:
            skipped += 1
            details.append(f"⚠ {u['username']} — poza powiązaną strukturą OU, pominięty")
            continue
        ndn = normalize_dn(u["dn"])

        existing = session.exec(select(User).where(User.username == u["username"])).first()
        if existing and existing.auth_type != AuthType.ldap:
            conflicts += 1
            details.append(f"⚠ {u['username']} — konflikt z kontem lokalnym, pominięty")
            continue

        if existing:
            existing.full_name    = u["full_name"] or existing.full_name
            existing.email        = u["email"] or existing.email
            existing.is_active    = u["is_enabled_in_ad"]
            existing.department_id = dept_id or existing.department_id
            existing.ldap_dn      = ndn
            # Stanowisko: AD jest źródłem prawdy — także wyczyszczenie w AD.
            existing.title        = u.get("title") or ""
            session.add(existing); session.commit()
            updated += 1
            details.append(f"~ {u['username']} — zaktualizowany")
        else:
            new_user = User(
                username=u["username"],
                full_name=u["full_name"],
                email=u["email"],
                title=u.get("title") or "",
                password_hash="!ldap-managed!",
                roles=roles_to_json(["viewer"]),
                auth_type=AuthType.ldap,
                is_active=u["is_enabled_in_ad"],
                department_id=dept_id,
                ldap_dn=ndn,
            )
            session.add(new_user); session.commit()
            created += 1
            details.append(f"+ {u['username']} — utworzony")

    not_found = wanted - {u["username"] for u in users_raw}
    for nf in not_found:
        skipped += 1
        details.append(f"⚠ {nf} — nie znaleziony w AD, pominięty")

    return LdapUserImportResult(
        created=created, updated=updated, skipped=skipped, conflicts=conflicts,
        details=details,
    )
