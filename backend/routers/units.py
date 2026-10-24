"""
Router: Jednostki organizacyjne i wydziały — admin only.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from models import (Unit, Department, DepartmentDeputy, SecuritySeverity, User,
                    has_role)
from services.auth_service import get_current_user
from services.permissions import require_admin, require_superadmin

router = APIRouter()


def _guard_self_post(current_user: User, user_id: Optional[int]) -> None:
    """Admin (nie superadmin) nie może przypisać SIEBIE na stanowisko w strukturze
    (kierownik komórki/jednostki, zastępca) — dostałby kroki kierownicze obiegu
    i rolę „manager” z automatu. Robi to superadmin."""
    if user_id and user_id == current_user.id and not has_role(current_user, "superadmin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może przypisać samego siebie jako kierownika ani zastępcy "
            "— poproś o to superadmina",
        )


def _audit_post_change(session: Session, request: Optional[Request], actor: User, *,
                       action: str, target_type: str, target_id: int, name: str,
                       old_user_id: Optional[int], new_user_id: Optional[int],
                       extra: Optional[dict] = None) -> None:
    """Zmiana stanowiska w strukturze (kierownik komórki/jednostki, zastępca) →
    wpis w audit logu. Objęcie stanowiska daje kroki kierownicze obiegu i rolę
    „manager”, więc dodatkowo trafia do zdarzeń bezpieczeństwa (medium)."""
    if old_user_id == new_user_id:
        return
    from services.audit import record_event, request_meta
    from services.security_events import emit as emit_security_event
    meta = request_meta(request)
    details = {"name": name, "old_user_id": old_user_id, "new_user_id": new_user_id,
               **(extra or {})}
    record_event(session, action=action, user_id=actor.id, username=actor.username,
                 target_type=target_type, target_id=target_id, ip=meta["ip"],
                 user_agent=meta["user_agent"], details=details)
    if new_user_id:
        from services.security_events import POST_ACTION_LABELS
        new_user = session.get(User, new_user_id)
        who = (new_user.username if new_user else f"id={new_user_id}")
        post = POST_ACTION_LABELS.get(action, "stanowisko kierownicze")
        emit_security_event(
            session, event_type="structure.post_assigned", source="units",
            severity=SecuritySeverity.medium,
            summary=f"{who} obejmuje stanowisko w „{name}” ({post}) — przez {actor.username}",
            details={"action": action, **details}, user_id=actor.id, ip=meta["ip"],
        )


def _stage_snapshot(session: Session, dept_ids) -> tuple[set[int], dict]:
    """Stan wniosków w toku w komórkach `dept_ids` PRZED zmianą struktury —
    dla `_resync_stage` (patrz services.workflow.resync_manager_stage)."""
    from services.workflow import manager_stage_snapshot
    ids = set(dept_ids or ())
    return ids, manager_stage_snapshot(session, ids)


def _resync_stage(session: Session, snap: tuple[set[int], dict], reason: str,
                  dept_ids=None) -> None:
    """Po zmianie struktury (już zatwierdzonej): zwolnij nieważne przejęcia
    wniosków w toku i powiadom nowych adresatów kroku; commit."""
    from services.workflow import resync_manager_stage
    ids, before = snap
    resync_manager_stage(session, ids if dept_ids is None else dept_ids,
                         before=before, reason=reason)
    session.commit()


def _all_dept_ids(session: Session) -> set[int]:
    return {int(x) for x in session.exec(select(Department.id)).all()}


# Komórki zarchiwizowane przez superadmina (force-delete) — znikają ze
# wszystkich list, wyborów, dopasowań importu AD i edycji; zostają w bazie
# wyłącznie dla historii wniosków.
_NOT_ARCHIVED = Department.archived_at == None  # noqa: E711


def _live_dept(session: Session, dept_id: Optional[int]) -> Optional[Department]:
    """Komórka o danym id, o ile istnieje i NIE jest zarchiwizowana (id spoza
    zakresu bazy — jak nieistniejąca, bez OverflowError)."""
    from services.structure import db_int_ok
    if dept_id is None or not db_int_ok(dept_id):
        return None
    dept = session.get(Department, dept_id)
    if not dept or getattr(dept, "archived_at", None):
        return None
    return dept


def _get_unit(session: Session, unit_id: Optional[int]) -> Optional[Unit]:
    """Jednostka o danym id albo None (także dla id spoza zakresu bazy)."""
    from services.structure import db_int_ok
    if unit_id is None or not db_int_ok(unit_id):
        return None
    return session.get(Unit, unit_id)


def _guard_self_hr(session: Session, current_user: User, dept: "Department") -> None:
    """Admin (nie superadmin) nie oznacza własnej komórki jako kadrowej (is_hr) —
    pracownik takiej komórki dostaje uprawnienia kadr."""
    if (not has_role(current_user, "superadmin") and dept.id is not None
            and current_user.department_id == dept.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może oznaczyć własnej komórki jako kadrowej — poproś o to superadmina",
        )


SUPERADMIN_POST_MSG = "Superadmin to konto awaryjne — nie pełni funkcji w strukturze"


def _guard_superadmin_post(session: Session, user_id: Optional[int]) -> None:
    """Superadmin (konto awaryjne / konfiguracyjne) nie obejmuje stanowisk
    w strukturze: kierownika komórki, dyrektora jednostki ani zastępcy."""
    if not user_id:
        return
    from services.structure import db_int_ok
    if not db_int_ok(user_id):
        raise HTTPException(400, "Wskazana osoba nie istnieje")
    u = session.get(User, user_id)
    if u and has_role(u, "superadmin"):
        raise HTTPException(400, SUPERADMIN_POST_MSG)


# ---------------------------------------------------------------------------
# Jednostki
# ---------------------------------------------------------------------------

class UnitCreate(BaseModel):
    name: str
    code: Optional[str] = None


class UnitRead(BaseModel):
    id: int
    name: str
    code: Optional[str]
    description: Optional[str] = None
    is_active: bool
    # Kierownik CAŁEJ jednostki (podgląd uprawnień + wnioskowanie za pracowników).
    manager_user_id: Optional[int] = None
    manager_name: Optional[str] = None


class UnitUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    manager_user_id: Optional[int] = None    # None w patchu = zdejmij kierownika


def _unit_read(session: Session, unit: Unit) -> "UnitRead":
    mgr_name = None
    if unit.manager_user_id:
        mgr = session.get(User, unit.manager_user_id)
        mgr_name = (mgr.full_name or mgr.username) if mgr else None
    return UnitRead(
        id=unit.id, name=unit.name, code=unit.code,
        description=getattr(unit, "description", None), is_active=unit.is_active,
        manager_user_id=unit.manager_user_id, manager_name=mgr_name,
    )


@router.get("/", response_model=list[UnitRead])
def list_units(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    return [_unit_read(session, u) for u in session.exec(select(Unit).order_by(Unit.name)).all()]


@router.get("/active", response_model=list[UnitRead])
def list_active_units(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Aktywne jednostki — dla każdego zalogowanego wszystkie (komórka kadrowa
    obsługuje całą organizację; dawne przypisania kadr do jednostek nie
    ograniczają już widoku)."""
    stmt = select(Unit).where(Unit.is_active == True)  # noqa: E712
    return session.exec(stmt.order_by(Unit.name)).all()


