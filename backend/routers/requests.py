"""
Router: Wnioski o uprawnienia — workflow PENDING_MANAGER → PENDING_IT → COMPLETED/REJECTED.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, col

from database import get_session
from models import (
    AccessRequest, RequestItem, RequestStatus,
    User, Unit, Department, PermissionSystem, PermissionSystemUnit,
    SystemPermission, has_role,
    AuthType, roles_to_json,
)
from services.auth_service import get_current_user
from services.permissions import (
    require_hr, require_it_staff,
    is_admin, managed_dept_ids, hr_scoped_unit_ids, unit_manager_dept_ids,
)

_log = logging.getLogger("szup.requests")


# ---------------------------------------------------------------------------
# Helpers — role i widoczność
# ---------------------------------------------------------------------------

def _managed_dept_ids(session: Session, user: User) -> tuple[list[int], list[int]]:
    """Cienki proxy do services.permissions.managed_dept_ids (historyczna nazwa)."""
    return managed_dept_ids(session, user)


def _validate_items_scope(session: Session, unit_id: int, items) -> None:
    """Zweryfikuj że każdy (system_id, permission_id) z items:
      - istnieje,
      - permission_id należy do tego system_id,
      - system jest dostępny w tej jednostce (all_units=True lub wpis w M:N).

    Rzuca HTTPException(400) przy pierwszej niezgodności.
    """
    # Wczytaj listę dozwolonych systemów dla tej jednostki jednym zapytaniem.
    scoped_ids = {
        int(x) for x in session.exec(
            select(PermissionSystemUnit.system_id)
            .where(PermissionSystemUnit.unit_id == unit_id)
        ).all()
    }
    for item in items:
        s = session.get(PermissionSystem, item.system_id)
        if not s:
            raise HTTPException(400, f"System {item.system_id} nie istnieje")
        p = session.get(SystemPermission, item.permission_id)
        if not p:
            raise HTTPException(400, f"Uprawnienie {item.permission_id} nie istnieje")
        if p.system_id != s.id:
            raise HTTPException(
                400,
                f"Uprawnienie {p.id} nie należy do systemu {s.id}",
            )
        if not s.all_units and s.id not in scoped_ids:
            raise HTTPException(
                400,
                f'System "{s.name}" nie jest dostępny w tej jednostce',
            )


def _clean_custom_values(session: Session, item) -> Optional[str]:
    """Zwaliduj i zserializuj wartość kontrolki JEDNEJ pozycji wniosku.

    Kontrolka (lista wyboru albo pole do wpisania) jest cechą KONKRETNEGO
    uprawnienia, nie całego oprogramowania: obok pozycji z importu, które są
    zwykłymi checkboxami, mogą stać pozycje dodane ręcznie przez IT, które
    doprecyzowuje się listą albo tekstem.

    Wartość trzymamy dalej w `RequestItem.custom_values` jako mapę
    nazwa→wartość — dzięki temu podgląd, PDF i „Moje uprawnienia" działają
    bez zmian, a wartości zapisane wcześniej (gdy pola definiowano przy
    programie) pozostają czytelne.
    """
    import json as _json
    from routers.systems import INPUT_OPTION_TYPES, _parse_options

    perm = session.get(SystemPermission, item.permission_id)
    itype = getattr(perm, "input_type", None) or "none" if perm else "none"
    if not perm or itype == "none":
        return None

    label = perm.permission_name
    opts = _parse_options(getattr(perm, "options", None))
    required = bool(getattr(perm, "input_required", False))
    # Pozycje odbierane (revoke) nie wymagają doprecyzowania — odbieramy całość.
    is_revoke = getattr(item, "kind", "grant") == "revoke"

    supplied = getattr(item, "custom_values", None) or {}
    raw = supplied.get(label)
    if raw is None and len(supplied) == 1:
        # Zgodność wstecz: wcześniej kluczem była nazwa POLA przy programie,
        # która nie musiała odpowiadać nazwie uprawnienia.
        raw = next(iter(supplied.values()))
    val = str(raw).strip() if raw is not None else ""

    if itype == "multiselect":
        chosen, seen = [], set()
        for part in val.split(","):
            v = part.strip()
            if not v or v in seen:
                continue
            if opts and v not in opts:
                raise HTTPException(
                    400,
                    f'Nieprawidłowa wartość „{v}" uprawnienia „{label}". '
                    f'Dozwolone: {", ".join(opts)}.',
                )
            seen.add(v); chosen.append(v)
        if not chosen:
            if required and not is_revoke:
                raise HTTPException(
                    400,
                    f'Uprawnienie „{label}" wymaga wybrania co najmniej '
                    f'jednej pozycji.',
                )
            return None
        # Kolejność z definicji — stabilna, niezależna od kolejności klikania.
        val = ", ".join([o for o in opts if o in seen] if opts else chosen)
    elif not val:
        if required and not is_revoke:
            raise HTTPException(
                400,
                f'Uprawnienie „{label}" wymaga uzupełnienia — '
                f'wypełnij je przy wyborze uprawnień.',
            )
        return None
    elif itype in INPUT_OPTION_TYPES and opts and val not in opts:
        raise HTTPException(
            400,
            f'Nieprawidłowa wartość uprawnienia „{label}". '
            f'Dozwolone: {", ".join(opts)}.',
        )

    return _json.dumps({label: val}, ensure_ascii=False)


router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DeclarationIn(BaseModel):
    """Oświadczenie wnioskującego wpisane w chwili kierowania wniosku do IT."""
    declared_by_name: str                  # „imię i nazwisko"
    declared_date: str                     # RRRR-MM-DD


class RequestItemSchema(BaseModel):
    system_id: int
    permission_id: int
    # Kierunek pozycji: "grant" (nadać) / "revoke" (odebrać). Pozwala na
    # wniosek o zmianę, który jednocześnie nadaje i odbiera (stan docelowy).
    kind: str = "grant"
    # Wartości pól dodatkowych oprogramowania ({"Zakres uprawnień": "FK, KP"}).
    # Definiują poziom/zakres dostępu; pola obowiązkowe muszą być wypełnione.
    custom_values: Optional[dict[str, str]] = None


class RequestCreate(BaseModel):
    worker_name: str
    worker_email: Optional[str] = None
    worker_phone: Optional[str] = None
    worker_position: Optional[str] = None
    # Data zatrudnienia od (nowy pracownik) / ostatni dzień pracy (ustanie).
    employment_from: Optional[date] = None
    work_until: Optional[date] = None
    worker_user_id: Optional[int] = None
    unit_id: int
    department_id: int
    items: list[RequestItemSchema] = []
    # Kierunek: "grant" (nadanie — nowy pracownik) lub "revoke" (odebranie —
    # ustanie stosunku pracy). Przy revoke worker_user_id wskazuje istniejącego
    # pracownika, a items to uprawnienia do odebrania.
    kind: str = "grant"
    # Typ wniosku (opcjonalny na start dla wstecznej kompatybilności API,
    # ale w praktyce wymuszany przez frontend). Gdy set → uruchamiamy
    # silnik workflow zamiast hardcoded flow.
    request_type_id: Optional[int] = None
    # Oświadczenie wnioskującego — wymagane, gdy złożenie wniosku od razu
    # kieruje go do IT (kierownik składa i sam zatwierdza wybór w 1-stopniu).
    declaration: Optional[DeclarationIn] = None


class DenyItemIn(BaseModel):
    item_id: int
    comment: Optional[str] = None


class WorkflowActionIn(BaseModel):
    action: str                            # "approve" | "reject" | "select" | "execute"
    comment: Optional[str] = None
    items: list[RequestItemSchema] = []    # dla akcji "select" (wybór uprawnień)
    # Odmowa KONKRETNYCH pozycji — kierownik nadrzędny (approve) albo IT (execute).
    # Pozycja zostaje na wniosku z komentarzem, ale nie wchodzi do uprawnień.
    denials: list[DenyItemIn] = []
    # Oświadczenie wnioskującego — wymagane, gdy TA akcja kieruje wniosek do
    # realizacji IT i wniosek nadaje uprawnienia. Brak → 428.
    declaration: Optional[DeclarationIn] = None
    # Dla akcji "execute": pozycje DOŁOŻONE przez IT (np. moduł wymaga zależnego
    # uprawnienia). Osobne pole od `items`, bo tam semantyka to „zastąp koszyk",
    # a tu „dołóż do zatwierdzonego". IT nigdy nie usuwa pozycji kierownika.
    added_items: list[RequestItemSchema] = []
    ad_username: Optional[str] = None      # dla akcji "execute" (IT wpisuje login AD)
    expected_node_id: Optional[str] = None  # H4 — optymistyczna kontrola współbieżności


class LinkWorker(BaseModel):
    ad_username: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_request(r: AccessRequest, items: list, session: Session | None = None) -> dict:
    dept_name = None
    dept_desc = None    # pełna nazwa komórki (opis OU z AD), np. „Biuro Informatyki”
    unit_name = None
    # Flaga komórki: czy wniosek wymaga akceptacji kierownika wyższego rzędu.
    # Front rozdziela na jej podstawie dwie ścieżki (1-stopniowa: kierownik →
    # IT; 2-stopniowa: kierownik → kierownik nadrzędny → IT).
    requires_higher = False
    assigned_to_name = None
    requested_by_name = None
    current_node_id = None
    # Dane z konta pracownika (gdy wniosek jest dowiązany) — do karty „Pracownik”:
    # login oraz stanowisko z AD jako fallback, gdy wniosek nie ma własnego.
    worker_username = None
    worker_title = ""
    worker_acc_email = None
    if session is not None:
        if r.worker_user_id:
            wu = session.get(User, r.worker_user_id)
            if wu:
                worker_username = wu.username
                worker_title = wu.title or ""
                worker_acc_email = wu.email
        if r.department_id:
            d = session.get(Department, r.department_id)
            if d:
                dept_name = d.name
                dept_desc = d.description
                requires_higher = bool(d.requires_higher_approval)
        if r.unit_id:
            u = session.get(Unit, r.unit_id)
            if u:
                unit_name = u.name
        aid = getattr(r, "assigned_to_user_id", None)
        if aid:
            au = session.get(User, aid)
            if au:
                assigned_to_name = au.full_name or au.username
        # „Wnioskujący" o konkretne uprawnienia = aktor ostatniego kroku
        # „select" w obiegu (zwykle kierownik I stopnia), NIE pracownik kadr,
        # który jedynie zgłosił zatrudnienie. Fallback: twórca wniosku.
        from models import WorkflowInstance, WorkflowStep, WorkflowStepAction
        inst = session.exec(
            select(WorkflowInstance).where(WorkflowInstance.request_id == r.id)
        ).first()
        if inst:
            sel_step = session.exec(
                select(WorkflowStep)
                .where(WorkflowStep.instance_id == inst.id)
                .where(WorkflowStep.action == WorkflowStepAction.select)
                .order_by(WorkflowStep.step_index.desc())
            ).first()
            if sel_step and sel_step.actor_name:
                requested_by_name = sel_step.actor_name
            # Front odsyła to jako `expected_node_id` przy akcji — optymistyczna
            # kontrola współbieżności (H4), żeby dwie osoby nie wykonały kroku naraz.
            from models import WorkflowInstanceStatus
            if inst.status == WorkflowInstanceStatus.active:
                current_node_id = inst.current_node_id
    return {
        "id": r.id,
        "worker_name": r.worker_name,
        "worker_email": r.worker_email or worker_acc_email,
        "worker_phone": r.worker_phone,
        "worker_position": r.worker_position or worker_title,
        "worker_username": worker_username,
        "employment_from": r.employment_from.isoformat() if getattr(r, "employment_from", None) else None,
        "work_until": r.work_until.isoformat() if getattr(r, "work_until", None) else None,
        "worker_user_id": r.worker_user_id,
        "unit_id": r.unit_id,
        "unit_name": unit_name,
        "department_id": r.department_id,
        "department_name": dept_name,
        "department_description": dept_desc,
        "requires_higher_approval": requires_higher,
        "kind": getattr(r, "kind", "grant") or "grant",
        "status": r.status,
        "created_by_id": r.created_by_id,
        "created_by_name": r.created_by_name,
        # kto WNIOSKUJE o uprawnienia (aktor kroku „select"; fallback: twórca)
        "requested_by_name": requested_by_name or r.created_by_name,
        "current_node_id": current_node_id,
        "approved_by_id": r.approved_by_id,
        "completed_by_id": r.completed_by_id,
        "selector_by_id": r.selector_by_id,
        "assigned_to_user_id": getattr(r, "assigned_to_user_id", None),
        "assigned_to_name": assigned_to_name,
        "manager_comment": r.manager_comment,
        "it_comment": r.it_comment,
        "selector_comment": r.selector_comment,
        "created_at": r.created_at.isoformat(),
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
        "selected_at": r.selected_at.isoformat() if r.selected_at else None,
        "items": items,
    }


def _get_items(session: Session, request_id: int) -> list:
    items = session.exec(select(RequestItem).where(RequestItem.request_id == request_id)).all()
    result = []
    for item in items:
        sys_obj  = session.get(PermissionSystem, item.system_id)
        perm_obj = session.get(SystemPermission, item.permission_id)
        # Wartości pól dodatkowych (poziom/zakres dostępu) + ich definicje,
        # żeby front mógł wyrenderować formularz i pokazać wypełnione wartości.
        cvals = {}
        raw = getattr(item, "custom_values", None)
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    cvals = {str(k): str(v) for k, v in loaded.items()}
            except (json.JSONDecodeError, TypeError):
                cvals = {}
        # Definicja kontrolki uprawnienia (lista / pole) — front renderuje
        # ją przy pozycji i pokazuje wypełnioną wartość.
        from routers.systems import _parse_options
        pinput = {
            "type": (getattr(perm_obj, "input_type", None) or "none") if perm_obj else "none",
            "options": _parse_options(getattr(perm_obj, "options", None)) if perm_obj else [],
            "required": bool(getattr(perm_obj, "input_required", False)) if perm_obj else False,
            "prompt": getattr(perm_obj, "input_prompt", None) if perm_obj else None,
        }
        # Pozycje dołożone przez IT na etapie realizacji — front je oznacza,
        # żeby było widać, co doszło poza pierwotnym wnioskiem kierownika.
        added_by_id = getattr(item, "added_by_user_id", None)
        added_by_name = None
        if added_by_id:
            au = session.get(User, added_by_id)
            if au:
                added_by_name = au.full_name or au.username
        denied_by_id = getattr(item, "denied_by_user_id", None)
        denied_by_name = None
        if denied_by_id:
            du = session.get(User, denied_by_id)
            if du:
                denied_by_name = du.full_name or du.username
        fulfilled_by_id = getattr(item, "fulfilled_by_user_id", None)
        fulfilled_by_name = None
        if fulfilled_by_id:
            fu = session.get(User, fulfilled_by_id)
            if fu:
                fulfilled_by_name = fu.full_name or fu.username
        result.append({
            "id": item.id,
            "system_id": item.system_id,
            "system_name": sys_obj.name if sys_obj else None,
            "permission_id": item.permission_id,
            "permission_name": perm_obj.permission_name if perm_obj else None,
            "group_name": getattr(perm_obj, "group_name", None) if perm_obj else None,
            "subgroup_name": getattr(perm_obj, "subgroup_name", None) if perm_obj else None,
            "kind": getattr(item, "kind", "grant") or "grant",
            "custom_values": cvals,
            "input": pinput,
            "added_by_user_id": added_by_id,
            "added_by_name": added_by_name,
            "denied": bool(getattr(item, "denied", False)),
            "deny_comment": getattr(item, "deny_comment", None),
            "denied_by_name": denied_by_name,
            "denied_at": (item.denied_at.isoformat()
                          if getattr(item, "denied_at", None) else None),
            "fulfilled": bool(getattr(item, "fulfilled", False)),
            "fulfilled_by_name": fulfilled_by_name,
            "fulfilled_at": (item.fulfilled_at.isoformat()
                             if getattr(item, "fulfilled_at", None) else None),
        })
    return result


def _item_kind(item, request_kind: str) -> str:
    """Kierunek pozycji: własny, a gdy brak (stare rekordy) — kierunek wniosku."""
    k = getattr(item, "kind", None)
    if k in ("grant", "revoke"):
        return k
    return "revoke" if request_kind == "revoke" else "grant"


def _dept_name(session: Session, dept_id: int) -> str:
    d = session.get(Department, dept_id)
    return d.name if d else str(dept_id)


def _user_email(session: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(User, user_id)
    return u.email if u else None


def _resolve_or_create_worker(
    session: Session, ad_username: str, req: AccessRequest
) -> User:
    """
    Znajduje konto po sAMAccountName (username) lub tworzy nowe „ghost" konto
    typu LDAP z danymi z wniosku. Uzupełnia department_id jeśli puste.
    Nie zmienia konta lokalnego (admin/superadmin) — rzuca 400.
    """
    uname = (ad_username or "").strip().lower()
    if not uname:
        raise HTTPException(400, "Podaj nazwę konta AD (sAMAccountName) pracownika")

    # Username w bazie traktujemy jako wpisany — ale porównanie case-insensitive.
    existing = session.exec(
        select(User).where(User.username == uname)
    ).first()
    if not existing:
        # case-insensitive fallback (SQLite domyślnie case-sensitive dla LIKE,
        # ale czasem users są zapisani z oryginalną wielkością liter)
        from sqlalchemy import func
        existing = session.exec(
            select(User).where(func.lower(User.username) == uname)
        ).first()

    if existing:
        # Nie dowiązujemy wniosku do kont lokalnych typu admin/superadmin,
        # żeby nie mieszać kont technicznych z listą pracowników.
        if has_role(existing, "superadmin", "admin"):
            raise HTTPException(
                400,
                f'Login "{uname}" wskazuje na konto administracyjne — wpisz '
                f'sAMAccountName pracownika, dla którego realizujesz wniosek',
            )
        # Uzupełnij brakujące dane z wniosku (nie nadpisuj istniejących).
        changed = False
        if not existing.full_name and req.worker_name:
            existing.full_name = req.worker_name; changed = True
        if not existing.email and req.worker_email:
            existing.email = req.worker_email; changed = True
        if not existing.department_id and req.department_id:
            existing.department_id = req.department_id; changed = True
        if changed:
            session.add(existing); session.commit(); session.refresh(existing)
        return existing

    # Tworzymy „ghost" konto LDAP, is_active=True. Przy późniejszym imporcie
    # z AD (Users → LDAP → import) dane zostaną nadpisane aktualnymi z AD.
    new_user = User(
        username=uname,
        full_name=req.worker_name or uname,
        email=req.worker_email,
        password_hash="!ldap-managed!",
        roles=roles_to_json(["viewer"]),
        auth_type=AuthType.ldap,
        is_active=True,
        department_id=req.department_id,
    )
    session.add(new_user); session.commit(); session.refresh(new_user)
    return new_user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_requests(
    status_filter: Optional[RequestStatus] = Query(None, alias="status"),
    scope: Optional[str] = Query(None, description="manager|it — wymuś perspektywę roli"),
    limit: int = Query(200, le=1000),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(AccessRequest)

    # Perspektywa "mine" — wyłącznie wnioski, które TEN użytkownik złożył
    # (np. kierownik wnioskujący dla swoich pracowników). Działa dla każdej roli.
    if scope == "mine":
        stmt = stmt.where(AccessRequest.created_by_id == current_user.id)
    # Gdy użytkownik jawnie prosi o perspektywę "manager" (panel kierownika),
    # ZAWSZE zawężamy do wydziałów, którymi kieruje — nawet jeśli ma dodatkowo
    # rolę it_staff. Admin/superadmin zawsze widzi wszystko.
    elif scope == "manager" and not is_admin(current_user):
        if not has_role(current_user, "manager"):
            return []
        direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
        all_ids = list({*direct_ids, *escalated_ids})
        if not all_ids:
            return []
        stmt = stmt.where(col(AccessRequest.department_id).in_(all_ids))
    elif is_admin(current_user) or has_role(current_user, "it_staff"):
        pass  # widzą wszystko (IT w panelu IT; admin wszędzie)
    elif has_role(current_user, "manager"):
        # widzi wnioski ze swoich wydziałów (bezpośrednio) i z wydziałów
        # podrzędnych z flagą requires_higher_approval (do akceptacji wyższego rzędu).
        direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
        all_ids = list({*direct_ids, *escalated_ids})
        if not all_ids:
            return []
        stmt = stmt.where(col(AccessRequest.department_id).in_(all_ids))
    else:
        # hr, viewer — tylko własne
        stmt = stmt.where(AccessRequest.created_by_id == current_user.id)

    if status_filter:
        stmt = stmt.where(AccessRequest.status == status_filter)

    stmt = stmt.order_by(col(AccessRequest.created_at).desc()).limit(limit).offset(offset)
    rows = session.exec(stmt).all()
    out = [_serialize_request(r, _get_items(session, r.id), session) for r in rows]

    # W perspektywie kierownika/„moje" dołącz informację o bieżącym węźle obiegu
    # i o tym, czy TEN użytkownik może na nim działać. Dzięki temu panel potrafi
    # rozdzielić wnioski „do obsługi" (can_act) od „w realizacji" (it_execute) i
    # pokazać etap w „Moich wnioskach".
    if scope in ("manager", "mine"):
        from models import WorkflowInstance, WorkflowInstanceStatus
        from services.workflow import can_act, find_node
        import json as _json
        by_id = {r.id: r for r in rows}
        for row in out:
            r = by_id[row["id"]]
            node_type, act = None, False
            inst = session.exec(
                select(WorkflowInstance).where(WorkflowInstance.request_id == r.id)
            ).first()
            if inst and inst.status == WorkflowInstanceStatus.active and inst.current_node_id:
                try:
                    graph = _json.loads(inst.template_snapshot)
                    node = find_node(graph, inst.current_node_id)
                except Exception:
                    node = None
                if node:
                    node_type = node.get("type")
                    dept = session.get(Department, r.department_id) if r.department_id else None
                    allowed, _reason = can_act(node, r, dept, current_user, session)
                    act = bool(allowed)
            row["current_node_type"] = node_type
            row["can_act"] = act
    return out


@router.get("/my-scope")
def my_scope(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Zwraca flagi określające zakładki dostępne w panelu kierownika:
      - can_select  — użytkownik jest bezpośrednim kierownikiem co najmniej
                      jednego wydziału z flagą 2-stopniową (wybiera uprawnienia
                      dla swoich pracowników, zatwierdza kierownik nadrzędny).
      - can_approve — użytkownik akceptuje wnioski:
                      * jest kierownikiem wydziału 1-stopniowego, lub
                      * jest kierownikiem wydziału nadrzędnego dla co najmniej
                        jednego subwydziału 2-stopniowego.
    Admin/superadmin widzi obie zakładki.
    """
    if is_admin(current_user):
        return {"can_select": True, "can_approve": True}
    if not has_role(current_user, "manager"):
        return {"can_select": False, "can_approve": False}

    direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
    # flaga na wydziałach bezpośrednich (czy jest w nich 2-stopniowy?)
    direct_depts = []
    if direct_ids:
        direct_depts = session.exec(
            select(Department).where(col(Department.id).in_(direct_ids))
        ).all()

    can_select  = any(d.requires_higher_approval for d in direct_depts)
    can_approve = any(not d.requires_higher_approval for d in direct_depts) or bool(escalated_ids)
    return {"can_select": can_select, "can_approve": can_approve}


