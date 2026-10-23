"""
Router: Zarządzanie użytkownikami.

Superadmin (konto awaryjne): zarządza wszystkimi kontami i nadaje/odbiera
       dowolną rolę (bez łączenia roli superadmin z rolami operacyjnymi).
Admin: może zakładać konta i zarządzać użytkownikami z wyjątkiem kont z rolą
       admin lub superadmin (edycja, reset hasła, odblokowanie, dezaktywacja,
       usunięcie — tylko superadmin); nadaje wyłącznie role operacyjne
       (kierownik, IT, podgląd) — ról admin/superadmin nie nadaje ani nie odbiera.

Roli „hr” nie ma (v3.9): pracownikiem kadr jest każdy członek komórki kadrowej
(Department.is_hr). Wejście konta do takiej komórki (formularz, import z AD)
jest zdarzeniem bezpieczeństwa `user.hr_capability_granted` (medium), a reset
hasła członka komórki kadrowej — `user.password_reset` (high).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from models import (
    User, AuthType, Unit, Department, SecuritySeverity,
    parse_roles, roles_to_json, primary_role, VALID_ROLES, has_role,
)
from services.auth_service import (
    clean_text_field, get_current_user, hash_password, invalidate_tokens_now,
    validate_password_strength,
)
from services.permissions import (
    require_admin, require_manager, managed_dept_ids,
    users_with_role, manager_scope_ids, SUPERADMIN_FORBIDDEN_ROLES,
)

router = APIRouter()
_log = logging.getLogger("szup.users")


# Role, których nadanie poszerza dostęp do wniosków i danych pracowników —
# każde nadanie trafia też do zdarzeń bezpieczeństwa (konto „marionetka”).
OPERATIONAL_ROLES = {"manager", "it_staff"}
ADMIN_ROLES = {"admin", "superadmin"}

HR_ROLE_REMOVED_MSG = (
    "Roli „hr” nie można już nadawać — pracownikiem kadr jest każdy członek "
    "komórki kadrowej. Przypisz osobę do takiej komórki (Struktura → oznacz "
    "komórkę jako kadrową)"
)


def _validate_roles(roles: list[str]) -> None:
    """Walidacja listy ról przy zakładaniu / edycji konta (400 przy błędzie):
      - „hr” — rola zniesiona (zdolność kadrowa = komórka kadrowa),
      - nieznane role,
      - superadmin razem z rolą operacyjną (kierownik, IT) — superadmin to konto
        awaryjne do konfiguracji, nie do pracy w obiegu wniosków."""
    if "hr" in roles:
        raise HTTPException(400, HR_ROLE_REMOVED_MSG)
    invalid = [r for r in roles if r not in VALID_ROLES]
    if invalid:
        raise HTTPException(400, f"Nieznane role: {invalid}")
    if "superadmin" in roles:
        mixed = sorted(set(roles) & SUPERADMIN_FORBIDDEN_ROLES)
        if mixed:
            raise HTTPException(
                400,
                "Konto superadmina służy wyłącznie do konfiguracji — nie można go "
                f"łączyć z rolami operacyjnymi ({', '.join(mixed)}). Do pracy "
                "w obiegu wniosków użyj osobnego konta",
            )


def _audit_user(session: Session, request: Optional[Request], actor: User, *,
                action: str, target: User, details: Optional[dict] = None) -> None:
    """Wpis w audit logu o zmianie konta. W `details` nigdy nie ma haseł."""
    from services.audit import record_event, request_meta
    meta = request_meta(request)
    record_event(session, action=action, user_id=actor.id, username=actor.username,
                 target_type="user", target_id=target.id, ip=meta["ip"],
                 user_agent=meta["user_agent"],
                 details={"username": target.username, **(details or {})})


def _roles_granted_event(session: Session, request: Optional[Request], actor: User,
                         target: User, granted: set[str]) -> None:
    """Nadanie roli operacyjnej lub administracyjnej → zdarzenie bezpieczeństwa
    (admin → high, kierownik / IT → medium)."""
    sensitive = granted & (OPERATIONAL_ROLES | ADMIN_ROLES)
    if not sensitive:
        return
    from services.audit import request_meta
    from services.security_events import emit as emit_security_event
    severity = SecuritySeverity.high if sensitive & ADMIN_ROLES else SecuritySeverity.medium
    emit_security_event(
        session, event_type="user.roles_granted", source="users", severity=severity,
        summary=(f"Nadano role {', '.join(sorted(sensitive))} kontu {target.username} "
                 f"przez {actor.username}"),
        details={"target_user_id": target.id, "target_username": target.username,
                 "granted": sorted(sensitive)},
        user_id=actor.id, ip=request_meta(request)["ip"],
    )


def _hr_capability_event(session: Session, request: Optional[Request], actor: User,
                         target: User, old_dept_id: Optional[int], *, via: str) -> None:
    """Konto weszło do komórki kadrowej (Department.is_hr) → zdarzenie medium.

    Zdolność kadrowa (dane pracowników i wnioski we wszystkich jednostkach)
    nie jest rolą, więc nie obejmuje jej `_roles_granted_event` — bez tego
    admin mógłby po cichu założyć „marionetkę” w komórce kadrowej. Przejście
    między dwiema komórkami kadrowymi niczego nie poszerza (bez zdarzenia).
    `via` — skąd zmiana: "create", "update", "ldap_import"."""
    if not target.department_id or target.department_id == old_dept_id:
        return
    new_dept = session.get(Department, target.department_id)
    if not new_dept or not new_dept.is_hr:
        return
    old_dept = session.get(Department, old_dept_id) if old_dept_id else None
    if old_dept is not None and old_dept.is_hr:
        return
    from services.audit import request_meta
    from services.security_events import emit as emit_security_event
    emit_security_event(
        session, event_type="user.hr_capability_granted", source="users",
        severity=SecuritySeverity.medium,
        summary=(f"Konto {target.username} uzyskało zdolność kadrową — przypisane do "
                 f"komórki kadrowej „{new_dept.name}” przez {actor.username}"),
        details={"target_user_id": target.id, "target_username": target.username,
                 "department_id": new_dept.id, "department_name": new_dept.name,
                 "old_department_id": old_dept_id, "via": via},
        user_id=actor.id, ip=request_meta(request)["ip"],
    )


def _clean_identity(data, *, username: bool = False) -> None:
    """Limity pól konta (N2): login, imię i nazwisko, e-mail — najwyżej 200
    znaków, bez znaków sterujących. Modyfikuje `data` w miejscu (przycięte
    spacje); błąd = 400."""
    if username:
        data.username = clean_text_field(data.username, "login", required=True)
    if data.full_name is not None:
        data.full_name = clean_text_field(data.full_name, "imię i nazwisko")
    if data.email is not None:
        data.email = clean_text_field(data.email, "e-mail")


def _guard_admin_account(current_user: User, target: User) -> None:
    """Kontem z rolą admin lub superadmin zarządza wyłącznie superadmin.

    Dotyczy edycji (w tym ról i aktywności), resetu hasła, odblokowania
    i usunięcia. Inaczej administrator mógłby zresetować hasło innego admina,
    zalogować się jako on i np. zamknąć zdarzenie bezpieczeństwa o własnym
    działaniu. Własne konto admin edytuje nadal w granicach `update_user`."""
    if has_role(current_user, "superadmin"):
        return
    if has_role(target, "superadmin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może zarządzać kontem superadmina",
        )
    if has_role(target, "admin") and target.id != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Kontem innego administratora zarządza wyłącznie superadmin",
        )


def _guard_admin_role_change(current_user: User, roles: list[str],
                             current_roles: Optional[list[str]] = None) -> None:
    """Role administracyjne (admin, superadmin) nadaje i odbiera wyłącznie superadmin.

    Inaczej administrator mógłby założyć konto-„marionetkę” z rolą admin
    (albo nadać ją istniejącemu kontu) i działać nim z pominięciem rozdziału
    obowiązków. Role operacyjne admin nadaje nadal — każde nadanie trafia do
    audytu i zdarzeń bezpieczeństwa (`_roles_granted_event`).

    `current_roles` — obecne role konta przy edycji (None przy zakładaniu).
    """
    if has_role(current_user, "superadmin"):
        return
    requested = set(roles) & ADMIN_ROLES
    existing = set(current_roles or []) & ADMIN_ROLES
    if "superadmin" in requested - existing:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Administrator nie może nadawać roli superadmin",
        )
    if requested != existing:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Role administracyjne (admin, superadmin) nadaje i odbiera wyłącznie superadmin",
        )


def _admin_account_off_limits(current_user: User, target: User) -> bool:
    """Czy `target` jest kontem, którym `current_user` nie może zarządzać
    (wariant `_guard_admin_account` bez wyjątku — np. do pomijania w imporcie)."""
    try:
        _guard_admin_account(current_user, target)
    except HTTPException:
        return True
    return False


def _stage_snapshot_before_deactivation(session: Session, user_id: int) -> dict:
    """Migawka „kto odpowiada za krok” wniosków w komórkach, na które wpływają
    stanowiska konta (`manager_stage_snapshot`). Robiona PRZED ustawieniem
    `is_active=False` i przekazywana do `release_manager_posts(before=...)` —
    po dezaktywacji stan „przed” byłby już równy stanowi „po”, więc nowy
    odpowiedzialny nie dostałby powiadomienia."""
    from services.org_sync import _posts_subtree
    from services.workflow import manager_stage_snapshot
    return manager_stage_snapshot(session, _posts_subtree(session, user_id))


class UserCreate(BaseModel):
    username: str
    password: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    auth_type: AuthType = AuthType.local
    roles: list[str] = ["viewer"]
    department_id: Optional[int] = None


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
    # Dawne jednostki kadr (UserUnit) — tylko do odczytu, niczego nie ograniczają.
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


class PasswordResetRequest(BaseModel):
    new_password: str


def _user_unit_ids(session, user_id: int) -> list[int]:
    from models import UserUnit
    if session is None:
        return []
    rows = session.exec(select(UserUnit.unit_id).where(UserUnit.user_id == user_id)).all()
    return sorted(int(x) for x in rows)


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
            # Nadanie odebrane systemowo (np. usunięcie posiadanej grupy przez
            # superadmina) — wskazuje wniosek odebrania; już nie jest posiadane.
            if getattr(it, "revoked_by_request_id", None):
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
    """Uprawnienia zalogowanego użytkownika (NIS2/KSC — transparentność).
    v3.1: + `manager` — kto składa wnioski o uprawnienia dla tej osoby."""
    out = _effective_permissions(session, current_user.id)
    out["manager"] = _my_manager(session, current_user)
    return out


def _my_manager(session: Session, user: User) -> Optional[dict]:
    """Efektywny kierownik użytkownika: kierownik jego komórki (dla samodzielnych
    stanowisk / komórek bez kierownika — najbliższy wyżej). Gdy użytkownik SAM
    kieruje tą komórką — kierownik komórki nadrzędnej. None, gdy brak."""
    from services.permissions import effective_manager_dept
    if not user.department_id:
        return None
    dept = session.get(Department, user.department_id)
    resp = effective_manager_dept(session, dept) if dept else None
    if resp and resp.manager_user_id == user.id:
        parent = session.get(Department, resp.parent_dept_id) if resp.parent_dept_id else None
        resp = effective_manager_dept(session, parent) if parent else None
    if not resp or not resp.manager_user_id:
        return None
    m = session.get(User, resp.manager_user_id)
    if not m:
        return None
    return {"name": m.full_name or m.username, "department": resp.name, "email": m.email}


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
        # Zakres kierownika i przełożonego (poddrzewo, cała jednostka dyrektora),
        # spójny z zakresem wniosków. Podgląd uprawnień nie oznacza prawa do
        # działania w obiegu — przełożony działa tylko po przejęciu wniosku albo
        # w komórce bez kierownika (services.workflow.can_act).
        scope = manager_scope_ids(session, current_user)
        if target.department_id not in scope and not _can_act_on_worker_request(
                session, current_user, user_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                "Brak dostępu do uprawnień tego pracownika")
    return _effective_permissions(session, user_id)


def _can_act_on_worker_request(session: Session, user: User, worker_id: int) -> bool:
    """Czy `user` może działać na bieżącym kroku któregoś AKTYWNEGO wniosku
    pracownika. Np. AD przeniosło pracownika do innej komórki, a wniosek jest
    wciąż w starej — kierownik starej komórki musi widzieć obecne uprawnienia,
    żeby dokończyć wybór (inaczej 403 i pusta lista)."""
    from models import AccessRequest, WorkflowInstance, WorkflowInstanceStatus
    # Import w funkcji — services.workflow importuje sporo modułów (cykl importów).
    from services.workflow import active_node_of, can_act
    rows = session.exec(
        select(AccessRequest, WorkflowInstance)
        .join(WorkflowInstance, WorkflowInstance.request_id == AccessRequest.id)
        .where(AccessRequest.worker_user_id == worker_id)
        .where(WorkflowInstance.status == WorkflowInstanceStatus.active)
    ).all()
    for req, inst in rows:
        node = active_node_of(session, inst)
        if not node:
            continue
        dept = session.get(Department, req.department_id) if req.department_id else None
        try:
            allowed, _reason = can_act(node, req, dept, user, session)
        except Exception:
            allowed = False
        if allowed:
            return True
    return False


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
    pracy: wybór pracownika z listy). Dostęp operacyjny: kadry (komórka
    kadrowa) i kierownik, superadmin — break-glass. Administrator (Wariant A)
    nie działa operacyjnie.

    IDOR/RODO: sam fakt roli nie wystarcza — zakres musi obejmować tę komórkę:
      - kierownik: tylko wydziały, którymi kieruje (bezpośrednio/zastępczo/2-st.),
      - kadry: wszystkie jednostki (komórka kadrowa obsługuje całą organizację).
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
            if department_id in manager_scope_ids(session, current_user):
                allowed = True
        # Ścieżka kadr (komórka kadrowa) — wszystkie jednostki.
        if not allowed and hr_cap:
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
    # zarządza (bezpieczeństwo); kadry i superadmin — całe poddrzewo.
    if not has_role(current_user, "superadmin") and has_role(current_user, "manager") \
            and not hr_cap:
        managed = manager_scope_ids(session, current_user)
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

    # Kierownik — tylko swój zakres komórek; kadry i superadmin — wszyscy.
    allowed_dept_ids = None     # None = bez ograniczenia
    if not has_role(current_user, "superadmin"):
        if has_role(current_user, "manager") and not hr_cap:
            allowed_dept_ids = manager_scope_ids(session, current_user)

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
    składać wnioski — ten sam zakres „przełożonego” co wyszukiwarka
    (users/search), podgląd uprawnień i obieg wniosków:
      - komórki, którymi kieruje bezpośrednio (lub jest zastępcą), z
        samodzielnymi stanowiskami i komórkami bez kierownika pod nim,
      - całe poddrzewo podległych komórek,
      - wszystkie komórki jednostek, których jest kierownikiem.
    """
    _direct_ids, escalated_ids = managed_dept_ids(session, current_user)
    # manager_scope_ids obejmuje już komórki jednostek, którymi user kieruje.
    all_ids = list(manager_scope_ids(session, current_user))
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

    # Wniosek przełożonego dla pracownika komórki, która ma WŁASNEGO aktywnego
    # kierownika, jest przy składaniu automatycznie przejmowany (zatrzymany
    # u przełożonego) — front uprzedza o tym przy wyborze pracownika.
    from services.permissions import has_active_manager, is_department_manager_or_deputy
    take_over_cache: dict[int, bool] = {}

    def _will_take_over(d: Optional[Department]) -> bool:
        if d is None:
            return False
        if d.id not in take_over_cache:
            take_over_cache[d.id] = bool(
                not is_department_manager_or_deputy(session, current_user, d)
                and has_active_manager(session, d))
        return take_over_cache[d.id]

    result = []
    for u in workers:
        d = depts_map.get(u.department_id)
        un = units_map.get(d.unit_id) if d else None
        result.append({
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "title": u.title or "",
            "department_id": u.department_id,
            "department_name": d.name if d else None,
            "department_description": d.description if d else None,
            "unit_id": d.unit_id if d else None,
            "unit_name": un.name if un else None,
            "is_escalated": u.department_id in escalated_ids,
            # 2-stopniowy obieg? Front wie wtedy, że oświadczenie podpisze
            # dopiero kierownik II stopnia, więc nie pokazuje go przy tworzeniu.
            "requires_higher_approval": bool(d.requires_higher_approval) if d else False,
            "is_self": False,
            "will_take_over": _will_take_over(d),
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
        "title": me.title or "",
        "department_id": me.department_id,
        "department_name": md.name if md else None,
        "department_description": md.description if md else None,
        "unit_id": md.unit_id if md else None,
        "unit_name": mun.name if mun else None,
        "is_escalated": False,
        "requires_higher_approval": bool(md.requires_higher_approval) if md else False,
        "is_self": True,
        "will_take_over": False,
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
    wraz z efektywnymi uprawnieniami (`_effective_permissions` — jak zakładka
    „Pracownicy”).

    Admin/superadmin widzi pełną strukturę (wszystkie jednostki i wydziały).
    """
    from sqlmodel import col as _col
    from services.permissions import is_admin

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

    # --- 5. Efektywne uprawnienia per pracownik ---
    # Ta sama funkcja co „Pracownicy” i „Moje uprawnienia”: stan odtwarzany
    # chronologicznie (odebrane i odmówione pozycje NIE są posiadane).
    perms_by_user: dict[int, list[dict]] = {
        w.id: _effective_permissions(session, w.id)["permissions"] for w in workers
    }

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
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    _validate_roles(data.roles)
    _guard_admin_role_change(current_user, data.roles)
    _clean_identity(data, username=True)
    from services.ldap_service import normalize_login, find_user_by_login
    if data.auth_type == AuthType.ldap:
        # Konto AD zapisujemy pod loginem znormalizowanym — tak samo jak przy
        # logowaniu AD/SSO i imporcie (inaczej powstałby duplikat).
        data.username = normalize_login(data.username)
        if not data.username:
            raise HTTPException(400, "Nieprawidłowy login konta AD")
    if find_user_by_login(session, data.username):
        raise HTTPException(400, "Użytkownik o tej nazwie już istnieje")
    if data.auth_type == AuthType.local and not data.password:
        raise HTTPException(400, "Hasło jest wymagane dla konta lokalnego")
    if data.password:
        validate_password_strength(data.password)

    if data.department_id is not None:
        # Komórka zlikwidowana (archiwum) albo nieaktywna nie przyjmuje kont (F8).
        from services.structure import live_department
        live_department(session, data.department_id)

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
    # Rola → struktura: kierownik przypisany do komórki bez kierownika
    # obejmuje ją automatycznie (bez podmieniania obsadzonego stanowiska).
    from services.org_sync import sync_after_user_change
    changed, warning = sync_after_user_change(session, user)
    if changed:
        session.commit(); session.refresh(user)
    _audit_user(session, request, current_user, action="user.created", target=user, details={
        "auth_type": user.auth_type.value if hasattr(user.auth_type, "value") else user.auth_type,
        "roles": parse_roles(user.roles),
        "department_id": user.department_id,
    })
    _roles_granted_event(session, request, current_user, user, set(parse_roles(user.roles)))
    _hr_capability_event(session, request, current_user, user, None, via="create")
    return _user_read(user, session=session, warning=warning)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    _guard_admin_account(current_user, user)
    _clean_identity(data)
    if data.roles is not None:
        _validate_roles(data.roles)
        _guard_admin_role_change(current_user, data.roles, parse_roles(user.roles))
        # Admin (nie superadmin) nie zmienia SWOICH ról — ani nie nadaje sobie
        # ról operacyjnych (kierownik, IT), ani nie odbiera. Robi to superadmin.
        if (user.id == current_user.id and not has_role(current_user, "superadmin")
                and set(data.roles) != set(parse_roles(user.roles))):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                "Administrator nie może zmieniać własnych ról — poproś o to superadmina")
        # Ochrona własnego konta — nie można odebrać sobie roli dającej dostęp
        if user.id == current_user.id:
            if has_role(current_user, "superadmin") and "superadmin" not in data.roles:
                raise HTTPException(400, "Nie możesz odebrać sobie roli superadmin")
            if has_role(current_user, "admin") and "admin" not in data.roles and "superadmin" not in data.roles:
                raise HTTPException(400, "Nie możesz odebrać sobie roli admin")
    if data.is_active is not None:
        if user.id == current_user.id and not data.is_active:
            raise HTTPException(400, "Nie możesz dezaktywować własnego konta")
    if user.id == current_user.id and not has_role(current_user, "superadmin"):
        # Zmiana własnej komórki poszerza własny zakres (np. kierownik obejmuje
        # komórkę bez kierownika, komórka kadrowa daje funkcje kadr) — tylko superadmin.
        if ("department_id" in data.model_fields_set
                and (data.department_id or None) != user.department_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                "Administrator nie może zmieniać własnej komórki — poproś o to superadmina")
    deactivated = data.is_active is False and user.is_active
    # Stan „kto odpowiada za krok” wniosków w toku — PRZED zmianą is_active
    # (po niej nieaktywny kierownik już się nie liczy i nowy odpowiedzialny
    # nie dostałby powiadomienia).
    stage_before = _stage_snapshot_before_deactivation(session, user.id) if deactivated else None
    before = {
        "roles": sorted(parse_roles(user.roles)),
        "department_id": user.department_id,
        "is_active": user.is_active,
    }

    if data.full_name is not None:  user.full_name = data.full_name
    if data.email is not None:      user.email = data.email
    if data.is_active is not None:  user.is_active = data.is_active
    if data.roles is not None:      user.roles = roles_to_json(data.roles)

    # department_id: obecność pola w żądaniu = intencja zmiany (także na null,
    # by odpiąć od komórki). Rozróżniamy „nie podano" od „podano null".
    if "department_id" in data.model_fields_set:
        if data.department_id:
            if data.department_id != user.department_id:
                from services.structure import live_department
                live_department(session, data.department_id)
            user.department_id = data.department_id
        else:
            user.department_id = None

    session.add(user); session.commit(); session.refresh(user)

    # Synchronizacja ze strukturą po zmianie ról / komórki:
    #  - nadanie roli „manager" + komórka bez kierownika → obejmuje ją,
    #  - odebranie roli „manager" → zwolnij stanowiska, którymi kierował.
    warning = None
    if deactivated:
        # Dezaktywacja zwalnia stanowiska (kierownik / zastępca / dyrektor
        # jednostki) — inaczej wnioski czekałyby na osobę, która się nie zaloguje.
        from services.org_sync import release_manager_posts
        if release_manager_posts(session, user.id, before=stage_before):
            session.commit(); session.refresh(user)
    elif data.roles is not None or "department_id" in data.model_fields_set:
        from services.org_sync import (
            after_department_change, release_manager_posts, sync_after_user_change,
        )
        changed = False
        if user.department_id != before["department_id"]:
            # Przeniesienie do innej komórki zwalnia stanowiska w dawnej (kierownik
            # nie kieruje dalej starą komórką). Rolę ustala admin — bez jej
            # automatycznego odbierania.
            moved = after_department_change(session, user, before["department_id"],
                                            drop_unused_role=False)
            changed = bool(moved["released_dept_ids"] or moved["adopted"])
            warning = moved["warning"]
        if "manager" in parse_roles(user.roles):
            adopted, sync_warning = sync_after_user_change(session, user)
            changed = changed or adopted
            warning = warning or sync_warning
        else:
            changed = release_manager_posts(session, user.id) or changed
        if changed:
            session.commit(); session.refresh(user)

    after = {
        "roles": sorted(parse_roles(user.roles)),
        "department_id": user.department_id,
        "is_active": user.is_active,
    }
    diff = {k: {"old": before[k], "new": after[k]} for k in before if before[k] != after[k]}
    if diff:
        _audit_user(session, request, current_user, action="user.updated",
                    target=user, details={"changes": diff})
        _roles_granted_event(session, request, current_user, user,
                             set(after["roles"]) - set(before["roles"]))
        _hr_capability_event(session, request, current_user, user,
                             before["department_id"], via="update")
    return _user_read(user, session=session, warning=warning)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: PasswordResetRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "Użytkownik nie istnieje")
    _guard_admin_account(current_user, user)
    if user.auth_type != AuthType.local:
        raise HTTPException(400, "Nie można zresetować hasła konta LDAP")

    validate_password_strength(data.new_password)
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.utcnow()
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    # Wszystkie dotychczasowe sesje konta tracą ważność.
    invalidate_tokens_now(user)
    session.add(user); session.commit()
    _audit_user(session, request, current_user, action="user.password_reset", target=user)
    # Kto zna nowe hasło, może działać jako to konto — przy kontach z rolą
    # operacyjną lub administracyjną oraz członkach komórki kadrowej (zdolność
    # kadrowa) to zdarzenie wysokie (zamyka superadmin).
    from services.permissions import user_is_hr
    sensitive = set(parse_roles(user.roles)) & (OPERATIONAL_ROLES | ADMIN_ROLES)
    if user_is_hr(session, user):
        sensitive.add("hr")
    if sensitive:
        from services.audit import request_meta
        from services.security_events import emit as emit_security_event
        emit_security_event(
            session, event_type="user.password_reset", source="users",
            severity=SecuritySeverity.high,
            summary=(f"Zresetowano hasło konta {user.username} "
                     f"({', '.join(sorted(sensitive))}) przez {current_user.username}"),
            details={"target_user_id": user.id, "target_username": user.username,
                     "roles": sorted(sensitive)},
            user_id=current_user.id, ip=request_meta(request)["ip"],
        )
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
    _guard_admin_account(current_user, user)
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
    _guard_admin_account(current_user, user)
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
    # Konta wyłączone w SZUP, a aktywne w AD — import ich NIE reaktywuje
    # (dezaktywacja w SZUP bywa celowa, np. podejrzenie przejęcia konta).
    reactivation_skipped: int = 0


def _build_dn_to_dept_map(session: Session) -> tuple[dict[str, int], set[str]]:
    """Mapa znormalizowany DN OU → Department.id (tylko komórki niezarchiwizowane)
    oraz zbiór DN przypisanych KILKU komórkom naraz.

    DN niejednoznacznego nie rozstrzygamy (dawniej wygrywała komórka o wyższym
    id — dopisanie DN do nowej komórki, np. kadrowej, przenosiło importem całą
    OU). Osobom z takiej OU import nie zmienia komórki."""
    from services.ldap_service import normalize_dn
    out: dict[str, int] = {}
    ambiguous: set[str] = set()
    for d in session.exec(select(Department).order_by(Department.id)).all():
        if not d.ldap_dn or getattr(d, "archived_at", None) is not None:
            continue
        key = normalize_dn(d.ldap_dn)
        if key in out and out[key] != d.id:
            ambiguous.add(key)
        out.setdefault(key, d.id)
    for key in ambiguous:
        out.pop(key, None)
    return out, ambiguous


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

    dept_by_dn, ambiguous_dn = _build_dn_to_dept_map(session)
    unit_by_dn = _build_dn_to_unit_map(session)
    _require_structure(dept_by_dn or ambiguous_dn, unit_by_dn)
    dept_names = {d.id: d.name for d in session.exec(select(Department)).all()}
    unit_names = {u.id: u.name for u in session.exec(select(Unit)).all()}
    from services.ldap_service import normalize_login
    # Dopasowanie BEZ względu na wielkość liter — tak jak przy imporcie.
    existing: dict[str, User] = {}
    for eu in session.exec(select(User).order_by(User.id)).all():
        existing.setdefault((eu.username or "").lower(), eu)

    from services.ldap_service import parent_dn as _parent_of

    def _resolve_dept_unit(start_dn: str) -> tuple[Optional[int], Optional[int]]:
        """Idzie w górę po parent-DN dopóki nie trafi na dopasowany Department/Unit.
        OU przypisana kilku komórkom: bez komórki (tylko jednostka)."""
        current = normalize_dn(start_dn)
        while current:
            if current in ambiguous_dn:
                up = current
                while up:
                    if up in unit_by_dn:
                        return None, unit_by_dn[up]
                    up = normalize_dn(_parent_of(up))
                return None, None
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
        existing_user = existing.get(normalize_login(u["username"]))
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
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """
    Importuje wskazanych użytkowników (po sAMAccountName) z AD do bazy.
    - Nowe konta  → auth_type=ldap, rola ['viewer'], department_id po parent-OU.
    - LDAP konta  → aktualizacja full_name, email, department_id, ldap_dn, title.
    - Konto wyłączone w AD → istniejące konto domenowe jest dezaktywowane,
      a jego stanowiska w strukturze zwolnione; nowego nie tworzymy.
    - Konto wyłączone w SZUP, a aktywne w AD → import go NIE reaktywuje
      (licznik `reactivation_skipped`); reaktywacja tylko ręcznie.
    - Konta z rolą admin / superadmin aktualizuje wyłącznie superadmin.
    - Konta lokalne o tym samym loginie → pomijane (konflikt).
    - Login nieznaleziony w AD → pomijany. Świadomie NIE dezaktywujemy takiego
      konta: pusty wynik wyszukiwania bywa skutkiem złego search_base lub
      uprawnień konta usługowego, a nie usunięcia osoby z AD.
    """
    from models import LdapSettings
    from services.ldap_service import (
        fetch_ldap_users, normalize_dn, normalize_login, find_user_by_login, is_valid_login,
    )
    from services.org_sync import after_department_change, release_manager_posts

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

    # Loginy normalizujemy tak samo jak przy logowaniu AD/SSO (małe litery,
    # bez realmu) — jedno konto AD = jedno konto w aplikacji.
    wanted = {normalize_login(n) for n in data.usernames}
    for u in users_raw:
        u["username"] = normalize_login(u["username"])
    dept_by_dn, ambiguous_dn = _build_dn_to_dept_map(session)
    unit_by_dn = _build_dn_to_unit_map(session)
    _require_structure(dept_by_dn or ambiguous_dn, unit_by_dn)

    from services.ldap_service import parent_dn as _parent_of

    def _resolve_dept_unit(start_dn: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Najbliższa dopasowana komórka (+ obejmująca jednostka) w górę po DN.
        Trzeci element: DN OU przypisanej kilku komórkom (wtedy bez komórki)."""
        current = normalize_dn(start_dn)
        while current:
            if current in ambiguous_dn:
                up = current
                while up:
                    if up in unit_by_dn:
                        return None, unit_by_dn[up], current
                    up = normalize_dn(_parent_of(up))
                return None, None, current
            if current in dept_by_dn:
                d_id = dept_by_dn[current]
                u_id = None
                up = current
                while up:
                    if up in unit_by_dn:
                        u_id = unit_by_dn[up]; break
                    up = normalize_dn(_parent_of(up))
                return d_id, u_id, None
            if current in unit_by_dn:
                return None, unit_by_dn[current], None
            current = normalize_dn(_parent_of(current))
        return None, None, None

    created = updated = skipped = conflicts = reactivation_skipped = 0
    details: list[str] = []
    processed_names: set[str] = set()   # ochrona przed duplikatami loginu w tej serii

    for u in users_raw:
        if u["username"] not in wanted:
            continue
        if not is_valid_login(u["username"]):
            skipped += 1
            details.append(f"⚠ {u['username']} — niedozwolone znaki w loginie, pominięty")
            continue

        # Pomiń zduplikowany login — importujemy tylko pierwsze wystąpienie
        # (tak samo oznacza je podgląd).
        if u["username"] in processed_names:
            skipped += 1
            details.append(f"⚠ {u['username']} — duplikat loginu, pominięty")
            continue
        processed_names.add(u["username"])

        # Konto WYŁĄCZONE w AD: nowego nie tworzymy, a istniejące konto
        # domenowe dezaktywujemy i zwalniamy jego stanowiska w strukturze.
        # Stanowiska zwalniamy także wtedy, gdy konto jest już nieaktywne —
        # mogło zostać kierownikiem, zanim dezaktywacja je zwalniała.
        if not u["is_enabled_in_ad"]:
            ex = find_user_by_login(session, u["username"])
            if ex and ex.auth_type == AuthType.ldap:
                if _admin_account_off_limits(current_user, ex):
                    skipped += 1
                    details.append(f"⚠ {u['username']} — konto administracyjne, "
                                   "zmienia je wyłącznie superadmin")
                    continue
                was_active = ex.is_active
                # Migawka obiegu PRZED zmianą is_active (powiadomienie nowego
                # odpowiedzialnego — patrz _stage_snapshot_before_deactivation).
                stage_before = _stage_snapshot_before_deactivation(session, ex.id)
                ex.is_active = False
                session.add(ex)
                released = release_manager_posts(session, ex.id, before=stage_before)
                session.commit()
                if was_active or released:
                    _audit_user(session, request, current_user,
                                action="user.deactivated_ad", target=ex,
                                details={"was_active": was_active,
                                         "released_posts": released})
                    updated += 1
                    details.append(f"~ {u['username']} — wyłączony w AD, dezaktywowany")
                else:
                    skipped += 1
                    details.append(f"⚠ {u['username']} — wyłączony w AD, konto już nieaktywne")
                continue
            skipped += 1
            details.append(f"⚠ {u['username']} — wyłączony w AD, pominięty")
            continue

        dept_id, unit_id, ambiguous = _resolve_dept_unit(u["parent_dn"])
        if ambiguous:
            details.append(f"⚠ {u['username']} — OU „{ambiguous}” jest przypisana kilku "
                           "komórkom; komórki nie zmieniono (popraw powiązania w strukturze)")
        # Importujemy WYŁĄCZNIE osoby z powiązanych jednostek organizacyjnych —
        # jeśli OU użytkownika nie mieści się w zaimportowanej strukturze, pomijamy.
        if dept_id is None and unit_id is None:
            skipped += 1
            details.append(f"⚠ {u['username']} — poza powiązaną strukturą OU, pominięty")
            continue
        ndn = normalize_dn(u["dn"])
        guid = u.get("guid") or None

        existing = find_user_by_login(session, u["username"])
        if existing and existing.auth_type != AuthType.ldap:
            conflicts += 1
            details.append(f"⚠ {u['username']} — konflikt z kontem lokalnym, pominięty")
            continue

        if existing:
            if _admin_account_off_limits(current_user, existing):
                skipped += 1
                details.append(f"⚠ {u['username']} — konto administracyjne, "
                               "zmienia je wyłącznie superadmin")
                continue
            old = {"full_name": existing.full_name, "email": existing.email,
                   "department_id": existing.department_id, "title": existing.title or ""}
            new_dept_id = dept_id or existing.department_id
            if existing.id == current_user.id and new_dept_id != existing.department_id:
                # Własnej komórki nie zmienia się importem — tak jak w edycji konta
                # (komórka kadrowa dałaby sobie samemu zdolność kadrową).
                new_dept_id = existing.department_id
                details.append(f"⚠ {u['username']} — to Twoje konto: komórki nie zmieniono "
                               "(własną komórkę zmienia inny administrator lub superadmin)")
            existing.full_name    = u["full_name"] or existing.full_name
            existing.email        = u["email"] or existing.email
            existing.department_id = new_dept_id
            existing.ldap_dn      = ndn
            if guid:
                existing.ldap_guid = guid
            # Stanowisko: AD jest źródłem prawdy — także wyczyszczenie w AD.
            existing.title        = u.get("title") or ""
            # is_active: import tylko DEZAKTYWUJE (gałąź wyżej). Konta wyłączonego
            # w SZUP nie włączamy po cichu — reaktywacja wyłącznie ręczna.
            session.add(existing)
            moved = None
            if existing.department_id != old["department_id"]:
                # Przeniesienie w AD: stanowiska w dawnej komórce są zwalniane,
                # wolne stanowisko w nowej obejmuje kierownik (org_sync).
                moved = after_department_change(session, existing, old["department_id"])
            session.commit(); session.refresh(existing)
            new = {"full_name": existing.full_name, "email": existing.email,
                   "department_id": existing.department_id, "title": existing.title or ""}
            diff = {k: {"old": old[k], "new": new[k]} for k in old if old[k] != new[k]}
            if diff:
                extra = {}
                if moved and (moved["released_dept_ids"] or moved["adopted"]
                              or moved["role_revoked"]):
                    extra = {"structure": {k: moved[k] for k in (
                        "released_dept_ids", "adopted", "role_revoked")}}
                _audit_user(session, request, current_user, action="user.updated_ad",
                            target=existing, details={"changes": diff, **extra})
            _hr_capability_event(session, request, current_user, existing,
                                 old["department_id"], via="ldap_import")
            updated += 1
            if not existing.is_active:
                reactivation_skipped += 1
                details.append(f"~ {u['username']} — zaktualizowany; konto wyłączone w SZUP, "
                               "pominięto reaktywację")
            else:
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
                ldap_guid=guid,
            )
            session.add(new_user); session.commit()
            _audit_user(session, request, current_user, action="user.created_ad",
                        target=new_user, details={"department_id": dept_id})
            _hr_capability_event(session, request, current_user, new_user, None,
                                 via="ldap_import")
            created += 1
            details.append(f"+ {u['username']} — utworzony")

    not_found = wanted - {u["username"] for u in users_raw}
    for nf in not_found:
        skipped += 1
        details.append(f"⚠ {nf} — nie znaleziony w AD, pominięty")

    return LdapUserImportResult(
        created=created, updated=updated, skipped=skipped, conflicts=conflicts,
        details=details, reactivation_skipped=reactivation_skipped,
    )