@router.post("/", response_model=UnitRead, status_code=status.HTTP_201_CREATED)
def create_unit(
    data: UnitCreate,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    from services.structure import clean_model_fields, name_spec, text_spec
    clean_model_fields(data, {"name": name_spec("nazwa jednostki"), "code": text_spec("kod")})
    unit = Unit(name=data.name, code=data.code)
    session.add(unit); session.commit(); session.refresh(unit)
    return unit


@router.patch("/{unit_id}", response_model=UnitRead)
def update_unit(
    unit_id: int,
    data: UnitUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    unit = _get_unit(session, unit_id)
    if not unit:
        raise HTTPException(404, "Jednostka nie istnieje")
    from services.structure import (
        clean_model_fields, description_spec, name_spec, text_spec,
    )
    clean_model_fields(data, {"name": name_spec("nazwa jednostki"), "code": text_spec("kod"),
                              "description": description_spec()})
    prev_manager_id = unit.manager_user_id
    # exclude_unset: pozwala jawnie zdjąć kierownika (manager_user_id=None w patchu),
    # nie gubiąc przy tym pozostałych pól.
    payload = data.model_dump(exclude_unset=True)
    if "manager_user_id" in payload and payload["manager_user_id"] != prev_manager_id:
        _guard_self_post(current_user, payload["manager_user_id"])
        _guard_superadmin_post(session, payload["manager_user_id"])
    if "manager_user_id" in payload and payload["manager_user_id"]:
        mgr = session.get(User, payload["manager_user_id"])
        if not mgr:
            raise HTTPException(400, "Wskazany kierownik jednostki nie istnieje")
    director_changed = ("manager_user_id" in payload
                        and payload["manager_user_id"] != prev_manager_id)
    if director_changed:
        from services.workflow import unit_dept_ids
        snap = _stage_snapshot(session, unit_dept_ids(session, unit.id))
        orphans_before = _higher_orphan_ids(session, snap[0])
    for field, value in payload.items():
        setattr(unit, field, value)
    session.add(unit); session.commit(); session.refresh(unit)
    # Struktura → rola: kierownik jednostki dostaje rolę `manager`, poprzedni
    # traci ją, jeśli nic już nie prowadzi.
    if "manager_user_id" in payload:
        from services.org_sync import sync_after_unit_manager_change
        sync_after_unit_manager_change(session, prev_manager_id, unit.manager_user_id)
        session.commit(); session.refresh(unit)
        if director_changed:
            # Dyrektor jednostki jest przełożonym we wszystkich jej komórkach —
            # jego przejęcia tracą ważność, zmienia się adresat rezerwowy.
            _resync_stage(session, snap, "Zmiana dyrektora jednostki")
            if _report_higher_orphans(session, request, current_user, snap[0],
                                      orphans_before, f"zmiana dyrektora jednostki „{unit.name}”"):
                session.commit()
            session.refresh(unit)
        _audit_post_change(session, request, current_user, action="unit.manager_changed",
                           target_type="unit", target_id=unit.id, name=unit.name,
                           old_user_id=prev_manager_id, new_user_id=unit.manager_user_id)
    return _unit_read(session, unit)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(
    unit_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    unit = _get_unit(session, unit_id)
    if not unit:
        raise HTTPException(404, "Jednostka nie istnieje")
    # sprawdź czy ma wydziały
    if session.exec(select(Department).where(Department.unit_id == unit_id)
                    .where(_NOT_ARCHIVED)).first():
        raise HTTPException(400, "Nie można usunąć jednostki — posiada wydziały")
    # Komórki zarchiwizowane zostają dla historii wniosków — jednostki z nimi
    # nie da się usunąć (wnioski wskazują na jednostkę); można ją wyłączyć.
    if session.exec(select(Department).where(Department.unit_id == unit_id)).first():
        raise HTTPException(400,
            "Nie można usunąć jednostki — zawiera zarchiwizowane komórki z historią "
            "wniosków. Wyłącz jednostkę zamiast ją usuwać.")
    # Dawne przypisania kadr do jednostek (UserUnit) niczego już nie
    # ograniczają (kadry obsługują całą organizację) — nie blokują usunięcia.
    from sqlalchemy import delete as _delete
    from models import UserUnit
    session.execute(_delete(UserUnit).where(UserUnit.unit_id == unit_id))
    session.delete(unit)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Nie można usunąć jednostki — jest powiązana z wnioskami lub systemami.")


# ---------------------------------------------------------------------------
# Wydziały
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    unit_id: int
    name: str
    description: Optional[str] = None
    kind: str = "department"                    # department / section / standalone
    parent_dept_id: Optional[int] = None
    manager_user_id: Optional[int] = None
    requires_higher_approval: bool = False
    is_hr: bool = False


class DepartmentRead(BaseModel):
    id: int
    unit_id: int
    parent_dept_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    kind: str = "department"
    manager_user_id: Optional[int]
    manager_name: Optional[str] = None
    is_active: bool
    requires_higher_approval: bool = False
    is_hr: bool = False


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    parent_dept_id: Optional[int] = None        # None = brak zmiany (użyj SENTINEL niżej)
    manager_user_id: Optional[int] = None
    is_active: Optional[bool] = None
    requires_higher_approval: Optional[bool] = None
    is_hr: Optional[bool] = None


def _validate_kind(kind: Optional[str]) -> None:
    from models import DEPARTMENT_KINDS
    if kind is None:
        return
    if kind not in DEPARTMENT_KINDS:
        raise HTTPException(
            400,
            f"Nieznany typ węzła: {kind!r}. "
            f"Dozwolone: {', '.join(DEPARTMENT_KINDS)}.",
        )


def _validate_no_cycle(session: Session, dept_id: int, new_parent_id: Optional[int]) -> None:
    """Uniemożliw ustawienie rodzica tworzącego cykl (rodzic-w-poddrzewie)."""
    if new_parent_id is None:
        return
    if new_parent_id == dept_id:
        raise HTTPException(400, "Wydział nie może być własnym rodzicem")
    visited: set[int] = set()
    cur = new_parent_id
    while cur is not None and cur not in visited:
        if cur == dept_id:
            raise HTTPException(400, "Wykryto cykl w hierarchii — nieprawidłowy rodzic")
        visited.add(cur)
        parent = session.get(Department, cur)
        if not parent:
            raise HTTPException(400, f"Rodzic id={cur} nie istnieje")
        cur = parent.parent_dept_id


def _enrich_dept(dept: Department, session: Session) -> DepartmentRead:
    mgr_name = None
    if dept.manager_user_id:
        mgr = session.get(User, dept.manager_user_id)
        mgr_name = (mgr.full_name or mgr.username) if mgr else None
    return DepartmentRead(
        id=dept.id, unit_id=dept.unit_id, parent_dept_id=dept.parent_dept_id,
        name=dept.name, description=getattr(dept, "description", None),
        kind=dept.kind or "department",
        manager_user_id=dept.manager_user_id,
        manager_name=mgr_name, is_active=dept.is_active,
        requires_higher_approval=bool(dept.requires_higher_approval),
        is_hr=bool(getattr(dept, "is_hr", False)),
    )


def _validate_higher_approval(dept: Department, session: Session, *, enabling: bool) -> None:
    """Włączenie akceptacji wyższego rzędu wymaga osoby, która może ją wykonać:
    aktywnego kierownika lub zastępcy komórki wyżej albo dyrektora jednostki
    (`services.structure.higher_approvers`) — inaczej wnioski utknęłyby na tym
    kroku.

    Sprawdzamy WYŁĄCZNIE przy włączaniu flagi (`enabling`). Komórka, która
    straciła taką osobę później (zmiana kierownika rodzica, usunięcie rodzica,
    przeniesienie), zachowuje flagę i można ją dalej edytować — problem
    zgłasza lista kontrolna (/settings/health)."""
    if not enabling or not dept.requires_higher_approval:
        return
    from services.structure import higher_approvers
    if higher_approvers(session, dept):
        return
    # Komórka nadrzędna MA kierownika, ale nie może on zatwierdzić (np. kieruje
    # też tą komórką) — dopuszczamy jak dotąd; wnioski przejmie rezerwa
    # superadmina, a lista kontrolna zgłasza problem.
    parent = session.get(Department, dept.parent_dept_id) if dept.parent_dept_id else None
    if parent is not None and parent.manager_user_id:
        return
    if not dept.parent_dept_id:
        raise HTTPException(
            400,
            "Nie można włączyć akceptacji wyższego rzędu — komórka nie ma komórki nadrzędnej, "
            "a jednostka nie ma dyrektora.")
    raise HTTPException(
        400,
        "Nie można włączyć akceptacji wyższego rzędu — nad komórką nie ma nikogo, kto mógłby "
        "ją wykonać (kierownika ani zastępcy komórki nadrzędnej, ani dyrektora jednostki).")


def _higher_orphan_ids(session: Session, dept_ids) -> set[int]:
    """Komórki z `dept_ids`, których akceptacji wyższej nie ma kto wykonać."""
    from services.structure import higher_approval_orphans
    return {d.id for d in higher_approval_orphans(session, dept_ids)}


def _report_higher_orphans(session: Session, request: Optional[Request], actor: User,
                           dept_ids, before: set[int], cause: str) -> list[int]:
    """Po zmianie struktury: komórki z akceptacją wyższą, które przez tę zmianę
    straciły osobę uprawnioną do jej wykonania — flaga zostaje (edycji komórki
    to nie blokuje), wpis w dzienniku i ostrzeżenie w logu; lista kontrolna
    pokazuje je jako błąd. Zwraca id takich komórek."""
    new = sorted(_higher_orphan_ids(session, dept_ids) - set(before))
    if not new:
        return []
    import logging
    from services.audit import record_event, request_meta
    names = [d.name for d in (session.get(Department, i) for i in new) if d]
    logging.getLogger("szup.units").warning(
        "Akceptacja wyższa bez osoby uprawnionej po zmianie (%s): %s", cause, ", ".join(names))
    meta = request_meta(request)
    record_event(session, action="department.higher_approval_unreachable",
                 user_id=actor.id, username=actor.username, target_type="department",
                 target_id=new[0], ip=meta["ip"], user_agent=meta["user_agent"],
                 details={"department_ids": new, "names": names, "cause": cause})
    return new


@router.get("/departments/all", response_model=list[DepartmentRead])
def list_all_departments(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    depts = session.exec(
        select(Department).where(_NOT_ARCHIVED).order_by(Department.name)).all()
    return [_enrich_dept(d, session) for d in depts]


@router.get("/departments/active", response_model=list[DepartmentRead])
def list_active_departments(
    unit_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Aktywne (niezarchiwizowane) komórki — wszystkie, opcjonalnie z jednostki."""
    stmt = (select(Department).where(Department.is_active == True)  # noqa: E712
            .where(_NOT_ARCHIVED))
    if unit_id:
        stmt = stmt.where(Department.unit_id == unit_id)
    depts = session.exec(stmt.order_by(Department.name)).all()
    return [_enrich_dept(d, session) for d in depts]


@router.post("/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
def create_department(
    data: DepartmentCreate,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    from services.structure import clean_model_fields, description_spec, name_spec
    clean_model_fields(data, {"name": name_spec("nazwa komórki"),
                              "description": description_spec()})
    if data.kind != "standalone":
        _guard_self_post(current_user, data.manager_user_id)
        _guard_superadmin_post(session, data.manager_user_id)
    if not _get_unit(session, data.unit_id):
        raise HTTPException(400, "Jednostka nie istnieje")
    _validate_kind(data.kind)
    if data.parent_dept_id is not None:
        parent = _live_dept(session, data.parent_dept_id)
        if not parent:
            raise HTTPException(400, "Wydział nadrzędny nie istnieje")
        if parent.unit_id != data.unit_id:
            raise HTTPException(400, "Wydział nadrzędny należy do innej jednostki")
    # Samodzielne stanowisko nie ma kierownika — podlega kierownikowi wyżej.
    mgr = None if (data.kind == "standalone") else data.manager_user_id
    dept = Department(
        unit_id=data.unit_id, name=data.name,
        description=(data.description or None),
        kind=data.kind or "department",
        parent_dept_id=data.parent_dept_id,
        manager_user_id=mgr,
        requires_higher_approval=data.requires_higher_approval,
        is_hr=data.is_hr,
    )
    _validate_higher_approval(dept, session, enabling=bool(data.requires_higher_approval))
    session.add(dept); session.commit(); session.refresh(dept)
    # Struktura → rola: nowy kierownik dostaje rolę „manager".
    from services.org_sync import sync_after_manager_change
    sync_after_manager_change(session, None, dept.manager_user_id)
    session.commit(); session.refresh(dept)
    _audit_post_change(session, request, current_user, action="department.manager_changed",
                       target_type="department", target_id=dept.id, name=dept.name,
                       old_user_id=None, new_user_id=dept.manager_user_id)
    if dept.is_hr:
        _emit_hr_flag_change(session, request, current_user, dept, True)
    return _enrich_dept(dept, session)


def _emit_hr_flag_change(session: Session, request: Request, actor: User, dept: Department,
                         enabled: bool) -> None:
    """Zdarzenie bezpieczeństwa przy oznaczeniu komórki jako kadrowej (lub zdjęciu
    oznaczenia) — członkowie zyskują/tracą zdolność kadrową dla wszystkich jednostek."""
    from services.security_events import emit, plural
    from services.audit import request_meta
    members = session.exec(select(User).where(User.department_id == dept.id)).all()
    emit(session, event_type="department.hr_flag_changed", source="units",
         severity=SecuritySeverity.medium,
         summary=(f"Komórka „{dept.name}” {'oznaczona jako kadrowa' if enabled else 'nie jest już kadrowa'} "
                  f"przez {actor.username} ({len(members)} "
                  f"{plural(len(members), 'osoba', 'osoby', 'osób')})"),
         details={"department_id": dept.id, "enabled": enabled,
                  "member_user_ids": [u.id for u in members]},
         user_id=actor.id, ip=request_meta(request)["ip"])


@router.patch("/departments/{dept_id}", response_model=DepartmentRead)
def update_department(
    dept_id: int,
    data: DepartmentUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    dept = _live_dept(session, dept_id)
    if not dept:
        raise HTTPException(404, "Wydział nie istnieje")
    from services.structure import clean_model_fields, description_spec, name_spec
    clean_model_fields(data, {"name": name_spec("nazwa komórki"),
                              "description": description_spec()})
    prev_manager_id = dept.manager_user_id   # do synchronizacji roli po zmianie
    # requires_higher_approval=False jest prawidłową wartością (nie pomijaj None-em)
    payload = data.model_dump(exclude_unset=True)
    if "manager_user_id" in payload and payload["manager_user_id"] != prev_manager_id:
        _guard_self_post(current_user, payload["manager_user_id"])
        _guard_superadmin_post(session, payload["manager_user_id"])
    if payload.get("is_hr") and not dept.is_hr:
        _guard_self_hr(session, current_user, dept)

    # Walidacja typu (jeśli w patchu)
    if "kind" in payload:
        _validate_kind(payload["kind"])

    # Walidacja parent_dept_id (jeśli w patchu) — brak cyklu + ta sama jednostka.
    if "parent_dept_id" in payload:
        new_parent = payload["parent_dept_id"]
        if new_parent is not None:
            parent = _live_dept(session, new_parent)
            if not parent:
                raise HTTPException(400, "Wydział nadrzędny nie istnieje")
            if parent.unit_id != dept.unit_id:
                raise HTTPException(400, "Wydział nadrzędny należy do innej jednostki")
        _validate_no_cycle(session, dept.id, new_parent)

    # Zmiana kierownika / podległości / typu komórki zmienia osobę
    # odpowiedzialną za wnioski w toku w całym jej poddrzewie (i ważność
    # przejęć) — stan sprzed zmiany do porządków po zapisie.
    structural = (
        ("manager_user_id" in payload and payload["manager_user_id"] != prev_manager_id)
        or ("parent_dept_id" in payload and payload["parent_dept_id"] != dept.parent_dept_id)
        or ("kind" in payload and payload["kind"] != dept.kind)
    )
    enabling_higher = bool(payload.get("requires_higher_approval")) and not dept.requires_higher_approval
    if structural:
        from services.workflow import subtree_dept_ids
        snap = _stage_snapshot(session, subtree_dept_ids(session, {dept.id}))
        orphans_before = _higher_orphan_ids(session, snap[0])

    hr_flag_changed = "is_hr" in payload and bool(payload["is_hr"]) != bool(dept.is_hr)
    for field, value in payload.items():
        setattr(dept, field, value)
    # Samodzielne stanowisko nie ma kierownika — zdejmujemy go, gdy komórka
    # staje się (albo pozostaje) samodzielnym stanowiskiem.
    manager_cleared = False
    if dept.kind == "standalone" and dept.manager_user_id:
        dept.manager_user_id = None
        manager_cleared = True
    _validate_higher_approval(dept, session, enabling=enabling_higher)
    session.add(dept); session.commit(); session.refresh(dept)
    if hr_flag_changed:
        _emit_hr_flag_change(session, request, current_user, dept, bool(dept.is_hr))
    # Struktura → rola: nadaj rolę nowemu kierownikowi, posprzątaj po poprzednim.
    if "manager_user_id" in payload or manager_cleared:
        from services.org_sync import sync_after_manager_change
        sync_after_manager_change(session, prev_manager_id, dept.manager_user_id)
        session.commit(); session.refresh(dept)
        _audit_post_change(session, request, current_user, action="department.manager_changed",
                           target_type="department", target_id=dept.id, name=dept.name,
                           old_user_id=prev_manager_id, new_user_id=dept.manager_user_id)
    if structural:
        _resync_stage(session, snap, f"Zmiana w strukturze komórki „{dept.name}”")
        if _report_higher_orphans(session, request, current_user, snap[0], orphans_before,
                                  f"zmiana w strukturze komórki „{dept.name}”"):
            session.commit()
        session.refresh(dept)
    return _enrich_dept(dept, session)


class AutoManagersIn(BaseModel):
    # Nadpisać już ustawionych kierowników? Domyślnie NIE — uzupełniamy tylko puste.
    overwrite: bool = False


class AutoManagersResult(BaseModel):
    assigned: int
    skipped_has_manager: int
    ambiguous: int
    no_candidate: int
    details: list[str]


@router.post("/departments/auto-managers", response_model=AutoManagersResult)
def auto_assign_managers(
    data: AutoManagersIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Przypisz kierowników komórek na podstawie stanowiska z AD (`title`
    zawiera „kierownik"/„dyrektor"/„naczelnik"). Dla każdej komórki szukamy
    AKTYWNYCH pracowników TEJ komórki o stanowisku kierowniczym:
      - dokładnie 1 kandydat  → przypisujemy go kierownikiem (+ rola),
      - >1 kandydatów         → zostawiamy do ręcznej decyzji (ambiguous),
      - 0                     → pomijamy.
    Domyślnie nie ruszamy komórek, które już mają kierownika.
    """
    from services.org_sync import title_indicates_manager, sync_after_manager_change

    assigned = skipped = ambiguous = none = 0
    details: list[str] = []
    changes: list[tuple[Department, Optional[int], int]] = []

    users = session.exec(select(User).where(User.is_active == True)).all()  # noqa: E712
    # Admin (nie superadmin) nie może w ten sposób przypisać SIEBIE (_guard_self_post).
    if not has_role(current_user, "superadmin"):
        users = [u for u in users if u.id != current_user.id]
    # Superadmin (konto awaryjne) nigdy nie zostaje kierownikiem komórki.
    users = [u for u in users if not has_role(u, "superadmin")]
    by_dept: dict[int, list[User]] = {}
    for u in users:
        if u.department_id and title_indicates_manager(getattr(u, "title", None)):
            by_dept.setdefault(u.department_id, []).append(u)

    snap = _stage_snapshot(session, _all_dept_ids(session))
    for dept in session.exec(select(Department).where(Department.is_active == True)  # noqa: E712
                             .where(_NOT_ARCHIVED)).all():
        if dept.kind == "standalone":
            continue  # samodzielne stanowisko nie ma kierownika
        if dept.manager_user_id and not data.overwrite:
            skipped += 1
            continue
        candidates = by_dept.get(dept.id, [])
        if len(candidates) == 0:
            none += 1
            continue
        if len(candidates) > 1:
            ambiguous += 1
            names = ", ".join((c.full_name or c.username) for c in candidates)
            details.append(f"„{dept.name}” — kilku kandydatów ({names}) — ustaw ręcznie")
            continue
        chosen = candidates[0]
        if dept.manager_user_id == chosen.id:
            skipped += 1
            continue
        prev = dept.manager_user_id
        dept.manager_user_id = chosen.id
        session.add(dept)
        sync_after_manager_change(session, prev, chosen.id)
        changes.append((dept, prev, chosen.id))
        assigned += 1
        who = chosen.full_name or chosen.username
        extra = f" ({chosen.title})" if getattr(chosen, "title", None) else ""
        details.append(f"„{dept.name}” → {who}{extra}")

    session.commit()
    if changes:
        from services.workflow import subtree_dept_ids
        _resync_stage(session, snap, "Automatyczne przypisanie kierowników komórek",
                      dept_ids=subtree_dept_ids(session, {d.id for d, _p, _n in changes}))
    for dept, prev, new in changes:
        _audit_post_change(session, request, current_user, action="department.manager_changed",
                           target_type="department", target_id=dept.id, name=dept.name,
                           old_user_id=prev, new_user_id=new, extra={"source": "auto-managers"})
    return AutoManagersResult(
        assigned=assigned, skipped_has_manager=skipped,
        ambiguous=ambiguous, no_candidate=none, details=details)


@router.delete("/departments/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    dept_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    dept = _live_dept(session, dept_id)
    if not dept:
        raise HTTPException(404, "Wydział nie istnieje")
    from models import AccessRequest
    if session.exec(select(AccessRequest).where(AccessRequest.department_id == dept_id)).first():
        raise HTTPException(400, "Nie można usunąć wydziału — posiada wnioski")
    if session.exec(select(Department).where(Department.parent_dept_id == dept_id)).first():
        raise HTTPException(400, "Nie można usunąć wydziału — posiada podrzędne wydziały")
    ex_manager_id = dept.manager_user_id
    session.delete(dept)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Nie można usunąć wydziału — jest powiązany z użytkownikami lub zastępcami.")
    # Komórka zniknęła — jeśli jej kierownik nie kieruje już niczym, zdejmij rolę.
    from services.org_sync import revoke_manager_role_if_unused
    if revoke_manager_role_if_unused(session, ex_manager_id):
        session.commit()


# ---------------------------------------------------------------------------
# Usunięcie komórki przez superadmina (także komórki z historią)
# ---------------------------------------------------------------------------

from models import RequestStatus as _RS  # noqa: E402
_ACTIVE_REQUEST_STATUSES = (_RS.pending_selection, _RS.pending_manager, _RS.pending_it)


FORCE_DELETE_REASON_MAX = 1000


class DepartmentForceDeleteIn(BaseModel):
    reason: str                      # wymagany — trafia do audytu i odrzucanych wniosków
    password: str                    # potwierdzenie hasłem wykonującego


class DepartmentForceDeleteOut(BaseModel):
    mode: str                        # "deleted" (usunięta) | "archived" (zarchiwizowana)
    department_id: int
    # Pracownicy odpięci od zarchiwizowanej komórki — kadry składają dla nich
    # wnioski o ustanie (bez komórki) albo admin przypisuje ich do innej.
    # 3.11: lista [{id, full_name, login}] (wcześniej liczba).
    detached_users: list[dict] = []
    detached_user_ids: list[int] = []
    removed_deputies: int
    reparented_department_ids: list[int]
    rejected_request_ids: list[int]
    # Wnioski w realizacji IT z częścią pozycji już zrealizowanych — nie są
    # odrzucane: pozostałe pozycje odmówiono, a wniosek zamknięto, żeby
    # nadane w systemach uprawnienia zostały w rejestrze.
    completed_request_ids: list[int] = []
    # Wnioski z niewykonanymi pozycjami odebrania — zostają w kolejce IT
    # (pending_it); uprawnienia znikają po realizacji przez IT.
    it_pending_request_ids: list[int] = []
    # Komórki z akceptacją wyższą, które przez usunięcie straciły osobę
    # uprawnioną do jej wykonania (zgłasza je też lista kontrolna).
    higher_approval_unreachable_ids: list[int] = []


def _active_node(session: Session, inst) -> dict:
    import json as _json
    from services.workflow import find_node
    node = None
    try:
        node = find_node(_json.loads(inst.template_snapshot), inst.current_node_id) \
            if inst.current_node_id else None
    except Exception:
        node = None
    return node or {"id": inst.current_node_id or "system", "type": "system"}


def _system_reject_request(session: Session, req, actor: User, comment: str,
                           dept_id: Optional[int], extra_ids=(),
                           payload: Optional[dict] = None) -> None:
    """Odrzucenie wniosku w toku z powodu usunięcia komórki — poza `can_act`
    (superadmin nie jest uczestnikiem obiegu). Zapisuje podpisany krok
    `reject` z aktorem-superadminem w łańcuchu kroków, zamyka instancję,
    zwalnia przejęcie i powiadamia twórcę wniosku (jak zwykłe odrzucenie).

    Na etapie kierownika komórki wersja robocza przestaje obowiązywać: notatka
    robocza (`manager_comment`) zostaje zastąpiona powodem odrzucenia — inaczej
    po archiwizacji zobaczyliby ją IT i administrator. `extra_ids` — dodatkowi
    adresaci powiadomienia (kierownik i zastępcy usuwanej komórki).
    `payload` — opis operacji systemowej w podpisanym kroku (domyślnie
    usunięcie komórki; usunięcie grupy uprawnień podaje własny)."""
    from datetime import datetime as _dt
    from models import RequestStatus, WorkflowInstanceStatus, WorkflowStepAction
    from services.workflow import (
        MANAGER_STAGE_TYPES, _notify_request_rejected, _record_step,
        _sync_request_status, clear_take_over, instance_of,
    )
    inst = instance_of(session, req)
    if inst and inst.status == WorkflowInstanceStatus.active:
        node = _active_node(session, inst)
        _record_step(session, inst, node, action=WorkflowStepAction.reject,
                     actor_user=actor, comment=comment,
                     payload=payload or {"system": "department_deleted",
                                         "department_id": dept_id})
        inst.status = WorkflowInstanceStatus.rejected
        inst.completed_at = _dt.utcnow()
        session.add(inst)
        _sync_request_status(req, inst)
        manager_stage = node.get("type") in MANAGER_STAGE_TYPES
    else:
        # Starszy wniosek bez obiegu — sam status.
        manager_stage = req.status in (RequestStatus.pending_selection,
                                       RequestStatus.pending_manager)
        req.status = RequestStatus.rejected
        req.rejected_at = req.rejected_at or _dt.utcnow()
        req.current_node_type = None
    if manager_stage or getattr(req, "draft_saved_at", None):
        req.manager_comment = comment
        req.draft_saved_at = None
    clear_take_over(req)
    session.add(req)
    _notify_request_rejected(session, req, actor, comment,
                             extra_ids=extra_ids if manager_stage else ())


def _has_fulfilled_items(session: Session, req) -> bool:
    from models import RequestItem
    return session.exec(
        select(RequestItem.id).where(RequestItem.request_id == req.id)
        .where(RequestItem.fulfilled == True)  # noqa: E712
    ).first() is not None


def _system_complete_partial(session: Session, req, actor: User, comment: str,
                             dept_id: int) -> list[int]:
    """Wniosek w realizacji IT z pozycjami już odhaczonymi jako zrealizowane
    (IT nadało je w systemach) przy usunięciu komórki: zamiast odrzucenia
    (które zostawiłoby nadane uprawnienia poza rejestrem — reguła częściowej
    realizacji) pozostałe pozycje NADANIA są odmawiane z powodem, a wniosek
    zamykany jako zrealizowany. Wniosek z niewykonanymi pozycjami odebrania
    tu nie trafia — zostaje w kolejce IT (`_system_forward_to_it`). Zwraca id
    odmówionych pozycji."""
    from datetime import datetime as _dt
    from models import RequestItem, WorkflowInstanceStatus, WorkflowStepAction
    from services.workflow import (
        _notify_request_completed, _record_step, _sync_request_status,
        clear_take_over, instance_of,
    )
    now = _dt.utcnow()
    denied: list[int] = []
    for it in session.exec(select(RequestItem).where(RequestItem.request_id == req.id)
                           .order_by(RequestItem.id)).all():
        if it.fulfilled or it.denied or (it.kind or "grant") == "revoke":
            continue
        it.denied = True
        it.deny_comment = comment[:FORCE_DELETE_REASON_MAX + 40]
        it.denied_by_user_id = actor.id
        it.denied_at = now
        denied.append(it.id)
        session.add(it)
    inst = instance_of(session, req)
    if inst and inst.status == WorkflowInstanceStatus.active:
        node = _active_node(session, inst)
        _record_step(session, inst, node, action=WorkflowStepAction.execute,
                     actor_user=actor, comment=comment,
                     payload={"system": "department_deleted", "department_id": dept_id,
                              "partial": True, "denied_item_ids": denied})
        inst.status = WorkflowInstanceStatus.completed
        inst.completed_at = now
        session.add(inst)
        _sync_request_status(req, inst)
    else:
        from models import RequestStatus
        req.status = RequestStatus.completed
        req.current_node_type = None
    req.completed_at = req.completed_at or now
    req.completed_by_id = actor.id
    req.it_comment = comment
    clear_take_over(req)
    session.add(req)
    session.flush()
    _notify_request_completed(session, req, actor)
    return denied


def _has_open_revoke_items(session: Session, req) -> bool:
    """Czy wniosek ma pozycje odebrania jeszcze niewykonane przez IT."""
    from models import RequestItem
    return any((it.kind or "grant") == "revoke" and not it.fulfilled and not it.denied
               for it in session.exec(select(RequestItem)
                                      .where(RequestItem.request_id == req.id)).all())


def _system_forward_to_it(session: Session, req, actor: User, comment: str) -> list[int]:
    """Wniosek w realizacji IT z niewykonanymi pozycjami ODEBRANIA przy
    likwidacji komórki (3.11): odebrań NIE oznaczamy jako zrealizowanych —
    wniosek zostaje w kolejce IT (`pending_it`), a IT i helpdesk dostają
    powiadomienie. Uprawnienie efektywne znika dopiero po realizacji przez IT.
    Niezrealizowane pozycje NADANIA są odmawiane (komórka nie istnieje).
    Starszy wniosek bez obiegu dostaje obieg systemowy (realizacja IT).
    Zwraca id odmówionych pozycji."""
    from datetime import datetime as _dt
    from models import RequestItem, WorkflowInstanceStatus
    from services.workflow import _notify_stage, clear_take_over, instance_of
    now = _dt.utcnow()
    denied: list[int] = []
    for it in session.exec(select(RequestItem).where(RequestItem.request_id == req.id)
                           .order_by(RequestItem.id)).all():
        if it.fulfilled or it.denied or (it.kind or "grant") == "revoke":
            continue
        it.denied = True
        it.deny_comment = comment[:FORCE_DELETE_REASON_MAX + 40]
        it.denied_by_user_id = actor.id
        it.denied_at = now
        denied.append(it.id)
        session.add(it)
    clear_take_over(req)
    session.add(req)
    session.flush()
    inst = instance_of(session, req)
    if inst is None:
        from routers.systems import start_system_revoke
        start_system_revoke(session, req)
    elif inst.status == WorkflowInstanceStatus.active:
        _notify_stage(session, req, _active_node(session, inst), None, actor)
    return denied


@router.post("/departments/{dept_id}/force-delete", response_model=DepartmentForceDeleteOut)
def force_delete_department(
    dept_id: int,
    data: DepartmentForceDeleteIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_superadmin),
):
    """Usunięcie komórki przez superadmina — także takiej, do której odwołują
    się wnioski, pracownicy lub zastępcy.

    Komórki podrzędne trafiają pod rodzica usuwanej komórki (nie są usuwane).
    Bez powiązań → usunięcie z bazy. Z powiązaniami → ARCHIWIZACJA: komórka
    zostaje dla historii (is_active=False, archived_at/archived_reason), znika
    ze wszystkich list; pracownicy są odpinani (lista w `detached_user_ids` —
    kadry składają dla nich wnioski o ustanie), zastępcy i kierownik zdejmowani,
    a wnioski w toku tej komórki odrzucane z podanym powodem. Wyjątki dla
    wniosków w realizacji IT: z niewykonanymi pozycjami odebrania — zostają
    w kolejce IT (niezrealizowane nadania odmówione, mail do IT i helpdesku);
    z pozycjami już zrealizowanymi — zamykane (pozostałe pozycje odmówione),
    żeby nadane uprawnienia zostały w rejestrze.
    """
    from datetime import datetime as _dt
    from models import AccessRequest, PermissionDeclaration
    from services.audit import confirm_password, record_event, request_meta
    from services.org_sync import revoke_manager_role_if_unused
    from services.security_events import emit as emit_security_event
    from services.workflow import subtree_dept_ids

    reason = (data.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Podaj powód usunięcia komórki")
    if len(reason) > FORCE_DELETE_REASON_MAX:
        raise HTTPException(400, f"Powód usunięcia komórki może mieć najwyżej "
                                 f"{FORCE_DELETE_REASON_MAX} znaków")
    dept = _live_dept(session, dept_id)
    if not dept:
        raise HTTPException(404, "Wydział nie istnieje")
    meta = request_meta(request)
    confirm_password(session, current_user, data.password,
                     operation=f"usunięcie komórki „{dept.name}”", ip=meta["ip"])

    children = session.exec(
        select(Department).where(Department.parent_dept_id == dept_id)).all()
    users = session.exec(select(User).where(User.department_id == dept_id)).all()
    deputies = session.exec(
        select(DepartmentDeputy).where(DepartmentDeputy.department_id == dept_id)).all()
    has_requests = session.exec(
        select(AccessRequest.id).where(AccessRequest.department_id == dept_id)).first() is not None
    has_declarations = session.exec(
        select(PermissionDeclaration.id)
        .where(PermissionDeclaration.department_id == dept_id)).first() is not None
    referenced = bool(users or deputies or has_requests or has_declarations)

    # Zmiana podległości dzieci i zdjęcie kierownika/zastępców zmienia osoby
    # odpowiedzialne za wnioski w toku w poddrzewie — stan sprzed zmiany.
    affected = subtree_dept_ids(session, {dept_id})
    snap = _stage_snapshot(session, affected)
    orphans_before = _higher_orphan_ids(session, affected - {dept_id})

    dept_name = dept.name
    ex_manager_id = dept.manager_user_id
    ex_deputy_ids = [d.user_id for d in deputies]
    new_parent_id = dept.parent_dept_id
    reparented = [c.id for c in children]
    for c in children:
        c.parent_dept_id = new_parent_id
        session.add(c)
    for d in deputies:
        session.delete(d)

    rejected_ids: list[int] = []
    completed_ids: list[int] = []
    it_pending_ids: list[int] = []
    denied_items: dict[int, list[int]] = {}
    ex_dn = dept.ldap_dn
    if not referenced:
        session.flush()
        session.delete(dept)
        mode = "deleted"
    else:
        mode = "archived"
        for u in users:
            u.department_id = None
            session.add(u)
        comment = f"Komórka usunięta: {reason}"
        active = session.exec(
            select(AccessRequest)
            .where(AccessRequest.department_id == dept_id)
            .where(AccessRequest.status.in_(_ACTIVE_REQUEST_STATUSES))  # type: ignore[attr-defined]
            .order_by(AccessRequest.id)
        ).all()
        # Kierownik i zastępcy likwidowanej komórki dowiadują się o odrzuceniu
        # wniosków, które czekały u nich (wersje robocze).
        stage_people = [x for x in (ex_manager_id, *ex_deputy_ids) if x]
        for req in active:
            if req.status == _RS.pending_it and _has_open_revoke_items(session, req):
                denied_items[req.id] = _system_forward_to_it(
                    session, req, current_user, comment)
                it_pending_ids.append(req.id)
                continue
            if req.status == _RS.pending_it and _has_fulfilled_items(session, req):
                denied_items[req.id] = _system_complete_partial(
                    session, req, current_user, comment, dept_id)
                completed_ids.append(req.id)
                continue
            _system_reject_request(session, req, current_user, comment, dept_id,
                                   extra_ids=stage_people)
            rejected_ids.append(req.id)
        dept.manager_user_id = None
        dept.is_active = False
        dept.requires_higher_approval = False
        dept.is_hr = False
        dept.archived_at = _dt.utcnow()
        dept.archived_reason = reason
        # Bez DN synchronizacja z AD nie dopasuje (i nie ożywi) archiwum —
        # ewentualny nowy import utworzy świeżą komórkę.
        dept.ldap_dn = None
        session.add(dept)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Nie udało się usunąć komórki — powiązania zmieniły się w trakcie. "
            "Spróbuj ponownie.")

    # Porządki po zmianie struktury (przejęcia, adresaci kroków) w poddrzewie
    # — bez samej komórki, jeśli zniknęła.
    remaining = (affected - {dept_id}) if mode == "deleted" else affected
    if remaining:
        _resync_stage(session, snap, f"Usunięcie komórki „{dept_name}”",
                      dept_ids=remaining)
    changed_roles = False
    for uid in {ex_manager_id, *ex_deputy_ids} - {None}:
        changed_roles = revoke_manager_role_if_unused(session, uid) or changed_roles
    if changed_roles:
        session.commit()
    unreachable = _report_higher_orphans(
        session, request, current_user, affected - {dept_id}, orphans_before,
        f"usunięcie komórki „{dept_name}”")

    details = {
        "name": dept_name, "mode": mode, "reason": reason,
        "detached_users": len(users) if mode == "archived" else 0,
        "detached_user_ids": [u.id for u in users] if mode == "archived" else [],
        # Wnioski z niewykonanymi odebraniami — zostają w kolejce IT.
        "it_pending_request_ids": it_pending_ids,
        "removed_deputies": ex_deputy_ids,
        "ex_manager_user_id": ex_manager_id,
        "reparented_department_ids": reparented,
        "new_parent_dept_id": new_parent_id,
        "rejected_request_ids": rejected_ids,
        # Wnioski zamknięte jako częściowo zrealizowane (pozycje odhaczone przez
        # IT zostają nadane, pozostałe odmówione): {id wniosku: [id odmówionych pozycji]}.
        "completed_request_ids": completed_ids,
        "denied_item_ids": {str(k): v for k, v in denied_items.items()},
        "higher_approval_unreachable_ids": unreachable,
    }
    if mode == "archived":
        details["ldap_dn"] = ex_dn
    record_event(session, action=f"department.force_{mode}", user_id=current_user.id,
                 username=current_user.username, target_type="department",
                 target_id=dept_id, ip=meta["ip"], user_agent=meta["user_agent"],
                 details=details)
    emit_security_event(
        session, event_type="department.force_deleted", source="units",
        severity=SecuritySeverity.high,
        summary=(f"Superadmin {current_user.username} "
                 + ("usunął" if mode == "deleted" else "zarchiwizował")
                 + f" komórkę „{dept_name}”: {reason}"),
        details={"department_id": dept_id, **details},
        user_id=current_user.id, ip=meta["ip"],
    )
    return DepartmentForceDeleteOut(
        mode=mode, department_id=dept_id,
        detached_users=[{"id": u.id, "full_name": u.full_name, "login": u.username}
                        for u in users] if mode == "archived" else [],
        detached_user_ids=details["detached_user_ids"],
        removed_deputies=len(ex_deputy_ids),
        reparented_department_ids=reparented,
        rejected_request_ids=rejected_ids,
        completed_request_ids=completed_ids,
        it_pending_request_ids=it_pending_ids,
        higher_approval_unreachable_ids=unreachable,
    )


# ---------------------------------------------------------------------------
# Import struktury z AD/LDAP
# ---------------------------------------------------------------------------

class LdapPreviewRequest(BaseModel):
    search_base: Optional[str] = None   # jeśli puste — użyj base_dn z ustawień LDAP


class LdapPreviewDept(BaseModel):
    dn: str
    name: str
    description: Optional[str] = None
    status: str        # "new" | "exists"
    existing_id: Optional[int] = None
    children: list["LdapPreviewDept"] = []


class LdapPreviewUnit(BaseModel):
    dn: str
    name: str
    description: Optional[str] = None
    status: str        # "new" | "exists"
    existing_id: Optional[int] = None
    departments: list[LdapPreviewDept]


class LdapImportDept(BaseModel):
    name: str
    dn: Optional[str] = None
    description: Optional[str] = None
    # Mapowanie ręczne: gdy admin wskaże istniejący wydział, importujemy „w niego"
    # (backfill DN, dzieci pod nim), zamiast dopasowywać/tworzyć po nazwie.
    map_to_dept_id: Optional[int] = None
    children: list["LdapImportDept"] = []


class LdapImportItem(BaseModel):
    unit_name: str
    unit_dn: Optional[str] = None
    description: Optional[str] = None
    # Mapowanie ręczne do istniejącej jednostki (zamiast dopasowania po nazwie).
    map_to_unit_id: Optional[int] = None
    departments: list[LdapImportDept]   # drzewo wydziałów


class LdapImportRequest(BaseModel):
    items: list[LdapImportItem]


LdapPreviewDept.model_rebuild()
LdapImportDept.model_rebuild()


class LdapImportResult(BaseModel):
    units_created: int
    units_skipped: int
    departments_created: int
    departments_skipped: int
    details: list[str]


@router.post("/ldap/preview", response_model=list[LdapPreviewUnit])
def ldap_preview(
    data: LdapPreviewRequest,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """
    Pobiera strukturę OU z AD/LDAP i zwraca podgląd co zostałoby zaimportowane.
    Nie modyfikuje bazy danych.
    """
    from models import LdapSettings
    cfg = session.exec(select(LdapSettings)).first()
    if not cfg or not cfg.host:
        raise HTTPException(400, "Brak konfiguracji LDAP — skonfiguruj połączenie w Ustawieniach")
    if not cfg.enabled:
        raise HTTPException(400, "LDAP nie jest włączone — włącz je w Ustawieniach")

    search_base = (data.search_base or "").strip() or cfg.base_dn
    if not search_base:
        raise HTTPException(400, "Podaj search_base lub ustaw base_dn w konfiguracji LDAP")

    try:
        from services.ldap_service import fetch_ou_structure
        raw = fetch_ou_structure(cfg, search_base)
    except Exception as exc:
        raise HTTPException(502, f"Błąd połączenia z LDAP: {exc}")

    # Enrichment — porównaj z bazą danych. Dopasowanie (jak w imporcie):
    # 1) po ldap_dn, 2) po (rodzic, nazwa), 3) po UNIKALNEJ nazwie w jednostce
    # (żeby rozpoznać istniejącą „płaską" komórkę i pokazać, że zostanie przeniesiona,
    # a nie zduplikowana).
    from services.ldap_service import normalize_dn as _ndn
    existing_units: dict[str, Unit] = {u.name: u for u in session.exec(select(Unit)).all()}
    by_parentname: dict[int, dict] = {}
    by_dn: dict[int, dict] = {}
    by_name: dict[int, dict] = {}
    for d in session.exec(select(Department).where(_NOT_ARCHIVED)).all():
        by_parentname.setdefault(d.unit_id, {})[(d.parent_dept_id, d.name)] = d
        if d.ldap_dn:
            by_dn.setdefault(d.unit_id, {})[d.ldap_dn] = d
        by_name.setdefault(d.unit_id, {}).setdefault(d.name, []).append(d)

    def _match(unit_id, parent_dept_id, child, parent_is_new):
        if not unit_id:
            return None
        ndn = _ndn(child["dn"]) if child.get("dn") else None
        if ndn:
            d = by_dn.get(unit_id, {}).get(ndn)
            if d:
                return d
        if not parent_is_new:
            d = by_parentname.get(unit_id, {}).get((parent_dept_id, child["name"]))
            if d:
                return d
        same = by_name.get(unit_id, {}).get(child["name"], [])
        if len(same) == 1:
            return same[0]
        return None

    def _walk(children: list[dict], unit_id: Optional[int],
              parent_dept_id: Optional[int], parent_is_new: bool) -> list[LdapPreviewDept]:
        out: list[LdapPreviewDept] = []
        for child in children:
            db_dept = _match(unit_id, parent_dept_id, child, parent_is_new)
            out.append(LdapPreviewDept(
                dn=child["dn"],
                name=child["name"],
                description=child.get("description"),
                status="exists" if db_dept else "new",
                existing_id=db_dept.id if db_dept else None,
                children=_walk(
                    child.get("children", []),
                    unit_id,
                    db_dept.id if db_dept else None,
                    parent_is_new or db_dept is None,
                ),
            ))
        return out

    result: list[LdapPreviewUnit] = []
    for item in raw:
        unit_db = existing_units.get(item["name"])
        result.append(LdapPreviewUnit(
            dn=item["dn"],
            name=item["name"],
            description=item.get("description"),
            status="exists" if unit_db else "new",
            existing_id=unit_db.id if unit_db else None,
            departments=_walk(
                item["departments"],
                unit_db.id if unit_db else None,
                None,
                unit_db is None,
            ),
        ))

    return result


@router.post("/ldap/import", response_model=LdapImportResult)
def ldap_import(
    data: LdapImportRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """
    Importuje zaznaczone jednostki i wydziały z podglądu do bazy danych.
    Istniejące rekordy są pomijane (nie nadpisywane).
    """
    counters = {"units_created": 0, "units_skipped": 0,
                "depts_created": 0, "depts_skipped": 0}
    details: list[str] = []

    from services.ldap_service import normalize_dn

    # Mapa znormalizowany DN → opis (atrybut `description` OU). Pobieramy raz
    # pełną strukturę z AD, żeby przy imporcie/synchronizacji ustawić opisy
    # jednostek i komórek bez przekazywania ich z frontu.
    def _build_desc_map() -> dict:
        try:
            from models import LdapSettings
            from services.ldap_service import fetch_ou_structure
            cfg = session.exec(select(LdapSettings)).first()
            if not cfg or not cfg.base_dn:
                return {}
            raw = fetch_ou_structure(cfg, cfg.base_dn)
        except Exception:
            return {}
        m: dict[str, Optional[str]] = {}

        def _walk(node):
            if node.get("dn"):
                m[normalize_dn(node["dn"])] = node.get("description")
            for c in node.get("children", []):
                _walk(c)
        for u in raw:
            if u.get("dn"):
                m[normalize_dn(u["dn"])] = u.get("description")
            for d in u.get("departments", []):
                _walk(d)
        return m

    desc_by_dn = _build_desc_map()
    # Przeniesienie komórki (zmiana podległości wg AD) zmienia przełożonych
    # wniosków w toku w jej poddrzewie — stan sprzed importu do porządków.
    stage_snap = _stage_snapshot(session, _all_dept_ids(session))
    orphans_before = _higher_orphan_ids(session, stage_snap[0])
    moved_dept_ids: set[int] = set()

    def _import_children(unit_id: int, parent_dept_id: Optional[int],
                         children: list[LdapImportDept], depth: int) -> None:
        for child in children:
            indent = "  " * depth
            ndn = normalize_dn(child.dn) if child.dn else None

            # 1) Mapowanie ręczne do wskazanego istniejącego wydziału.
            mapped = None
            if child.map_to_dept_id is not None:
                mapped = _live_dept(session, child.map_to_dept_id)
                if not mapped:
                    details.append(f"{indent}⚠ Wydział \"{child.name}\" — wskazany do mapowania "
                                   f"wydział (id={child.map_to_dept_id}) nie istnieje, "
                                   f"dopasowuję po nazwie")

            # 2) Dopasowanie: NAJPIERW po ldap_dn (stały, unikalny klucz z AD —
            #    chroni przed dublowaniem i pozwala przenieść komórkę, gdy w AD
            #    zmieniła się podległość), potem po (jednostka, rodzic, nazwa).
            existing = mapped
            if not existing and ndn:
                existing = session.exec(
                    select(Department)
                    .where(Department.unit_id == unit_id)
                    .where(Department.ldap_dn == ndn)
                    .where(_NOT_ARCHIVED)
                ).first()
            if not existing:
                existing = session.exec(
                    select(Department)
                    .where(Department.unit_id == unit_id)
                    .where(Department.parent_dept_id == parent_dept_id)
                    .where(Department.name == child.name)
                    .where(_NOT_ARCHIVED)
                ).first()
            # 3) Po UNIKALNEJ nazwie w jednostce (dowolny rodzic) — pozwala
            #    PRZENIEŚĆ istniejącą „płaską" komórkę pod właściwego rodzica
            #    zamiast tworzyć duplikat. Działa tylko gdy nazwa jest jednoznaczna.
            if not existing:
                same = session.exec(
                    select(Department)
                    .where(Department.unit_id == unit_id)
                    .where(Department.name == child.name)
                    .where(_NOT_ARCHIVED)
                ).all()
                if len(same) == 1:
                    existing = same[0]

            if existing and existing.unit_id != unit_id:
                # Mapowanie na komórkę z INNEJ jednostki przeniosłoby ją między
                # jednostkami (łańcuch przełożonych i zakres kadr bez sensu) —
                # pomijamy ją razem z poddrzewem.
                other = session.get(Unit, existing.unit_id)
                details.append(f"{indent}⚠ Wydział „{child.name}” — pominięty: wskazana "
                               f"komórka „{existing.name}” należy do innej jednostki "
                               f"(„{other.name if other else existing.unit_id}”); "
                               f"przenoszenie komórek między jednostkami nie jest "
                               f"możliwe w imporcie (pominięto też jej podkomórki)")
                counters["depts_skipped"] += 1
                continue
            if existing:
                changed = []
                if ndn and not existing.ldap_dn:
                    existing.ldap_dn = ndn; changed.append("DN")
                # Aktualizuj podległość i nazwę wg AD (bez tworzenia duplikatu).
                if existing.parent_dept_id != parent_dept_id:
                    try:
                        _validate_no_cycle(session, existing.id, parent_dept_id)
                    except HTTPException:
                        details.append(f"{indent}⚠ Wydział „{child.name}” — pominięto "
                                       f"zmianę podległości: utworzyłaby cykl w "
                                       f"strukturze (komórka pod własną podkomórką)")
                    else:
                        existing.parent_dept_id = parent_dept_id; changed.append("podległość")
                        moved_dept_ids.add(existing.id)
                if existing.name != child.name:
                    existing.name = child.name; changed.append("nazwa")
                # Opis z AD — ustaw/odśwież (nie czyścimy, gdy w AD pusty).
                adesc = child.description or (desc_by_dn.get(ndn) if ndn else None)
                if adesc and existing.description != adesc:
                    existing.description = adesc; changed.append("opis")
                if changed:
                    session.add(existing); session.commit()
                dept_id = existing.id
                counters["depts_skipped"] += 1
                if mapped:
                    details.append(f"{indent}→ Wydział „{child.name}” — zmapowany na "
                                   f"istniejący „{existing.name}”")
                elif changed:
                    details.append(f"{indent}~ Wydział „{child.name}” — zaktualizowano: "
                                   + ", ".join(changed))
                else:
                    details.append(f"{indent}~ Wydział „{child.name}” — już istnieje, bez zmian")
            else:
                dept = Department(unit_id=unit_id, parent_dept_id=parent_dept_id,
                                  name=child.name, ldap_dn=ndn,
                                  description=(child.description or (desc_by_dn.get(ndn) if ndn else None)))
                session.add(dept); session.commit(); session.refresh(dept)
                dept_id = dept.id
                counters["depts_created"] += 1
                details.append(f"{indent}+ Wydział \"{child.name}\" — utworzony")
            if child.children:
                _import_children(unit_id, dept_id, child.children, depth + 1)

    for item in data.items:
        ndn = normalize_dn(item.unit_dn) if item.unit_dn else None

        # 1) Mapowanie ręczne do wskazanej istniejącej jednostki.
        unit = None
        if item.map_to_unit_id is not None:
            unit = session.get(Unit, item.map_to_unit_id)
            if not unit:
                details.append(f"⚠ Jednostka \"{item.unit_name}\" — wskazana do mapowania "
                               f"jednostka (id={item.map_to_unit_id}) nie istnieje, "
                               f"dopasowuję po nazwie")

        # 2) Domyślnie: dopasowanie po nazwie.
        unit = unit or session.exec(
            select(Unit).where(Unit.name == item.unit_name)
        ).first()

        if not unit:
            unit = Unit(name=item.unit_name, ldap_dn=ndn,
                        description=(item.description or (desc_by_dn.get(ndn) if ndn else None)))
            session.add(unit); session.commit(); session.refresh(unit)
            counters["units_created"] += 1
            details.append(f"Jednostka \"{item.unit_name}\" — utworzona")
        else:
            uchg = False
            if ndn and not unit.ldap_dn:
                unit.ldap_dn = ndn; uchg = True
            adesc = item.description or (desc_by_dn.get(ndn) if ndn else None)
            if adesc and unit.description != adesc:
                unit.description = adesc; uchg = True
            if uchg:
                session.add(unit); session.commit()
            counters["units_skipped"] += 1
            if item.map_to_unit_id is not None:
                details.append(f"Jednostka \"{item.unit_name}\" — zmapowana na "
                               f"istniejącą \"{unit.name}\"")
            else:
                details.append(f"Jednostka \"{item.unit_name}\" — już istnieje, pominięta")

        _import_children(unit.id, None, item.departments, 1)

    session.commit()
    if moved_dept_ids:
        from services.workflow import subtree_dept_ids
        moved_tree = subtree_dept_ids(session, moved_dept_ids)
        _resync_stage(session, stage_snap, "Import struktury z AD (zmiana podległości)",
                      dept_ids=moved_tree)
        for did in _report_higher_orphans(session, request, current_user, moved_tree,
                                          orphans_before, "import struktury z AD"):
            d = session.get(Department, did)
            details.append(f"⚠ Komórka „{d.name if d else did}” ma akceptację wyższego rzędu, "
                           f"ale po zmianie podległości nikt nie może jej wykonać — "
                           f"popraw strukturę (lista kontrolna)")
    units_created  = counters["units_created"]
    units_skipped  = counters["units_skipped"]
    depts_created  = counters["depts_created"]
    depts_skipped  = counters["depts_skipped"]
    return LdapImportResult(
        units_created=units_created,
        units_skipped=units_skipped,
        departments_created=depts_created,
        departments_skipped=depts_skipped,
        details=details,
    )


class DedupeResult(BaseModel):
    deleted: int
    kept_with_data: int
    clusters_found: int
    details: list[str]


@router.post("/departments/dedupe", response_model=DedupeResult)
def dedupe_departments(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Usuwa zduplikowane komórki powstałe przy ponownym imporcie struktury.

    Duplikaty grupujemy po `ldap_dn` (ten sam węzeł AD), a gdy brak DN — po
    (jednostka, podległość, nazwa). W każdej grupie zostaje jeden rekord
    (z danymi, inaczej najstarszy), a USUWANE są WYŁĄCZNIE kopie BEZ danych:
    bez przypisanych pracowników, bez wniosków i bez ustawionego kierownika.
    Kasujemy od liści w górę, żeby nie zderzyć się z kluczami obcymi.
    """
    from collections import defaultdict
    from models import AccessRequest

    depts = session.exec(select(Department).where(_NOT_ARCHIVED)).all()

    def _value(d: Department) -> int:
        v = 1 if d.manager_user_id else 0
        if session.exec(select(User).where(User.department_id == d.id)).first():
            v += 1
        if session.exec(select(AccessRequest).where(AccessRequest.department_id == d.id)).first():
            v += 1
        return v

    clusters: dict[tuple, list[Department]] = defaultdict(list)
    for d in depts:
        key = (("dn", d.unit_id, d.ldap_dn) if d.ldap_dn
               else ("nm", d.unit_id, d.parent_dept_id, (d.name or "").strip().lower()))
        clusters[key].append(d)

    dupe_ids: set[int] = set()
    clusters_found = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        clusters_found += 1
        reals = [m for m in members if _value(m) > 0]
        keeper = (sorted(reals, key=lambda x: x.id)[0] if reals
                  else sorted(members, key=lambda x: x.id)[0])
        for m in members:
            if m.id != keeper.id and _value(m) == 0:
                dupe_ids.add(m.id)

    deleted = 0
    details: list[str] = []
    remaining = set(dupe_ids)
    progress = True
    while progress and remaining:
        progress = False
        for did in list(remaining):
            # Najpierw usuń ewentualne (duplikatowe) dzieci — czekamy, aż liść.
            if session.exec(select(Department).where(Department.parent_dept_id == did)).first():
                continue
            d = session.get(Department, did)
            if not d:
                remaining.discard(did); continue
            for dep in session.exec(
                select(DepartmentDeputy).where(DepartmentDeputy.department_id == did)).all():
                session.delete(dep)
            details.append(f"usunięto duplikat „{d.name}” (id={did})")
            session.delete(d)
            remaining.discard(did); deleted += 1; progress = True
    session.commit()

    kept_with_data = clusters_found  # ile grup miało zachowany rekord
    for did in remaining:
        d = session.get(Department, did)
        if d:
            details.append(f"pominięto „{d.name}” (id={did}) — zablokowany przez podrzędne")
    return DedupeResult(deleted=deleted, kept_with_data=kept_with_data,
                        clusters_found=clusters_found, details=details)


# ===========================================================================
# Zastępcy kierownika (DepartmentDeputy)
# ===========================================================================
# Dodatkowe osoby (obok głównego manager_user_id) z pełnymi uprawnieniami
# kierownika komórki: wybierają uprawnienia, akceptują wnioski, widzą swoich
# pracowników w „Moim zespole" / „Mojej strukturze".

class DeputyIn(BaseModel):
    user_id: int
    role_label: Optional[str] = None


class DeputyRead(BaseModel):
    id: int
    department_id: int
    user_id: int
    user_name: Optional[str]
    user_username: Optional[str]
    role_label: Optional[str]


def _serialize_deputy(session: Session, d: DepartmentDeputy) -> dict:
    u = session.get(User, d.user_id)
    return {
        "id": d.id,
        "department_id": d.department_id,
        "user_id": d.user_id,
        "user_name": (u.full_name or u.username) if u else None,
        "user_username": u.username if u else None,
        "role_label": d.role_label,
    }


@router.get("/departments/{department_id}/deputies", response_model=list[DeputyRead])
def list_deputies(
    department_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    # Zastępcy komórki to konfiguracja struktury organizacyjnej — dostęp
    # wyłącznie administracyjny (jak tworzenie/usuwanie zastępcy). Wcześniej
    # ten GET był otwarty dla każdego zalogowanego (IDOR: ujawnienie struktury).
    if not _live_dept(session, department_id):
        raise HTTPException(404, "Wydział nie istnieje")
    rows = session.exec(
        select(DepartmentDeputy).where(DepartmentDeputy.department_id == department_id)
        .order_by(DepartmentDeputy.id)
    ).all()
    return [_serialize_deputy(session, d) for d in rows]


@router.post("/departments/{department_id}/deputies",
             response_model=DeputyRead, status_code=status.HTTP_201_CREATED)
def add_deputy(
    department_id: int,
    data: DeputyIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    from services.structure import clean_model_fields, text_spec
    clean_model_fields(data, {"role_label": text_spec("funkcja zastępcy")})
    _guard_self_post(current_user, data.user_id)
    _guard_superadmin_post(session, data.user_id)
    dept = _live_dept(session, department_id)
    if not dept:
        raise HTTPException(404, "Wydział nie istnieje")
    user = session.get(User, data.user_id)
    if not user:
        raise HTTPException(400, "Wskazany użytkownik nie istnieje")
    if not user.is_active:
        raise HTTPException(400, "Użytkownik jest nieaktywny")
    # Nie może być główny kierownik (to bez sensu)
    if dept.manager_user_id == data.user_id:
        raise HTTPException(400, "Ten użytkownik jest już głównym kierownikiem tej komórki")
    # Duplikat
    existing = session.exec(
        select(DepartmentDeputy)
        .where(DepartmentDeputy.department_id == department_id)
        .where(DepartmentDeputy.user_id == data.user_id)
    ).first()
    if existing:
        raise HTTPException(400, "Ta osoba jest już zastępcą w tej komórce")

    from services.workflow import subtree_dept_ids
    snap = _stage_snapshot(session, subtree_dept_ids(session, {department_id}))
    row = DepartmentDeputy(
        department_id=department_id,
        user_id=data.user_id,
        role_label=(data.role_label or "").strip() or None,
    )
    session.add(row); session.commit(); session.refresh(row)
    _resync_stage(session, snap, f"Nowy zastępca kierownika komórki „{dept.name}”")
    session.refresh(row)
    # Zastępca też działa w obiegu jak kierownik → potrzebuje roli „manager".
    from services.org_sync import grant_manager_role
    if grant_manager_role(session, data.user_id):
        session.commit()
    _audit_post_change(session, request, current_user, action="department.deputy_added",
                       target_type="department", target_id=dept.id, name=dept.name,
                       old_user_id=None, new_user_id=data.user_id,
                       extra={"role_label": row.role_label})
    return _serialize_deputy(session, row)


@router.patch("/departments/deputies/{deputy_id}", response_model=DeputyRead)
def update_deputy(
    deputy_id: int,
    data: DeputyIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    from services.structure import clean_model_fields, db_int_ok, text_spec
    row = session.get(DepartmentDeputy, deputy_id) if db_int_ok(deputy_id) else None
    if not row:
        raise HTTPException(404, "Zastępca nie istnieje")
    clean_model_fields(data, {"role_label": text_spec("funkcja zastępcy")})
    # Zmieniamy tylko label — user_id/department_id są niezmienne (usuń i dodaj ponownie).
    row.role_label = (data.role_label or "").strip() or None
    session.add(row); session.commit(); session.refresh(row)
    return _serialize_deputy(session, row)


@router.delete("/departments/deputies/{deputy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deputy(
    deputy_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    row = session.get(DepartmentDeputy, deputy_id)
    if not row:
        raise HTTPException(404, "Zastępca nie istnieje")
    ex_user_id = row.user_id
    dept_id = row.department_id
    dept = session.get(Department, dept_id)
    from services.workflow import subtree_dept_ids
    snap = _stage_snapshot(session, subtree_dept_ids(session, {dept_id}))
    session.delete(row); session.commit()
    _resync_stage(session, snap, "Usunięcie zastępcy kierownika komórki"
                  + (f" „{dept.name}”" if dept else ""))
    _audit_post_change(session, request, current_user, action="department.deputy_removed",
                       target_type="department", target_id=dept_id,
                       name=dept.name if dept else f"id={dept_id}",
                       old_user_id=ex_user_id, new_user_id=None)
    # Jeśli nie kieruje już niczym i nie jest gdzie indziej zastępcą — zdejmij rolę.
    from services.org_sync import revoke_manager_role_if_unused
    if revoke_manager_role_if_unused(session, ex_user_id):
        session.commit()