@router.get("/dashboard")
def workflow_dashboard(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Pulpit obiegu wniosków bieżącego użytkownika: liczniki kolejek
    (do przypisania / akceptacji / realizacji) + powiadomienia o wnioskach
    czekających na jego działanie. Zastępuje dawny /compliance/my w zakresie
    obiegu (moduły ISO/RODO usunięte)."""
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import can_act, find_node
    import json as _json

    def _entry(r: AccessRequest) -> Optional[dict]:
        """Zwraca wpis kolejki, jeśli bieżący użytkownik może działać na
        aktualnym węźle obiegu tego wniosku; inaczej None."""
        inst = session.exec(
            select(WorkflowInstance).where(WorkflowInstance.request_id == r.id)
        ).first()
        if not inst or inst.status != WorkflowInstanceStatus.active or not inst.current_node_id:
            return None
        try:
            node = find_node(_json.loads(inst.template_snapshot), inst.current_node_id)
        except Exception:
            node = None
        if not node:
            return None
        dept = session.get(Department, r.department_id) if r.department_id else None
        allowed, _reason = can_act(node, r, dept, user, session)
        if not allowed:
            return None
        return {
            "request_id": r.id,
            "worker_name": r.worker_name,
            "dept_id": r.department_id,
            "dept_name": dept.name if dept else None,
            "dept_description": dept.description if dept else None,
            "node_label": node.get("label") or node.get("type"),
            "node_type": node.get("type"),
            "created_at": r.created_at,
        }

    pending: list[dict] = []
    seen_ids: set[int] = set()

    # 1) Perspektywa kierownika — wnioski z komórek, którymi zarządza.
    direct_ids, escalated_ids = managed_dept_ids(session, user)
    all_managed = set(direct_ids) | set(escalated_ids)
    if all_managed:
        for r in session.exec(
            select(AccessRequest).where(AccessRequest.department_id.in_(all_managed))
        ).all():
            e = _entry(r)
            if e:
                pending.append(e); seen_ids.add(r.id)

    # 2) Perspektywa IT — kolejka realizacji (it_execute) niezależnie od komórki.
    if has_role(user, "it_staff"):
        for r in session.exec(
            select(AccessRequest).where(AccessRequest.status == RequestStatus.pending_it)
        ).all():
            if r.id in seen_ids:
                continue
            e = _entry(r)
            if e:
                pending.append(e); seen_ids.add(r.id)

    pending_prepare = sum(1 for p in pending if p.get("node_type") == "select_permissions")
    pending_approve = sum(1 for p in pending if p.get("node_type") in ("manager_approve", "higher_manager_approve"))
    pending_execute = sum(1 for p in pending if p.get("node_type") == "it_execute")

    # Wnioski o zmianę nazwiska trafiają WPROST do IT (osobny, lekki obieg) —
    # też są „do realizacji", więc IT musi je widzieć na pulpicie obok wniosków
    # o uprawnienia. Liczymy osobno, żeby nie mieszać z licznikiem uprawnień.
    pending_names = 0
    if has_role(user, "it_staff"):
        from models import NameChangeRequest
        pending_names = len(session.exec(
            select(NameChangeRequest).where(NameChangeRequest.status == "pending")
        ).all())

    return {
        "pending_approvals_count": len(pending),
        "pending_prepare_count":   pending_prepare,
        "pending_approve_count":   pending_approve,
        "pending_execute_count":   pending_execute,
        "pending_names_count":     pending_names,
        "pending_approvals_list":  pending[:10],
        # Flagi widoczności kafelków KPI — kafelek pokazujemy tylko roli,
        # której kolejka faktycznie dotyczy:
        #  - przypisanie uprawnień: każdy kierownik (zarządza jakąś komórką),
        #  - akceptacja: TYLKO kierownik wyższego rzędu (ma podrzędne komórki
        #    2-stopniowe) — kierownik I stopnia nie akceptuje,
        #  - realizacja: tylko pracownik IT.
        "show_prepare": bool(all_managed),
        "show_approve": bool(escalated_ids),
        "show_execute": has_role(user, "it_staff"),
    }


@router.get("/{request_id}")
def get_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)
    return _serialize_request(r, _get_items(session, r.id), session)


def _require_request_creator(current_user: User = Depends(get_current_user),
                             session: Session = Depends(get_session)) -> User:
    # Wariant A: wnioski składa HR (rola lub komórka kadrowa) albo kierownik.
    # Administrator konfiguruje system i NIE tworzy wniosków; superadmin — break-glass.
    from services.permissions import user_is_hr
    if not (has_role(current_user, "superadmin", "manager")
            or user_is_hr(session, current_user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Wymagana rola HR (lub komórka kadrowa) albo kierownika")
    return current_user


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_request(
    data: RequestCreate,
    current_user: User = Depends(_require_request_creator),
    session: Session = Depends(get_session),
):
    if not session.get(Unit, data.unit_id):
        raise HTTPException(400, "Jednostka nie istnieje")
    dept = session.get(Department, data.department_id)
    if not dept:
        raise HTTPException(400, "Wydział nie istnieje")

    # --- Nowa ścieżka: request_type_id → silnik workflow -----------------
    if data.request_type_id is not None:
        from models import RequestType, WorkflowTemplate
        from services.workflow import start_instance

        rtype = session.get(RequestType, data.request_type_id)
        if not rtype or not rtype.is_active:
            raise HTTPException(400, "Typ wniosku nie istnieje lub jest nieaktywny")
        tpl = session.get(WorkflowTemplate, rtype.workflow_template_id)
        if not tpl or not tpl.is_active:
            raise HTTPException(400, "Szablon obiegu dla tego typu jest niedostępny")

        # "grant" — nadanie (nowy pracownik), "revoke" — odebranie (ustanie),
        # "change" — zmiana (stan docelowy: część pozycji nadaje, część odbiera).
        kind = data.kind if data.kind in ("grant", "revoke", "change") else "grant"
        worker_user_id: Optional[int] = data.worker_user_id
        if kind in ("revoke", "change") and worker_user_id is None:
            raise HTTPException(400,
                "Wniosek o odebranie/zmianę uprawnień wymaga wskazania pracownika")
        if worker_user_id is not None:
            wu = session.get(User, worker_user_id)
            if not wu:
                raise HTTPException(400, "Wskazany pracownik nie istnieje")
            if wu.department_id != data.department_id:
                raise HTTPException(400,
                    "Wybrany pracownik nie należy do wskazanego wydziału")

        # M3 — scoping wnioskodawcy (spójnie ze ścieżką legacy):
        #  - kierownik (bez HR) może składać tylko dla SWOICH wydziałów,
        #  - pracownik HR — tylko dla przypisanych mu jednostek.
        # Superadmin (break-glass) — bez ograniczeń.
        if not has_role(current_user, "superadmin"):
            from services.permissions import user_is_hr
            hr_cap = user_is_hr(session, current_user)
            if has_role(current_user, "manager") and not hr_cap:
                direct_ids, escalated_ids = managed_dept_ids(session, current_user)
                unit_ids = unit_manager_dept_ids(session, current_user)
                if data.department_id not in {*direct_ids, *escalated_ids, *unit_ids}:
                    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "Możesz składać wnioski tylko dla pracowników swoich wydziałów")
            elif hr_cap:
                scoped_units = hr_scoped_unit_ids(session, current_user)
                if scoped_units is not None and data.unit_id not in scoped_units:
                    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "Możesz składać wnioski tylko dla przypisanych Ci jednostek")

        # H3 — całość (wniosek + pozycje + instancja obiegu + ewentualny
        # auto-select) w JEDNEJ transakcji. Przy dowolnym błędzie rollback,
        # żeby nie zostawić osieroconego wniosku bez instancji obiegu.
        req = AccessRequest(
            worker_name=data.worker_name,
            worker_email=data.worker_email,
            worker_phone=data.worker_phone,
            worker_position=data.worker_position,
            employment_from=data.employment_from,
            work_until=data.work_until,
            worker_user_id=worker_user_id,
            unit_id=data.unit_id,
            department_id=data.department_id,
            kind=kind,
            request_type_id=rtype.id,
            status=RequestStatus.pending_manager,   # zostanie nadpisany przez silnik
            created_by_id=current_user.id,
            created_by_name=current_user.full_name or current_user.username,
        )
        try:
            session.add(req)
            session.flush()   # nadaje req.id bez zatwierdzania transakcji

            # Ewentualne uprawnienia od razu z wniosku (np. HR podpowiada,
            # kierownik ma je do potwierdzenia w kroku select_permissions).
            if data.items:
                _validate_items_scope(session, req.unit_id, data.items)
                for item in data.items:
                    ik = item.kind if item.kind in ("grant", "revoke") else (
                        "revoke" if kind == "revoke" else "grant")
                    session.add(RequestItem(
                        request_id=req.id, system_id=item.system_id,
                        permission_id=item.permission_id, kind=ik,
                        custom_values=_clean_custom_values(session, item)))
                session.flush()

            start_instance(session, req, tpl)
            session.flush()

            # Jeśli wniosek składa osoba, która i tak wykonywałaby krok „wybór
            # uprawnień" (kierownik/zastępca tej komórki) i podała już pozycje —
            # zaliczamy ten krok automatycznie. Inaczej musiałaby zatwierdzać
            # własny wniosek drugi raz. Krok trafia do śladu audytowego z nią
            # jako aktorem, a obieg idzie od razu dalej (wyższy rząd albo IT).
            if data.items:
                from models import WorkflowInstance, WorkflowInstanceStatus
                from services.workflow import can_act, find_node, execute_action
                import json as _json

                inst = session.exec(
                    select(WorkflowInstance).where(WorkflowInstance.request_id == req.id)
                ).first()
                if inst and inst.status == WorkflowInstanceStatus.active and inst.current_node_id:
                    try:
                        node = find_node(_json.loads(inst.template_snapshot), inst.current_node_id)
                    except Exception:
                        node = None
                    if node and node.get("type") == "select_permissions":
                        allowed, _reason = can_act(node, req, dept, current_user, session)
                        if allowed:
                            payload = {"items": [
                                {"system_id": i.system_id, "permission_id": i.permission_id,
                                 "kind": (i.kind if i.kind in ("grant", "revoke")
                                          else ("revoke" if kind == "revoke" else "grant")),
                                 "custom_values": i.custom_values or {}}
                                for i in data.items
                            ]}
                            # Auto-select w 1-stopniu ląduje wprost na it_execute —
                            # jeśli nadaje uprawnienia, wymaga oświadczenia (428).
                            payload = _enforce_declaration(
                                session, inst, req, "select", current_user,
                                data.declaration, payload)
                            execute_action(
                                session, inst, req, current_user, "select",
                                payload=payload,
                                comment="Wybór uprawnień wykonany przez składającego wniosek",
                            )

            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            _log.exception("create_request (workflow) — błąd tworzenia wniosku")
            raise HTTPException(500, "Nie udało się utworzyć wniosku (błąd obiegu).")
        session.refresh(req)

        return _serialize_request(req, _get_items(session, req.id), session)
    # --- Koniec ścieżki workflow ----------------------------------------

    # Czy to kierownik wystawia wniosek „ze swojej linii"? (Nie admin/HR —
    # także nie pracownik komórki kadrowej, który działa jak HR.)
    from services.permissions import user_is_hr as _user_is_hr
    is_pure_manager = (
        has_role(current_user, "manager")
        and not has_role(current_user, "superadmin", "admin")
        and not _user_is_hr(session, current_user)
    )

    # Routing statusu:
    #  - HR/admin: standardowy flow (pending_selection w 2-stopniowym,
    #    pending_manager w 1-stopniowym).
    #  - Manager wystawia sam: pomijamy ten etap, na którym i tak sam by
    #    akceptował. W 2-stopniowym, gdy nadrzędnym kierownikiem też jest on —
    #    idzie prosto do IT. Gdy nie — do kierownika wydziału nadrzędnego.
    auto_selected_by_manager = False
    auto_approved_by_manager = False

    # Kierownik CAŁEJ jednostki (podgląd + wnioskowanie) może wystawiać dla
    # pracowników swojej jednostki, ale NIE jest kierownikiem komórki w obiegu —
    # jego wniosek idzie normalną ścieżką akceptacji (nie auto-zatwierdza).
    direct_ids, escalated_ids = managed_dept_ids(session, current_user)
    is_dept_manager_here = data.department_id in {*direct_ids, *escalated_ids}
    is_unit_head_here = data.department_id in unit_manager_dept_ids(session, current_user)

    if is_pure_manager and not (is_dept_manager_here or is_unit_head_here):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Możesz składać wnioski tylko dla pracowników swoich wydziałów")

    if is_pure_manager and is_dept_manager_here:
        if dept.requires_higher_approval:
            parent = session.get(Department, dept.parent_dept_id) if dept.parent_dept_id else None
            # manager wybrał uprawnienia — zapisujemy go jako selector
            auto_selected_by_manager = True
            if parent and parent.manager_user_id == current_user.id:
                # kierownik wydziału nadrzędnego składa dla pracownika
                # podrzędnego 2-stopniowego → on też akceptuje → prosto do IT
                initial_status = RequestStatus.pending_it
                auto_approved_by_manager = True
            else:
                # bezpośredni kierownik wydziału → do kierownika nadrzędnego
                initial_status = RequestStatus.pending_manager
        else:
            # wydział 1-stopniowy — kierownik wystawia dla swojego pracownika → prosto do IT
            initial_status = RequestStatus.pending_it
            auto_approved_by_manager = True
    else:
        initial_status = (
            RequestStatus.pending_selection if dept.requires_higher_approval
            else RequestStatus.pending_manager
        )

    # Dowiązanie do konta pracownika (opcjonalne). Waliduj, że user istnieje
    # i ma przypisany ten sam wydział (spójność danych).
    worker_user_id: Optional[int] = data.worker_user_id
    if worker_user_id is not None:
        wu = session.get(User, worker_user_id)
        if not wu:
            raise HTTPException(400, "Wskazany pracownik nie istnieje")
        if wu.department_id != data.department_id:
            raise HTTPException(400,
                "Wybrany pracownik nie należy do wskazanego wydziału")

    # Serializuj also _serialize_request ma być fresh
    now = datetime.utcnow()
    req = AccessRequest(
        worker_name=data.worker_name,
        worker_email=data.worker_email,
        worker_phone=data.worker_phone,
        worker_position=data.worker_position,
        employment_from=data.employment_from,
        work_until=data.work_until,
        worker_user_id=worker_user_id,
        unit_id=data.unit_id,
        department_id=data.department_id,
        status=initial_status,
        created_by_id=current_user.id,
        created_by_name=current_user.full_name or current_user.username,
    )
    if auto_selected_by_manager:
        req.selector_by_id = current_user.id
        req.selected_at = now
    if auto_approved_by_manager:
        req.approved_by_id = current_user.id
        req.approved_at = now
    session.add(req); session.commit(); session.refresh(req)

    _validate_items_scope(session, req.unit_id, data.items)
    for item in data.items:
        session.add(RequestItem(request_id=req.id, system_id=item.system_id,
                                permission_id=item.permission_id))
    session.commit()

    # powiadomienie e-mail — adresat zależy od docelowego etapu.
    # M5 — best-effort: wniosek jest już zapisany; awaria dyspozycji maila NIE
    # może zwrócić 500 ani cofnąć wniosku (asymetria z silnikiem workflow).
    try:
        import threading
        if initial_status == RequestStatus.pending_selection and dept.manager_user_id:
            mgr_email = _user_email(session, dept.manager_user_id)
            if mgr_email:
                from services.email_alerts import notify_selector_new_request
                threading.Thread(target=notify_selector_new_request, daemon=True, kwargs={
                    "manager_email": mgr_email, "request_id": req.id,
                    "worker_name": req.worker_name, "dept_name": dept.name,
                    "created_by": req.created_by_name or "",
                    "from_name": current_user.full_name or current_user.username,
                    "from_email": current_user.email,
                }).start()
        elif initial_status == RequestStatus.pending_manager:
            # docelowy manager to: parent (w 2-stopniowym) albo dept (w 1-stopniowym)
            if dept.requires_higher_approval and dept.parent_dept_id:
                parent = session.get(Department, dept.parent_dept_id)
                target_mgr_id = parent.manager_user_id if parent else None
            else:
                target_mgr_id = dept.manager_user_id
            if target_mgr_id:
                mgr_email = _user_email(session, target_mgr_id)
                if mgr_email:
                    from services.email_alerts import notify_manager_new_request
                    threading.Thread(target=notify_manager_new_request, daemon=True, kwargs={
                        "manager_email": mgr_email, "request_id": req.id,
                        "worker_name": req.worker_name, "dept_name": dept.name,
                        "created_by": req.created_by_name or "",
                        "from_name": current_user.full_name or current_user.username,
                        "from_email": current_user.email,
                    }).start()
        elif initial_status == RequestStatus.pending_it:
            # wniosek idzie prosto do IT (manager-fast-path)
            from services.permissions import users_with_role
            it_emails = [u.email for u in users_with_role(session, "it_staff") if u.email]
            if it_emails:
                from services.email_alerts import notify_it_request_approved
                mgr_name = current_user.full_name or current_user.username
                threading.Thread(target=notify_it_request_approved, daemon=True, kwargs={
                    "it_emails": it_emails, "request_id": req.id,
                    "worker_name": req.worker_name, "dept_name": dept.name,
                    "manager_name": mgr_name,
                    "from_name": current_user.full_name or current_user.username,
                    "from_email": current_user.email,
                }).start()
    except Exception:
        _log.warning("create_request (legacy) — nie udało się zlecić powiadomienia e-mail",
                     exc_info=True)

    return _serialize_request(req, _get_items(session, req.id), session)


# --- Legacy endpointy /manager-action, /selector-action, /it-action USUNIĘTE. ---
# Cały obieg wniosków idzie teraz wyłącznie przez silnik workflow
# (POST /requests/{id}/workflow/action, akcje: select | approve | reject | execute),
# co gwarantuje spójność instancji obiegu i łańcucha kroków audytowych.


class AssignIn(BaseModel):
    user_id: Optional[int] = None      # None → zdejmij przypisanie


@router.post("/{request_id}/assign")
def assign_request(
    request_id: int,
    data: AssignIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Przekazanie wniosku pracownikowi IT przez KIEROWNIKA IT.

    Kierownik IT = osoba mająca JEDNOCZEŚNIE rolę „manager" i „it_staff".
    TYLKO ona może przekazywać — admin/superadmin NIE ma tego uprawnienia.
    Kierownik IT może zrealizować wniosek sam albo przekazać go pracownikowi IT.
    Przypisanie jest INFORMACYJNE — nie blokuje realizacji przez innych z IT.
    """
    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")

    is_it_manager = has_role(current_user, "manager") and has_role(current_user, "it_staff")
    if not is_it_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Wniosek może przekazać wyłącznie kierownik IT "
            "(konto z rolą kierownik ORAZ pracownik IT)")

    if data.user_id is None:
        r.assigned_to_user_id = None
    else:
        target = session.get(User, data.user_id)
        if not target or not target.is_active:
            raise HTTPException(400, "Wskazany pracownik nie istnieje lub jest nieaktywny")
        if not has_role(target, "it_staff"):
            raise HTTPException(400, "Wniosek można przekazać tylko pracownikowi IT")
        r.assigned_to_user_id = target.id

    session.add(r); session.commit(); session.refresh(r)
    return _serialize_request(r, _get_items(session, r.id), session)


@router.post("/{request_id}/link-worker")
def link_worker(
    request_id: int,
    data: LinkWorker,
    current_user: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    """
    Retroaktywne dowiązanie konta AD do wniosku (również zrealizowanego).
    Używane do „posprzątania" starych wniosków, w których worker_user_id
    nie został zapisany.
    """
    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    worker = _resolve_or_create_worker(session, data.ad_username, r)
    r.worker_user_id = worker.id
    session.add(r); session.commit()
    return _serialize_request(r, _get_items(session, r.id), session)


@router.get("/{request_id}/pdf")
def get_request_pdf(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Zwraca PDF wniosku — dokument do wydruku, podpisu i przesłania
    przez EZD FINN do Biura Informatyki UM Wodzisław Śląski.
    """
    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    from services.pdf_generator import generate_request_pdf
    try:
        pdf_bytes = generate_request_pdf(session, r)
    except Exception as exc:
        raise HTTPException(500, f"Błąd generowania PDF: {exc}")

    filename = f"SZUP_wniosek_{r.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/stats/summary")
def stats_summary(
    scope: Optional[str] = Query(None, description="manager — wymuś perspektywę kierownika"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Ten sam scoping, co w list_requests — statystyki mają odzwierciedlać
    # to, co użytkownik faktycznie widzi.
    base = select(AccessRequest.id, AccessRequest.status)
    if scope == "manager" and not is_admin(current_user):
        if not has_role(current_user, "manager"):
            return {st.value: 0 for st in RequestStatus}
        direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
        all_ids = list({*direct_ids, *escalated_ids})
        if not all_ids:
            return {st.value: 0 for st in RequestStatus}
        base = base.where(col(AccessRequest.department_id).in_(all_ids))
    elif is_admin(current_user) or has_role(current_user, "it_staff"):
        pass  # widzą wszystko
    elif has_role(current_user, "manager"):
        direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
        all_ids = list({*direct_ids, *escalated_ids})
        if not all_ids:
            return {st.value: 0 for st in RequestStatus}
        base = base.where(col(AccessRequest.department_id).in_(all_ids))
    else:
        base = base.where(AccessRequest.created_by_id == current_user.id)

    counts = {st.value: 0 for st in RequestStatus}
    for _id, st in session.exec(base).all():
        key = st.value if hasattr(st, "value") else str(st)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _check_access(user: User, r: AccessRequest, session: Session) -> None:
    if is_admin(user) or has_role(user, "it_staff"):
        return
    if has_role(user, "manager"):
        direct_ids, escalated_ids = _managed_dept_ids(session, user)
        if r.department_id in direct_ids or r.department_id in escalated_ids:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak dostępu do tego wniosku")
    # hr, viewer — tylko własne
    if r.created_by_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak dostępu do tego wniosku")


# ===========================================================================
# Workflow — konfigurowalny obieg (silnik services/workflow.py)
# ===========================================================================

@router.get("/{request_id}/workflow")
def get_workflow_state(
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Zwraca aktualny stan obiegu dla wniosku (pasek postępu + kroki)."""
    from models import WorkflowInstance
    from services.workflow import serialize_instance

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        return {"workflow_enabled": False}
    out = serialize_instance(session, inst)
    out["workflow_enabled"] = True
    return out


def _enforce_declaration(session, inst, request, action, current_user, declaration, payload):
    """Wymusza oświadczenie wnioskującego, gdy `action` kieruje wniosek do IT.

    Zwraca payload (ewentualnie wzbogacony o dane oświadczenia). Gdy oświadczenie
    jest wymagane, a nie dostarczone — HTTP 428 z treścią szablonu, żeby front
    pokazał modal i ponowił. Rekord `PermissionDeclaration` powstaje tu, przed
    `execute_action`; commit nastąpi dopiero po jego powodzeniu (spójna transakcja).
    """
    from datetime import datetime as _dt
    from services.workflow import landing_node_type, grants_permissions
    from services.declarations import create_declaration
    from routers.settings import effective_declaration_text
    from services.audit import record_event

    if action not in ("select", "approve"):
        return payload
    if landing_node_type(session, inst, request, action) != "it_execute":
        return payload
    if not grants_permissions(session, request):
        return payload

    if declaration is None or not (declaration.declared_by_name or "").strip() \
            or not (declaration.declared_date or "").strip():
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            {
                "code": "DECLARATION_REQUIRED",
                "message": "Wymagane oświadczenie wnioskującego przed skierowaniem "
                           "wniosku do realizacji IT.",
                "declaration_text": effective_declaration_text(session),
            },
        )

    approved_at = _dt.utcnow()
    text = effective_declaration_text(session)
    dec = create_declaration(
        session, request, current_user,
        declared_by_name=declaration.declared_by_name,
        declared_date=declaration.declared_date,
        declaration_text=text,
        approved_at=approved_at,
    )
    try:
        record_event(
            session, action="declaration.signed",
            user_id=current_user.id, username=current_user.username,
            target_type="access_request", target_id=request.id,
            details={"reference_code": dec.reference_code,
                     "worker_user_id": request.worker_user_id,
                     "declared_by_name": dec.declared_by_name},
            commit=False,
        )
    except Exception:
        pass
    # Dane oświadczenia trafiają do podpisanego payloadu kroku obiegu (łańcuch SHA256).
    return {
        **(payload or {}),
        "declaration_ref": dec.reference_code,
        "declared_by_name": dec.declared_by_name,
        "declared_date": dec.declared_date,
    }


@router.post("/{request_id}/workflow/action")
def workflow_action(
    request_id: int,
    data: WorkflowActionIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Wykonuje akcję na aktualnym węźle obiegu. Silnik przechodzi dalej."""
    from models import WorkflowInstance
    from services.workflow import execute_action, serialize_instance

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        raise HTTPException(400, "Wniosek nie ma podpiętego obiegu (starszy wniosek?).")

    # H4 — optymistyczna kontrola współbieżności. Jeśli klient przesłał węzeł,
    # na którym myśli że działa, a obieg zdążył przejść dalej (inny użytkownik
    # kliknął pierwszy) → odrzuć zamiast wykonać akcję na cudzym węźle.
    if data.expected_node_id and inst.current_node_id != data.expected_node_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Obieg zmienił stan (ktoś wykonał akcję w międzyczasie). Odśwież wniosek.")

    # Payload zależy od akcji.
    payload = None
    if data.action == "select":
        # Zastąp RequestItem tym co przyszło (kierownik uzupełnia koszyk).
        # Każda pozycja niesie własny kierunek (grant/revoke) — stan docelowy.
        _validate_items_scope(session, r.unit_id, data.items)
        rkind = getattr(r, "kind", "grant") or "grant"
        old = session.exec(select(RequestItem).where(RequestItem.request_id == r.id)).all()
        for it in old:
            session.delete(it)
        session.flush()
        for it in data.items:
            ik = it.kind if it.kind in ("grant", "revoke") else (
                "revoke" if rkind == "revoke" else "grant")
            session.add(RequestItem(
                request_id=r.id, system_id=it.system_id,
                permission_id=it.permission_id, kind=ik,
                custom_values=_clean_custom_values(session, it)))
        session.flush()
        payload = {"items": [{"system_id": it.system_id, "permission_id": it.permission_id,
                              "kind": (it.kind if it.kind in ("grant", "revoke")
                                       else ("revoke" if rkind == "revoke" else "grant")),
                              "custom_values": it.custom_values or {}}
                             for it in data.items]}
    elif data.action == "execute":
        payload = {"ad_username": data.ad_username} if data.ad_username else None

        # --- Pozycje dołożone przez IT ------------------------------------
        # WAŻNE: cała walidacja MUSI wykonać się PRZED _resolve_or_create_worker,
        # bo tamten helper robi commit w środku handlera — przy błędzie 400 po
        # nim zostałoby w bazie utworzone konto-widmo.
        added_payload = []
        if data.added_items:
            # Uzasadnienie jest obowiązkowe: IT rozszerza zakres poza to,
            # co zatwierdził kierownik — musi zostać ślad dlaczego.
            if not (data.comment or "").strip():
                raise HTTPException(
                    400,
                    "Dodanie uprawnień wymaga uzasadnienia — wpisz, dlaczego są "
                    "potrzebne (np. moduł wymaga zależnego dostępu).",
                )
            _validate_items_scope(session, r.unit_id, data.added_items)

            # Bez unikalności na (request_id, system_id, permission_id) w bazie
            # duplikat dałby zdublowane wiersze w podglądzie i PDF.
            have = {
                (it.system_id, it.permission_id)
                for it in session.exec(
                    select(RequestItem).where(RequestItem.request_id == r.id)
                ).all()
            }
            for it in data.added_items:
                key = (it.system_id, it.permission_id)
                if key in have:
                    sys_obj = session.get(PermissionSystem, it.system_id)
                    perm_obj = session.get(SystemPermission, it.permission_id)
                    raise HTTPException(
                        400,
                        f'Uprawnienie „{perm_obj.permission_name if perm_obj else it.permission_id}" '
                        f'({sys_obj.name if sys_obj else it.system_id}) jest już na wniosku.',
                    )
                have.add(key)

            for it in data.added_items:
                cleaned = _clean_custom_values(session, it)
                session.add(RequestItem(
                    request_id=r.id, system_id=it.system_id,
                    permission_id=it.permission_id, kind="grant",
                    custom_values=cleaned,
                    added_by_user_id=current_user.id))
                # Do śladu audytowego trafiają wartości PO czyszczeniu, żeby
                # podpisany payload zgadzał się z tym, co zapisano w bazie.
                added_payload.append({
                    "system_id": it.system_id,
                    "permission_id": it.permission_id,
                    "kind": "grant",
                    "custom_values": json.loads(cleaned) if cleaned else {},
                })
            session.flush()

            payload = {
                **(payload or {}),
                "added_items": added_payload,
                "justification": (data.comment or "").strip(),
            }

        # Dowiąż wniosek do konta pracownika (tworzy ghost-LDAP, jeśli trzeba) —
        # tak jak dawny /it-action. Dzięki temu pracownik od razu widzi swoje
        # uprawnienia w „Moje uprawnienia", a wniosek pojawia się w strukturze.
        if data.ad_username and data.ad_username.strip():
            worker = _resolve_or_create_worker(session, data.ad_username, r)
            r.worker_user_id = worker.id

    # Odmowa konkretnych pozycji — tylko kierownik nadrzędny (approve na
    # higher_manager_approve) albo IT (execute na it_execute). Uprawnienie do
    # samego węzła i tak zweryfikuje `can_act` w execute_action.
    if data.denials:
        from services.workflow import find_node as _find_node
        node = (_find_node(json.loads(inst.template_snapshot), inst.current_node_id)
                if inst.current_node_id else None)
        ntype = (node or {}).get("type")
        ok_combo = ((data.action == "approve" and ntype == "higher_manager_approve")
                    or (data.action == "execute" and ntype == "it_execute"))
        if not ok_combo:
            raise HTTPException(400,
                "Odmowa pozycji jest możliwa tylko przy zatwierdzaniu przez "
                "kierownika nadrzędnego albo realizacji przez IT.")
        want = {d.item_id: ((d.comment or "").strip() or None) for d in data.denials}
        rows = session.exec(
            select(RequestItem).where(RequestItem.request_id == r.id)
            .where(col(RequestItem.id).in_(list(want.keys())))
        ).all()
        missing = set(want.keys()) - {x.id for x in rows}
        if missing:
            raise HTTPException(400, "Część pozycji do odmowy nie należy do tego wniosku.")
        for x in rows:
            x.denied = True
            x.deny_comment = want[x.id]
            x.denied_by_user_id = current_user.id
            x.denied_at = datetime.utcnow()
            x.fulfilled = False
            x.fulfilled_by_user_id = None
            x.fulfilled_at = None
            session.add(x)
        session.flush()

    # Zamknięcie realizacji przez IT (execute na it_execute) — każda pozycja
    # NADANIA, która nie została odmówiona, zostaje odhaczona jako zrealizowana.
    # Dzięki temu po częściowej/etapowej pracy stan końcowy jest spójny
    # (wszystko „zrealizowano" albo „odmówiono"), a rejestr i audyt się zgadzają.
    if data.action == "execute":
        now = datetime.utcnow()
        for x in session.exec(
            select(RequestItem).where(RequestItem.request_id == r.id)
            .where(col(RequestItem.denied) == False)  # noqa: E712
            .where((col(RequestItem.kind) == "grant") | (col(RequestItem.kind).is_(None)))
        ).all():
            if not x.fulfilled:
                x.fulfilled = True
                x.fulfilled_by_user_id = current_user.id
                x.fulfilled_at = now
                session.add(x)
        session.flush()

    # Oświadczenie wnioskującego — gdy TA akcja kieruje wniosek do IT i wniosek
    # nadaje uprawnienia. Brak → 428; jest → zapis + dopisanie do payloadu kroku.
    payload = _enforce_declaration(
        session, inst, r, data.action, current_user, data.declaration, payload)

    execute_action(session, inst, r, current_user, data.action,
                   payload=payload, comment=data.comment)
    try:
        session.commit()
    except IntegrityError:
        # H4 — wyścig: równoległa akcja zapisała już krok o tym samym indeksie
        # (UNIQUE(instance_id, step_index)). Nie dublujemy obiegu.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Obieg zmienił stan (równoległa akcja). Odśwież wniosek.")
    session.refresh(inst); session.refresh(r)
    out = serialize_instance(session, inst)
    out["workflow_enabled"] = True
    return out


class ItemDenyIn(BaseModel):
    denied: bool = True              # True = odmów, False = cofnij odmowę
    comment: Optional[str] = None


@router.post("/{request_id}/items/{item_id}/deny")
def set_item_denial(
    request_id: int,
    item_id: int,
    data: ItemDenyIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Zapisuje (albo cofa) odmowę POJEDYNCZEJ pozycji od ręki — bez kończenia
    całego wniosku. Dzięki temu kierownik nadrzędny / realizator IT widzi od
    razu, że odmowa się zapisała (badge „odmówiono"). Dozwolone tylko na węźle,
    na którym ta osoba faktycznie może działać (higher_manager_approve /
    it_execute) — reguły jak w `workflow_action`."""
    from models import WorkflowInstance
    from services.audit import record_event
    from services.workflow import can_act, find_node

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    item = session.get(RequestItem, item_id)
    if not item or item.request_id != request_id:
        raise HTTPException(404, "Pozycja nie należy do tego wniosku.")

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst or not inst.current_node_id:
        raise HTTPException(400, "Wniosek nie ma aktywnego obiegu.")

    node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
    ntype = (node or {}).get("type")
    if ntype not in ("higher_manager_approve", "it_execute"):
        raise HTTPException(400,
            "Odmowa pozycji jest możliwa tylko przy zatwierdzaniu przez "
            "kierownika nadrzędnego albo realizacji przez IT.")

    dept = session.get(Department, r.department_id) if r.department_id else None
    ok, reason = can_act(node, r, dept, current_user, session)
    if not ok:
        raise HTTPException(403, reason or "Brak uprawnień do działania na tym etapie.")

    # Odmówić można tylko pozycji nadania — odebranie samo w sobie nic nie nadaje.
    if (getattr(item, "kind", "grant") or "grant") == "revoke":
        raise HTTPException(400, "Odmówić można tylko pozycji nadania uprawnienia.")

    if data.denied:
        item.denied = True
        item.deny_comment = (data.comment or "").strip() or None
        item.denied_by_user_id = current_user.id
        item.denied_at = datetime.utcnow()
        # Odmowa i „zrealizowano" wykluczają się — czyścimy ewentualne odhaczenie.
        item.fulfilled = False
        item.fulfilled_by_user_id = None
        item.fulfilled_at = None
        ev = "request_item.denied"
    else:
        item.denied = False
        item.deny_comment = None
        item.denied_by_user_id = None
        item.denied_at = None
        ev = "request_item.deny_revoked"
    session.add(item)

    try:
        perm_obj = session.get(SystemPermission, item.permission_id)
        sys_obj = session.get(PermissionSystem, item.system_id)
        record_event(
            session, action=ev,
            user_id=current_user.id, username=current_user.username,
            target_type="request_item", target_id=item.id,
            details={"request_id": request_id,
                     "permission": perm_obj.permission_name if perm_obj else item.permission_id,
                     "system": sys_obj.name if sys_obj else item.system_id,
                     "comment": item.deny_comment},
            commit=False,
        )
    except Exception:
        pass

    session.commit()
    updated = next((x for x in _get_items(session, request_id) if x["id"] == item_id), None)
    return {"item": updated}


class ItemFulfillIn(BaseModel):
    fulfilled: bool = True           # True = odhacz jako zrobione, False = cofnij


@router.post("/{request_id}/items/{item_id}/fulfill")
def set_item_fulfilled(
    request_id: int,
    item_id: int,
    data: ItemFulfillIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Odhacza (albo cofa) realizację POJEDYNCZEJ pozycji przez IT — praca
    etapowa. Zapis w bazie OD RAZU, zanim zamknie się cały wniosek, żeby IT
    mogło realizować wniosek częściami i widziało, co już zrobione. Dozwolone
    tylko na węźle `it_execute` i tylko dla osoby, która może tam działać."""
    from models import WorkflowInstance
    from services.audit import record_event
    from services.workflow import can_act, find_node

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    item = session.get(RequestItem, item_id)
    if not item or item.request_id != request_id:
        raise HTTPException(404, "Pozycja nie należy do tego wniosku.")

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst or not inst.current_node_id:
        raise HTTPException(400, "Wniosek nie ma aktywnego obiegu.")

    node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
    ntype = (node or {}).get("type")
    if ntype != "it_execute":
        raise HTTPException(400,
            "Odhaczanie realizacji pozycji jest możliwe tylko na etapie "
            "realizacji przez IT.")

    dept = session.get(Department, r.department_id) if r.department_id else None
    ok, reason = can_act(node, r, dept, current_user, session)
    if not ok:
        raise HTTPException(403, reason or "Brak uprawnień do działania na tym etapie.")

    if data.fulfilled and getattr(item, "denied", False):
        raise HTTPException(400,
            "Ta pozycja jest odmówiona — najpierw cofnij odmowę, aby ją zrealizować.")

    if data.fulfilled:
        item.fulfilled = True
        item.fulfilled_by_user_id = current_user.id
        item.fulfilled_at = datetime.utcnow()
        ev = "request_item.fulfilled"
    else:
        item.fulfilled = False
        item.fulfilled_by_user_id = None
        item.fulfilled_at = None
        ev = "request_item.fulfill_revoked"
    session.add(item)

    try:
        perm_obj = session.get(SystemPermission, item.permission_id)
        sys_obj = session.get(PermissionSystem, item.system_id)
        record_event(
            session, action=ev,
            user_id=current_user.id, username=current_user.username,
            target_type="request_item", target_id=item.id,
            details={"request_id": request_id,
                     "permission": perm_obj.permission_name if perm_obj else item.permission_id,
                     "system": sys_obj.name if sys_obj else item.system_id},
            commit=False,
        )
    except Exception:
        pass

    session.commit()
    updated = next((x for x in _get_items(session, request_id) if x["id"] == item_id), None)
    return {"item": updated}


@router.get("/{request_id}/workflow/verify")
def verify_workflow_chain(
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Weryfikuje łańcuch podpisów kroków. Dla audytora / superadmina."""
    from models import WorkflowInstance
    from services.workflow import verify_chain

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        return {"workflow_enabled": False, "chain_valid": None}
    return {"workflow_enabled": True, "chain_valid": verify_chain(session, inst.id)}


@router.get("/{request_id}/workflow/pdf")
def download_workflow_pdf(
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Pobierz PDF wniosku do podpisu odręcznego. Zaznacza pending_pdf_at,
    odblokowując checkbox potwierdzenia EZD FINN w UI.
    """
    from models import SIGNATURE_REQUIRED_NODE_TYPES, WorkflowInstance
    from services.pdf_generator import generate_request_pdf
    from services.workflow import can_act, find_node
    import json as _json

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        raise HTTPException(400, "Wniosek nie ma podpiętego obiegu.")
    if inst.status != "active" and str(inst.status) != "active":
        # Enum vs str — obsłuż oba przypadki
        s = inst.status.value if hasattr(inst.status, "value") else inst.status
        if s != "active":
            raise HTTPException(400, f"Instancja w stanie {s} — brak akcji.")

    graph = _json.loads(inst.template_snapshot)
    node = find_node(graph, inst.current_node_id) if inst.current_node_id else None
    if not node:
        raise HTTPException(400, "Brak bieżącego węzła.")
    if node["type"] not in SIGNATURE_REQUIRED_NODE_TYPES:
        raise HTTPException(400, "Bieżący węzeł nie wymaga podpisu.")

    dept = session.get(Department, r.department_id) if r.department_id else None
    allowed, reason = can_act(node, r, dept, current_user, session)
    if not allowed:
        raise HTTPException(403, reason)

    try:
        pdf_bytes = generate_request_pdf(session, r)
    except Exception as exc:
        raise HTTPException(500, f"Błąd generowania PDF: {exc}")

    # Zaznacz że PDF został pobrany. Reset przy advance() → nowy węzeł = nowy cykl.
    inst.pending_pdf_at = datetime.utcnow()
    inst.pending_pdf_by_user_id = current_user.id
    session.add(inst); session.commit()

    filename = f"wniosek-{r.id}-do-podpisu.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class EzdConfirmIn(BaseModel):
    confirmed: bool = True


@router.post("/{request_id}/workflow/ezd-confirm")
def confirm_ezd_sent(
    request_id: int,
    data: EzdConfirmIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Kierownik potwierdza że podpisany wniosek został wysłany EZD FINN
    do Biura Informatyki. Dopiero po tym odblokowuje się „Akceptuj".
    """
    from models import SIGNATURE_REQUIRED_NODE_TYPES, WorkflowInstance
    from services.workflow import can_act, find_node, serialize_instance
    import json as _json

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        raise HTTPException(400, "Wniosek nie ma podpiętego obiegu.")

    graph = _json.loads(inst.template_snapshot)
    node = find_node(graph, inst.current_node_id) if inst.current_node_id else None
    if not node:
        raise HTTPException(400, "Brak bieżącego węzła.")
    if node["type"] not in SIGNATURE_REQUIRED_NODE_TYPES:
        raise HTTPException(400, "Bieżący węzeł nie wymaga potwierdzenia EZD.")

    dept = session.get(Department, r.department_id) if r.department_id else None
    allowed, reason = can_act(node, r, dept, current_user, session)
    if not allowed:
        raise HTTPException(403, reason)

    if data.confirmed and not inst.pending_pdf_at:
        raise HTTPException(400,
            "Najpierw pobierz PDF do podpisu — dopiero potem możesz potwierdzić wysyłkę EZD.")

    inst.pending_ezd_confirmed = bool(data.confirmed)
    inst.pending_ezd_by_user_id = current_user.id if data.confirmed else None
    session.add(inst); session.commit(); session.refresh(inst)
    out = serialize_instance(session, inst)
    out["workflow_enabled"] = True
    return out
