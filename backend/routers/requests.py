"""
Router: Wnioski o uprawnienia — workflow PENDING_MANAGER → PENDING_IT → COMPLETED/REJECTED.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    require_it_staff,
    is_admin, managed_dept_ids, hr_scoped_unit_ids, unit_manager_dept_ids, manager_scope,
    manager_scope_ids,
)

_log = logging.getLogger("szup.requests")


# ---------------------------------------------------------------------------
# Helpers — role i widoczność
# ---------------------------------------------------------------------------

# Komunikat, gdy krok wykonała już inna osoba (np. przełożony) — 409.
STEP_ALREADY_DONE_MSG = ("Ten krok został już wykonany przez inną osobę (np. przełożonego) "
                         "albo wniosek jest zakończony. Odśwież wniosek.")


def _managed_dept_ids(session: Session, user: User) -> tuple[list[int], list[int]]:
    """Zakres wniosków kierownika (z komórkami przełożonego) — patrz
    services.permissions.manager_scope (cache na czas żądania)."""
    return manager_scope(session, user)


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


def _clean_custom_values(session: Session, item, *, allow_incomplete: bool = False) -> Optional[str]:
    """Zwaliduj i zserializuj wartość kontrolki JEDNEJ pozycji wniosku.

    Kontrolka (lista wyboru albo pole do wpisania) jest cechą KONKRETNEGO
    uprawnienia, nie całego oprogramowania: obok pozycji z importu, które są
    zwykłymi checkboxami, mogą stać pozycje dodane ręcznie przez IT, które
    doprecyzowuje się listą albo tekstem.

    Wartość trzymamy dalej w `RequestItem.custom_values` jako mapę
    nazwa→wartość — dzięki temu podgląd wniosku, rejestr i „Moje uprawnienia"
    działają bez zmian, a wartości zapisane wcześniej (gdy pola definiowano przy
    programie) pozostają czytelne.

    `allow_incomplete=True` (wersja robocza kierownika) — brak wartości pola
    obowiązkowego nie jest błędem; zostanie sprawdzony przy wysłaniu wniosku.
    Niedozwolone wartości z listy są odrzucane zawsze.
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
    if allow_incomplete:
        required = False

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


def _item_kind_for(item, request_kind: str) -> str:
    """Kierunek pozycji z formularza: własny (grant/revoke), a gdy brak — kierunek wniosku."""
    if item.kind in ("grant", "revoke"):
        return item.kind
    return "revoke" if request_kind == "revoke" else "grant"


def _replace_request_items(session: Session, r: AccessRequest, items, *,
                           allow_incomplete: bool = False) -> list[dict]:
    """Zastąp pozycje wniosku dokładnie tym, co przyszło z formularza kierownika
    (akcja „select" i zapis wersji roboczej). Każda pozycja niesie własny
    kierunek (grant/revoke) — stan docelowy. Waliduje zakres systemów
    i wartości kontrolek; zwraca listę pozycji do payloadu kroku / audytu.
    Tylko flush — commit robi wywołujący."""
    _validate_items_scope(session, r.unit_id, items)
    rkind = getattr(r, "kind", "grant") or "grant"
    # Najpierw walidacja wartości (bez zmian w bazie), dopiero potem podmiana.
    cleaned = [_clean_custom_values(session, it, allow_incomplete=allow_incomplete)
               for it in items]
    for old in session.exec(select(RequestItem).where(RequestItem.request_id == r.id)).all():
        session.delete(old)
    session.flush()
    for it, cv in zip(items, cleaned):
        session.add(RequestItem(
            request_id=r.id, system_id=it.system_id,
            permission_id=it.permission_id, kind=_item_kind_for(it, rkind),
            custom_values=cv))
    session.flush()
    return [{"system_id": it.system_id, "permission_id": it.permission_id,
             "kind": _item_kind_for(it, rkind),
             "custom_values": it.custom_values or {}}
            for it in items]


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
    # Typ wniosku — OBOWIĄZKOWY (brak → 400). Pole zostaje Optional w schemacie,
    # żeby zamiast ogólnego 422 zwrócić czytelny komunikat po polsku.
    request_type_id: Optional[int] = None
    # Oświadczenie wnioskującego — wymagane, gdy złożenie wniosku od razu
    # kieruje go do IT (kierownik składa i sam zatwierdza wybór w 1-stopniu).
    declaration: Optional[DeclarationIn] = None
    # „Zapisz roboczy" kierownika komórki: wniosek powstaje z pozycjami, ale BEZ
    # automatycznego wyboru — zostaje u kierownika jako wersja robocza.
    draft: bool = False


class DraftSaveIn(BaseModel):
    """Zapis wersji roboczej na etapie kierownika komórki (bez przesuwania obiegu).

    Na kroku wyboru uprawnień zapisuje pozycje i uwagi, na kroku akceptacji
    (`manager_approve`) — tylko uwagi (pozycje zostają bez zmian)."""
    items: list[RequestItemSchema] = []
    comment: Optional[str] = None
    # Pusta lista pozycji na wniosku, który ma już pozycje (np. wpisane przez
    # kadry), usunęłaby je — wymaga świadomego potwierdzenia (jak przy „select").
    allow_empty: bool = False
    # Optymistyczna kontrola współbieżności — węzeł, na którym klient zapisuje
    # wersję roboczą. Gdy obieg poszedł dalej albo wniosek przejęto → 409.
    expected_node_id: Optional[str] = None


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
    # Akcja "select" z PUSTĄ listą `items` na wniosku, który ma już pozycje
    # (np. wpisane przez kadry), usunęłaby je wszystkie. Domyślnie → 400;
    # front musi świadomie potwierdzić „wniosek bez pozycji" (allow_empty=true).
    allow_empty: bool = False
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
    step_since = None      # kiedy wniosek wszedł w bieżący krok (ISO) — tylko aktywny obieg
    waiting_for = None     # kto ma teraz działać (opis) — tylko aktywny obieg
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
        preloaded = session.info.get("_wf_inst_by_req")
        if preloaded is not None and r.id in preloaded:
            inst = preloaded[r.id]
        else:
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
                # v3.1 — „Czeka na: kto, od kiedy” (od wejścia w bieżący krok).
                from services.workflow import (
                    find_node, waiting_for_label, current_step_since,
                )
                try:
                    cur_node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
                except Exception:
                    cur_node = None
                # Zapamiętaj instancję i węzeł — list_requests użyje ich ponownie
                # (can_act) zamiast drugi raz pobierać instancję i parsować graf.
                session.info.setdefault("_wf_rows", {})[r.id] = (inst, cur_node)
                try:
                    waiting_for = waiting_for_label(
                        session, cur_node, r,
                        session.get(Department, r.department_id) if r.department_id else None)
                    since = current_step_since(session, inst)
                    step_since = since.isoformat() if since else None
                except Exception:   # informacja pomocnicza — nie może wywrócić listy
                    waiting_for = step_since = None
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
        "step_since": step_since,
        "waiting_for": waiting_for,
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
        # Wersja robocza kierownika i przejęcie przez przełożonego (historia
        # zostaje także po przejściu etapu kierownika).
        "draft_saved_at": (r.draft_saved_at.isoformat()
                           if getattr(r, "draft_saved_at", None) else None),
        "taken_over_by_id": getattr(r, "taken_over_by_id", None),
        "taken_over_by_name": getattr(r, "taken_over_by_name", None),
        "taken_over_at": (r.taken_over_at.isoformat()
                          if getattr(r, "taken_over_at", None) else None),
        "items": items,
    }


def _get_items(session: Session, request_id: int, preloaded: Optional[list] = None) -> list:
    """Pozycje wniosku do odpowiedzi API. `preloaded` — pozycje wczytane hurtem
    (lista wniosków), żeby nie odpytywać bazy osobno dla każdego wniosku."""
    items = (preloaded if preloaded is not None else
             session.exec(select(RequestItem).where(RequestItem.request_id == request_id)).all())
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


def _preload_for_requests(session: Session, rows: list) -> dict[int, list]:
    """Wczytaj hurtem dane potrzebne do serializacji listy wniosków (N+1).

    - pozycje wszystkich wniosków jednym zapytaniem (zwracamy mapę id → pozycje),
    - instancje obiegu (do `session.info["_wf_inst_by_req"]`; brak instancji = None),
    - komórki, jednostki, systemy, uprawnienia i konta użytkowników — trafiają do
      mapy tożsamości sesji, więc kolejne `session.get` nie odpytują bazy.
    Tylko odczyt; nic nie zmienia w danych.
    """
    from models import WorkflowInstance
    ids = [r.id for r in rows]
    if not ids:
        return {}
    items = session.exec(select(RequestItem).where(col(RequestItem.request_id).in_(ids))
                         .order_by(col(RequestItem.id))).all()
    by_req: dict[int, list] = {}
    for it in items:
        by_req.setdefault(it.request_id, []).append(it)

    inst_map: dict[int, object] = {i: None for i in ids}
    for inst in session.exec(
        select(WorkflowInstance).where(col(WorkflowInstance.request_id).in_(ids))
    ).all():
        if inst_map.get(inst.request_id) is None:
            inst_map[inst.request_id] = inst
    session.info.setdefault("_wf_inst_by_req", {}).update(inst_map)

    def _load(model, keys):
        keys = {k for k in keys if k}
        if keys:
            session.exec(select(model).where(col(model.id).in_(list(keys)))).all()

    _load(Department, (r.department_id for r in rows))
    _load(Unit, (r.unit_id for r in rows))
    _load(PermissionSystem, (it.system_id for it in items))
    _load(SystemPermission, (it.permission_id for it in items))
    _load(User, [*(r.worker_user_id for r in rows),
                 *(getattr(r, "assigned_to_user_id", None) for r in rows),
                 *(getattr(it, "added_by_user_id", None) for it in items),
                 *(getattr(it, "denied_by_user_id", None) for it in items),
                 *(getattr(it, "fulfilled_by_user_id", None) for it in items)])
    return by_req


def _attach_node_info(session: Session, out: list[dict], rows: list, user: User) -> None:
    """Dopisz do zserializowanych wniosków `current_node_type` (typ bieżącego
    węzła aktywnego obiegu albo None), `can_act` (czy `user` może na nim działać),
    `next_node_type` (typ węzła, na który trafi wniosek po wysłaniu bieżącego
    kroku — z pominięciami silnika, np. „it_execute” albo „higher_manager_approve”)
    oraz informacje o etapie kierownika komórki: `manager_stage` (etap roboczy
    komórki z własnym kierownikiem), `is_draft` (jest zapisana wersja robocza),
    `can_take_over` (czy `user` może wniosek przejąć jako przełożony)
    i `can_release` (czy `user` może oddać przejęcie).

    Przejęcie, które wygasło (przejmujący nieaktywny albo nie jest już
    przełożonym), na etapie kierownika jest pokazywane jako brak przejęcia."""
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import (
        can_act, find_node, is_manager_stage, can_take_over, can_release,
        effective_taker_id, landing_node_type,
    )
    by_id = {r.id: r for r in rows}
    cached = session.info.get("_wf_rows", {})
    preloaded = session.info.get("_wf_inst_by_req", {})
    for row in out:
        r = by_id[row["id"]]
        node_type, act = None, False
        stage, take, release, next_type = False, False, False, None
        if r.id in cached:
            # Instancja i węzeł już wczytane w _serialize_request.
            inst, node = cached[r.id]
        else:
            if r.id in preloaded:
                inst = preloaded[r.id]
            else:
                inst = session.exec(
                    select(WorkflowInstance).where(WorkflowInstance.request_id == r.id)
                ).first()
            node = None
            if inst and inst.status == WorkflowInstanceStatus.active and inst.current_node_id:
                try:
                    node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
                except Exception:
                    node = None
        if inst and inst.status == WorkflowInstanceStatus.active and inst.current_node_id:
            if node:
                node_type = node.get("type")
                dept = session.get(Department, r.department_id) if r.department_id else None
                allowed, _reason = can_act(node, r, dept, user, session)
                act = bool(allowed)
                stage = is_manager_stage(session, node_type, dept)
                try:
                    next_type = landing_node_type(session, inst, r, "approve")
                except Exception:   # podpowiedź dla etykiety — nie może wywrócić listy
                    next_type = None
                if stage:
                    take = can_take_over(session, r, user, node_type, dept)[0]
                    release = can_release(session, r, user, node_type, dept)
                    if r.taken_over_by_id and not effective_taker_id(session, r, dept):
                        row["taken_over_by_id"] = None
                        row["taken_over_by_name"] = None
                        row["taken_over_at"] = None
        row["current_node_type"] = node_type
        row["next_node_type"] = next_type
        row["can_act"] = act
        row["manager_stage"] = stage
        row["is_draft"] = bool(stage and getattr(r, "draft_saved_at", None))
        row["can_take_over"] = take
        row["can_release"] = release


def _item_kind(item, request_kind: str) -> str:
    """Kierunek pozycji: własny, a gdy brak (stare rekordy) — kierunek wniosku."""
    k = getattr(item, "kind", None)
    if k in ("grant", "revoke"):
        return k
    return "revoke" if request_kind == "revoke" else "grant"


def _resolve_or_create_worker(
    session: Session, ad_username: str, req: AccessRequest, *,
    fill_department: bool = True,
) -> User:
    """
    Znajduje konto po sAMAccountName (username) lub tworzy nowe „ghost" konto
    typu LDAP z danymi z wniosku. Login jest normalizowany jak przy logowaniu
    i imporcie z AD („DOMENA\\jan” → „jan”). Uzupełnia puste imię i e-mail,
    a gdy `fill_department` — także pustą komórkę istniejącego konta.
    Nie zmienia konta lokalnego (admin/superadmin) — rzuca 400.
    """
    from services.ldap_service import normalize_login, is_valid_login, find_user_by_login
    uname = normalize_login(ad_username)
    if not uname:
        raise HTTPException(400, "Podaj nazwę konta AD (sAMAccountName) pracownika")
    if not is_valid_login(uname):
        raise HTTPException(400, f'Login „{uname}" zawiera niedozwolone znaki — '
                                 f'wpisz sAMAccountName pracownika.')

    # Porównanie bez względu na wielkość liter (stare konta mogą mieć wielkie litery).
    existing = find_user_by_login(session, uname)

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
        if fill_department and not existing.department_id and req.department_id:
            existing.department_id = req.department_id; changed = True
        if changed:
            # flush, nie commit — całość akcji (krok obiegu, pozycje, konto)
            # zatwierdza wywołujący jedną transakcją.
            session.add(existing); session.flush()
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
    session.add(new_user); session.flush()   # nadaje id; commit robi wywołujący
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
    active: bool = Query(False, description="true = tylko wnioski w toku (bez zakończonych/odrzuconych)"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(AccessRequest)

    # Perspektywa "mine" — wyłącznie wnioski, które TEN użytkownik złożył
    # (np. kierownik wnioskujący dla swoich pracowników). Działa dla każdej roli.
    if scope == "mine":
        stmt = stmt.where(AccessRequest.created_by_id == current_user.id)
    # Perspektywa "manager" — ZAWSZE zawężamy do wydziałów, którymi user kieruje
    # (także jako przełożony), nawet jeśli ma dodatkowo rolę it_staff.
    # Admin/superadmin widzi wszystko (poza ukrytym etapem kierownika — niżej).
    elif scope == "manager" and not is_admin(current_user):
        if not has_role(current_user, "manager"):
            return []
        direct_ids, escalated_ids = _managed_dept_ids(session, current_user)
        all_ids = list({*direct_ids, *escalated_ids})
        if not all_ids:
            return []
        stmt = stmt.where(col(AccessRequest.department_id).in_(all_ids))
    elif is_admin(current_user) or has_role(current_user, "it_staff"):
        pass  # widzą wszystko (IT — kolejka realizacji; admin wszędzie)
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
    if active:
        # „Do obsługi” — bez historii; inaczej limit 200 najnowszych mógł wyciąć
        # najstarszy oczekujący wniosek (widoczny na pulpicie).
        stmt = stmt.where(col(AccessRequest.status).notin_(
            [RequestStatus.completed, RequestStatus.rejected]))

    # Wnioski na etapie kierownika komórki (wersja robocza) „nie istnieją" dla
    # osób spoza kręgu kierownika — także dla IT i administratora. Wycinamy je
    # już w SQL (ten sam warunek co `can_view_request`), żeby LIMIT/OFFSET
    # liczyły tylko widoczne wiersze.
    from services.workflow import manager_stage_hidden_clause
    hidden = manager_stage_hidden_clause(session, current_user)
    if hidden is not None:
        stmt = stmt.where(hidden)

    stmt = stmt.order_by(col(AccessRequest.created_at).desc(),
                         col(AccessRequest.id).desc()).limit(limit).offset(offset)
    rows = session.exec(stmt).all()
    items_by_req = _preload_for_requests(session, rows)
    out = [_serialize_request(r, _get_items(session, r.id, items_by_req.get(r.id, [])), session)
           for r in rows]

    # Dołącz informację o bieżącym węźle obiegu i o tym, czy TEN użytkownik może
    # na nim działać — w każdej perspektywie (także bez `scope`, z której korzysta
    # wyszukiwarka globalna). Dzięki temu panel rozdziela wnioski „do obsługi"
    # (can_act) od „w realizacji" (it_execute), a wyszukiwarka trafia do
    # właściwej zakładki.
    _attach_node_info(session, out, rows, current_user)
    return out


@router.get("/dashboard")
def workflow_dashboard(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Pulpit obiegu wniosków bieżącego użytkownika: liczniki kolejek
    (do przypisania / akceptacji / realizacji) + powiadomienia o wnioskach
    czekających na jego działanie."""
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import can_act, find_node, waiting_for_label, current_step_since
    import json as _json

    def _entry(r: AccessRequest) -> Optional[dict]:
        """Zwraca wpis kolejki, jeśli bieżący użytkownik może działać na
        aktualnym węźle obiegu tego wniosku; inaczej None."""
        # Brak w mapie aktywnych = brak aktywnego obiegu (nie ma na czym działać).
        inst = inst_by_req.get(r.id)
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
        since = current_step_since(session, inst)
        return {
            "request_id": r.id,
            "worker_name": r.worker_name,
            "dept_id": r.department_id,
            "dept_name": dept.name if dept else None,
            "dept_description": dept.description if dept else None,
            "node_label": node.get("label") or node.get("type"),
            "node_type": node.get("type"),
            "created_at": r.created_at,
            # v3.1 — od kiedy czeka na bieżącym kroku i na kogo.
            "step_since": since,
            "waiting_for": waiting_for_label(session, node, r, dept),
        }

    pending: list[dict] = []
    seen_ids: set[int] = set()
    # Aktywne instancje obiegu wczytane JEDNYM zapytaniem (zamiast osobnego
    # zapytania dla każdego wniosku w pętlach poniżej).
    inst_by_req: dict[int, WorkflowInstance] = {
        i.request_id: i for i in session.exec(
            select(WorkflowInstance)
            .where(WorkflowInstance.status == WorkflowInstanceStatus.active)
        ).all()
    }

    # 1) Perspektywa kierownika — wnioski z komórek, którymi zarządza
    #    (także jako przełożony / dyrektor jednostki).
    direct_ids, escalated_ids = _managed_dept_ids(session, user)
    all_managed = set(direct_ids) | set(escalated_ids)
    if all_managed:
        for r in session.exec(
            select(AccessRequest)
            .where(AccessRequest.department_id.in_(all_managed))
            # tylko wnioski w toku — zakończone/odrzucone nie mają aktywnego kroku
            .where(col(AccessRequest.status).notin_([RequestStatus.completed, RequestStatus.rejected]))
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

    # Najdłużej czekające na bieżącym kroku najpierw — sortujemy PRZED obcięciem
    # listy, żeby najstarsze sprawy nie wypadały z pulpitu.
    pending.sort(key=lambda p: p["step_since"] or p["created_at"])
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
        "pending_approvals_list":  pending[:50],
        # Flagi widoczności kafelków KPI — kafelek pokazujemy tylko roli,
        # której kolejka faktycznie dotyczy:
        #  - przypisanie uprawnień: każdy kierownik (zarządza jakąś komórką),
        #  - akceptacja: TYLKO kierownik wyższego rzędu (ma podrzędne komórki
        #    2-stopniowe) — kierownik I stopnia nie akceptuje,
        #  - realizacja: tylko pracownik IT.
        "show_prepare": bool(all_managed),
        # Z ORYGINALNYCH komórek 2-stopniowych (bez komórek „przełożonego”,
        # które ma każdy kierownik z podkomórkami) + gdy w kolejce są akceptacje.
        "show_approve": bool(managed_dept_ids(session, user)[1]) or pending_approve > 0,
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
    out = _serialize_request(r, _get_items(session, r.id), session)
    _attach_node_info(session, [out], [r], current_user)
    return out


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
    # Wnioski idą WYŁĄCZNIE przez silnik obiegu. Dawna ścieżka bez typu wniosku
    # tworzyła wniosek bez instancji obiegu (ślepy zaułek: każda akcja → 400),
    # gubiła kierunek pozycji i wartości pól — dlatego typ jest obowiązkowy.
    if data.request_type_id is None:
        raise HTTPException(400,
            "Wybierz typ wniosku — bez niego wniosku nie można skierować do obiegu.")
    if not session.get(Unit, data.unit_id):
        raise HTTPException(400, "Jednostka nie istnieje")
    dept = session.get(Department, data.department_id)
    if not dept:
        raise HTTPException(400, "Wydział nie istnieje")
    # Jednostka musi być jednostką komórki — od niej zależą zakres kadr (HR)
    # i dostępność systemów, więc niezgodna para obchodziłaby oba ograniczenia.
    if dept.unit_id != data.unit_id:
        raise HTTPException(400, "Wskazana komórka nie należy do wybranej jednostki.")

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

    # M3 — scoping wnioskodawcy:
    #  - kierownik (bez HR) może składać dla komórek ze SWOJEGO zakresu — ten sam
    #    zakres co `can_act`/wyszukiwarka (poddrzewo przełożonego + komórki
    #    jednostki, którą kieruje), żeby nie odmawiać złożenia wniosku dla
    #    osoby, na której wniosku ten kierownik i tak może wykonać każdy krok,
    #  - pracownik HR — tylko dla przypisanych mu jednostek.
    # Superadmin (break-glass) — bez ograniczeń.
    if not has_role(current_user, "superadmin"):
        from services.permissions import user_is_hr
        hr_cap = user_is_hr(session, current_user)
        if has_role(current_user, "manager") and not hr_cap:
            scope_ids = manager_scope_ids(session, current_user) | set(
                unit_manager_dept_ids(session, current_user))
            if data.department_id not in scope_ids:
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
    # Przełożony (kierownik / zastępca komórki wyżej, dyrektor jednostki) składa
    # wniosek dla podległej komórki z własnym kierownikiem — od razu go
    # „przejmuje”: może zapisać wersję roboczą i sam wykonać krok kierownika,
    # a kierownik komórki widzi wniosek jako przejęty (bez e-maila o wyborze).
    from services.workflow import dept_has_own_manager
    from services.permissions import is_department_manager_or_deputy, is_superior_for
    superior_creator = (
        not has_role(current_user, "superadmin")
        and dept_has_own_manager(session, dept)
        and not is_department_manager_or_deputy(session, current_user, dept)
        and is_superior_for(session, current_user, dept, include_self=False))
    if superior_creator:
        req.taken_over_by_id = current_user.id
        req.taken_over_by_name = current_user.full_name or current_user.username
        req.taken_over_at = datetime.utcnow()

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
                    custom_values=_clean_custom_values(
                        session, item, allow_incomplete=data.draft)))
            session.flush()

        start_instance(session, req, tpl)
        session.flush()

        if superior_creator:
            _finish_creation_take_over(session, req, current_user)
        if data.draft:
            _save_initial_draft(session, req, dept, current_user)
        # Jeśli wniosek składa osoba, która i tak wykonywałaby krok kierownika
        # komórki (kierownik/zastępca, przełożony po przejęciu) i podała już
        # pozycje — zaliczamy ten krok automatycznie. Inaczej musiałaby
        # zatwierdzać własny wniosek drugi raz. Krok trafia do śladu audytowego
        # z nią jako aktorem, a obieg idzie od razu dalej (wyższy rząd albo IT).
        if data.items and not data.draft:
            _auto_manager_steps(session, req, dept, current_user, data, kind)

        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        _log.exception("create_request (workflow) — błąd tworzenia wniosku")
        raise HTTPException(500, "Nie udało się utworzyć wniosku (błąd obiegu).")
    session.refresh(req)

    out = _serialize_request(req, _get_items(session, req.id), session)
    _attach_node_info(session, [out], [req], current_user)
    return out


def _current_node(session: Session, req: AccessRequest):
    """(instancja, bieżący węzeł) aktywnego obiegu wniosku albo (instancja|None, None)."""
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import find_node
    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == req.id)
    ).first()
    node = None
    if inst and inst.status == WorkflowInstanceStatus.active and inst.current_node_id:
        try:
            node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
        except Exception:
            node = None
    return inst, node


def _discard_stage_mail(session: Session, request_id: int, node_type: str) -> None:
    """Usuń z kolejki po-commitowej e-mail „wniosek czeka na Ciebie” dla
    węzła `node_type` — gdy krok wykonał/przejął sam składający."""
    from services.after_commit import discard_jobs
    from services.email_alerts import notify_workflow_stage
    discard_jobs(session, lambda fn, kw: (
        fn is notify_workflow_stage
        and kw.get("request_id") == request_id
        and kw.get("node_type") == node_type))


def _finish_creation_take_over(session: Session, req: AccessRequest, user: User) -> None:
    """Dokończ przejęcie ustawione przy składaniu wniosku przez przełożonego.

    Gdy obieg zaczyna się od kroku kierownika komórki — zostaje przejęty
    (zdarzenie w historii, bez e-maila do kierownika komórki o wyborze).
    W przeciwnym razie (szablon bez etapu kierownika) przejęcie nie ma sensu
    i jest czyszczone."""
    from services.workflow import MANAGER_STAGE_TYPES, clear_take_over, record_request_event
    from services.audit import record_event
    _inst, node = _current_node(session, req)
    ntype = (node or {}).get("type")
    if ntype not in MANAGER_STAGE_TYPES:
        clear_take_over(req)
        session.add(req); session.flush()
        return
    _discard_stage_mail(session, req.id, ntype)
    record_request_event(session, req.id, "take_over", actor_user=user,
                         note="Wniosek złożony przez przełożonego")
    try:
        record_event(
            session, action="request.taken_over",
            user_id=user.id, username=user.username,
            target_type="access_request", target_id=req.id,
            details={"department_id": req.department_id, "node_type": ntype,
                     "on_create": True},
            commit=False,
        )
    except Exception:
        pass
    session.flush()


def _auto_manager_steps(session: Session, req: AccessRequest, dept: Optional[Department],
                        user: User, data: "RequestCreate", kind: str) -> None:
    """Automatyczne kroki etapu kierownika przy składaniu wniosku z pozycjami.

    Dopóki obieg stoi na kroku kierownika (`MANAGER_STAGE_TYPES`), a składający
    może na nim działać, wykonujemy ten krok w jego imieniu: „wybór uprawnień”
    (pozycje z formularza) albo „akceptacja kierownika”. Gdy krok kieruje
    wniosek do IT i nadaje uprawnienia — wymagane oświadczenie (428)."""
    from services.workflow import MANAGER_STAGE_TYPES, can_act, execute_action
    for _ in range(len(MANAGER_STAGE_TYPES) + 1):
        inst, node = _current_node(session, req)
        ntype = (node or {}).get("type")
        if ntype not in MANAGER_STAGE_TYPES or not can_act(node, req, dept, user, session)[0]:
            return
        if ntype == "select_permissions":
            action = "select"
            payload = {"items": [
                {"system_id": i.system_id, "permission_id": i.permission_id,
                 "kind": (i.kind if i.kind in ("grant", "revoke")
                          else ("revoke" if kind == "revoke" else "grant")),
                 "custom_values": i.custom_values or {}}
                for i in data.items
            ]}
            comment = "Wybór uprawnień wykonany przez składającego wniosek"
        else:
            action, payload = "approve", None
            comment = "Akceptacja kierownika wykonana przez składającego wniosek"
        # Krok kończący się w IT, gdy wniosek nadaje uprawnienia — oświadczenie.
        payload = _enforce_declaration(
            session, inst, req, action, user, data.declaration, payload)
        # Wejście w ten krok zleciło już (w kolejce po commicie) e-mail „wniosek
        # czeka na Ciebie”. Krok wykonał właśnie składający, więc ta wiadomość
        # byłaby myląca — usuwamy ją; zostają powiadomienia o kolejnym etapie.
        _discard_stage_mail(session, req.id, ntype)
        execute_action(session, inst, req, user, action, payload=payload, comment=comment)
        session.flush()


def _save_initial_draft(session: Session, req: AccessRequest, dept: Optional[Department],
                        user: User) -> None:
    """„Zapisz roboczy" przy składaniu wniosku przez kierownika komórki
    (albo przełożonego, który składa wniosek dla podległej komórki).

    Wniosek zostaje na kroku kierownika (wybór uprawnień / akceptacja — bez
    automatycznego kroku i bez oświadczenia), oznaczony jako wersja robocza.
    E-mail „wniosek czeka na Ciebie”, zlecony przy wejściu w ten krok, jest
    zbędny — adresatem byłby sam składający.
    """
    from services.workflow import MANAGER_STAGE_TYPES, can_act, record_request_event
    from services.audit import record_event

    _inst, node = _current_node(session, req)
    ntype = (node or {}).get("type")
    if ntype not in MANAGER_STAGE_TYPES or not can_act(node, req, dept, user, session)[0]:
        raise HTTPException(400, "Wersję roboczą może zapisać tylko kierownik komórki "
                                 "(lub jego zastępca albo przełożony składający wniosek).")

    _discard_stage_mail(session, req.id, ntype)
    req.draft_saved_at = datetime.utcnow()
    session.add(req)
    record_request_event(session, req.id, "draft", actor_user=user,
                         note="Zapisano przy składaniu wniosku")
    try:
        record_event(
            session, action="request.draft_saved",
            user_id=user.id, username=user.username,
            target_type="access_request", target_id=req.id,
            details={"items": len(session.exec(
                select(RequestItem).where(RequestItem.request_id == req.id)).all()),
                "created": True},
            commit=False,
        )
    except Exception:
        pass
    session.flush()


# Cały obieg wniosków idzie wyłącznie przez silnik workflow
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
    from services.audit import record_event

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")

    is_it_manager = has_role(current_user, "manager") and has_role(current_user, "it_staff")
    if not is_it_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Wniosek może przekazać wyłącznie kierownik IT "
            "(konto z rolą kierownik ORAZ pracownik IT)")
    # Widoczność jak przy podglądzie — wniosek na etapie kierownika komórki
    # (wersja robocza) jest przed IT ukryty.
    _check_access(current_user, r, session)
    if r.status != RequestStatus.pending_it:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Przekazać pracownikowi IT można tylko wniosek czekający na realizację w IT.")

    old_assignee = r.assigned_to_user_id
    if data.user_id is None:
        r.assigned_to_user_id = None
    else:
        target = session.get(User, data.user_id)
        if not target or not target.is_active:
            raise HTTPException(400, "Wskazany pracownik nie istnieje lub jest nieaktywny")
        if not has_role(target, "it_staff"):
            raise HTTPException(400, "Wniosek można przekazać tylko pracownikowi IT")
        r.assigned_to_user_id = target.id

    session.add(r)
    try:
        record_event(
            session, action="request.assigned",
            user_id=current_user.id, username=current_user.username,
            target_type="access_request", target_id=r.id,
            details={"old_assigned_to_user_id": old_assignee,
                     "new_assigned_to_user_id": r.assigned_to_user_id},
            commit=False,
        )
    except Exception:
        pass
    session.commit(); session.refresh(r)
    return _request_out(session, r, current_user)


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

    Tylko dla wniosków BEZ dowiązanego konta (inaczej 409) — przepięcie
    zrealizowanych uprawnień na inne konto zmieniałoby rejestr uprawnień.
    Istniejącemu kontu nie uzupełniamy komórki (to mogłoby nadać zdolność
    HR, gdy komórka wniosku jest kadrowa).
    """
    from services.audit import record_event

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)
    if r.worker_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Wniosek ma już dowiązane konto pracownika — dowiązania nie można zmienić.")
    worker = _resolve_or_create_worker(session, data.ad_username, r, fill_department=False)
    old_worker = r.worker_user_id
    r.worker_user_id = worker.id
    session.add(r)
    try:
        record_event(
            session, action="request.worker_linked",
            user_id=current_user.id, username=current_user.username,
            target_type="access_request", target_id=r.id,
            details={"old_worker_user_id": old_worker,
                     "new_worker_user_id": worker.id,
                     "ad_username": worker.username},
            commit=False,
        )
    except Exception:
        pass
    session.commit(); session.refresh(r)
    return _request_out(session, r, current_user)


def _check_access(user: User, r: AccessRequest, session: Session) -> None:
    # Najpierw etap kierownika komórki (wersja robocza): krąg osób jest zamknięty
    # (kierownik i zastępcy, twórca, przejmujący, przełożeni, superadmin) —
    # ukryty także przed IT i administratorem.
    from services.workflow import manager_stage_visibility, DRAFT_HIDDEN_MSG
    vis = manager_stage_visibility(session, r, user)
    if vis is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DRAFT_HIDDEN_MSG)
    if vis is True:
        return
    if is_admin(user) or has_role(user, "it_staff"):
        return
    # Twórca zawsze widzi swój wniosek (np. kierownik Wydziału Kadr składający
    # zgłoszenie dla komórki spoza swojego zakresu kierowniczego).
    if r.created_by_id == user.id:
        return
    if has_role(user, "manager"):
        direct_ids, escalated_ids = _managed_dept_ids(session, user)
        if r.department_id in direct_ids or r.department_id in escalated_ids:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak dostępu do tego wniosku")
    # hr, viewer — tylko własne (własne wyszły wyżej)
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
    """Zwraca aktualny stan obiegu dla wniosku (pasek postępu + kroki).

    `events` — historia etapu kierownika komórki spoza podpisanych kroków:
    [{action: "draft"|"take_over"|"release", actor_name, at (ISO), note}]."""
    from models import WorkflowInstance
    from services.workflow import serialize_instance, serialize_request_events

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        return {"workflow_enabled": False, "events": serialize_request_events(session, r.id)}
    out = serialize_instance(session, inst)
    out["workflow_enabled"] = True
    out["events"] = serialize_request_events(session, r.id)
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
    # Typowo: przełożony dokończył krok, zanim kierownik niżej wysłał swój wybór.
    from models import WorkflowInstanceStatus
    if inst.status != WorkflowInstanceStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)
    if data.expected_node_id and inst.current_node_id != data.expected_node_id:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)

    # Najpierw — BEZ żadnych zmian w bazie — sprawdź bieżący węzeł, `can_act`
    # i czy akcja jest na nim dozwolona. Dopiero potem zapisujemy pozycje,
    # odmowy czy konto pracownika; inaczej osoba bez uprawnień (albo IT na
    # niewłaściwym kroku) zostawiałaby w bazie zmiany mimo odpowiedzi 403/400.
    from services.workflow import validate_action, MANAGER_STAGE_TYPES
    cur_node, _cur_dept = validate_action(session, inst, r, current_user, data.action)
    ntype = (cur_node or {}).get("type")
    # Stan przejęcia widziany przy walidacji — sprawdzany ponownie przed commitem.
    observed_taker = r.taken_over_by_id

    # Odmowa konkretnych pozycji — tylko kierownik nadrzędny (approve na
    # higher_manager_approve) albo IT (execute na it_execute).
    if data.denials:
        ok_combo = ((data.action == "approve" and ntype == "higher_manager_approve")
                    or (data.action == "execute" and ntype == "it_execute"))
        if not ok_combo:
            raise HTTPException(400,
                "Odmowa pozycji jest możliwa tylko przy zatwierdzaniu przez "
                "kierownika nadrzędnego albo realizacji przez IT.")

    # Payload zależy od akcji.
    payload = None
    if data.action == "select":
        # Zastąp RequestItem tym co przyszło (kierownik uzupełnia koszyk).
        # Każda pozycja niesie własny kierunek (grant/revoke) — stan docelowy.
        old = session.exec(select(RequestItem).where(RequestItem.request_id == r.id)).all()
        # Pusty wybór na wniosku z pozycjami (np. wpisanymi przez kadry) skasowałby
        # je po cichu — typowo, gdy front nie zdołał wczytać listy uprawnień.
        # Wymagamy świadomego potwierdzenia (allow_empty). To samo po zapisanej
        # wersji roboczej: pusta wersja nie może „przy okazji” trafić do IT.
        # Wniosek bez pozycji (np. ustanie pracownika, który nic nie ma) bez
        # wersji roboczej przechodzi jak dotąd.
        if not data.items and old and not data.allow_empty:
            raise HTTPException(400,
                "Nie wybrano żadnych uprawnień, a wniosek zawiera już pozycje "
                "(np. wpisane przez kadry). Zatwierdzenie pustego wyboru usunęłoby je. "
                "Odśwież wniosek i zaznacz uprawnienia albo potwierdź wniosek bez pozycji.")
        if not data.items and r.draft_saved_at and not data.allow_empty:
            raise HTTPException(400,
                "Wersja robocza nie zawiera żadnych uprawnień. Zaznacz uprawnienia "
                "albo potwierdź wysłanie wniosku bez pozycji.")
        payload = {"items": _replace_request_items(session, r, data.items)}
    elif data.action == "execute":
        payload = {"ad_username": data.ad_username} if data.ad_username else None

        # --- Pozycje dołożone przez IT ------------------------------------
        # Uprawnienie do kroku sprawdziło już validate_action; wszystko poniżej
        # (pozycje, konto-widmo z _resolve_or_create_worker) to flush w JEDNEJ
        # transakcji — przy błędzie nic nie zostaje w bazie.
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
            # duplikat dałby zdublowane wiersze w podglądzie wniosku i w rejestrze.
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

        # Dowiąż wniosek do konta pracownika (tworzy ghost-LDAP, jeśli trzeba).
        # Dzięki temu pracownik od razu widzi swoje
        # uprawnienia w „Moje uprawnienia", a wniosek pojawia się w strukturze.
        if data.ad_username and data.ad_username.strip():
            worker = _resolve_or_create_worker(session, data.ad_username, r)
            r.worker_user_id = worker.id

    # Odmowa konkretnych pozycji (kombinację akcja/węzeł sprawdzono wyżej).
    if data.denials:
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

    if ntype in MANAGER_STAGE_TYPES:
        # Wysłanie kroku kierownika: uwagi z wysyłki zastępują notatkę z wersji
        # roboczej (IT nie może zobaczyć nieaktualnej notatki), a wersja robocza
        # przestaje obowiązywać — kolejny etap zaczyna się bez niej.
        if data.action in ("select", "approve"):
            r.manager_comment = (data.comment or "").strip() or None
        r.draft_saved_at = None
        session.add(r)

    execute_action(session, inst, r, current_user, data.action,
                   payload=payload, comment=data.comment)
    if ntype in MANAGER_STAGE_TYPES:
        # Wyścig z przejęciem: zapis jest już w transakcji (blokada zapisu
        # SQLite), więc odczyt poniżej widzi każde zatwierdzone w międzyczasie
        # przejęcie. Gdy stan przejęcia się zmienił — ten krok nie jest ważny.
        session.flush()
        from sqlalchemy import select as _sa_select
        current_taker = session.connection().execute(
            _sa_select(AccessRequest.taken_over_by_id).where(AccessRequest.id == r.id)
        ).scalar()
        if current_taker != observed_taker:
            session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT,
                "Wniosek został w międzyczasie przejęty przez przełożonego. Odśwież wniosek.")
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


def _active_node(session: Session, request_id: int):
    """(instancja, bieżący węzeł) aktywnego obiegu albo 409/400, gdy go nie ma."""
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import find_node
    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request_id)
    ).first()
    if not inst:
        raise HTTPException(400, "Wniosek nie ma podpiętego obiegu (starszy wniosek?).")
    if inst.status != WorkflowInstanceStatus.active or not inst.current_node_id:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)
    try:
        node = find_node(json.loads(inst.template_snapshot), inst.current_node_id)
    except Exception:
        node = None
    if not node:
        raise HTTPException(400, "Instancja nie ma aktualnego węzła.")
    return inst, node


def _request_out(session: Session, r: AccessRequest, user: User) -> dict:
    out = _serialize_request(r, _get_items(session, r.id), session)
    _attach_node_info(session, [out], [r], user)
    return out


@router.post("/{request_id}/draft")
def save_draft(
    request_id: int,
    data: DraftSaveIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """„Zapisz roboczy" — kierownik komórki (albo przejmujący przełożony)
    zapisuje wniosek BEZ wysyłania go dalej. Na kroku wyboru uprawnień pozycje
    są zastępowane dokładnie jak przy akcji „select"; na kroku akceptacji
    kierownika zapisujemy tylko uwagi. Obieg stoi w miejscu, a wniosek pozostaje
    widoczny tylko dla kręgu kierownika (patrz `_check_access`). Pusta lista
    pozycji na wniosku, który ma pozycje, wymaga `allow_empty`."""
    from sqlalchemy import select as _sa_select
    from models import WorkflowInstance, WorkflowInstanceStatus
    from services.workflow import can_act, MANAGER_STAGE_TYPES, record_request_event
    from services.audit import record_event

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst, node = _active_node(session, request_id)
    if data.expected_node_id and inst.current_node_id != data.expected_node_id:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)
    ntype = node.get("type")
    if ntype not in MANAGER_STAGE_TYPES:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Wersję roboczą można zapisać tylko na etapie kierownika komórki "
            "(wybór lub akceptacja uprawnień). Odśwież wniosek.")
    dept = session.get(Department, r.department_id) if r.department_id else None
    allowed, reason = can_act(node, r, dept, current_user, session)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            reason or "Brak uprawnień do zapisania wersji roboczej.")
    observed_node, observed_taker = inst.current_node_id, r.taken_over_by_id

    try:
        if ntype == "select_permissions":
            old = session.exec(select(RequestItem).where(RequestItem.request_id == r.id)).all()
            if not data.items and old and not data.allow_empty:
                raise HTTPException(400,
                    "Wersja robocza bez uprawnień usunęłaby pozycje, które wniosek już "
                    "zawiera (np. wpisane przez kadry). Zaznacz uprawnienia albo potwierdź "
                    "zapis wniosku bez pozycji.")
            item_count = len(_replace_request_items(session, r, data.items,
                                                    allow_incomplete=True))
        else:
            # Akceptacja kierownika — pozycje są już ustalone; zapisujemy uwagi.
            item_count = len(session.exec(
                select(RequestItem).where(RequestItem.request_id == r.id)).all())
        r.draft_saved_at = datetime.utcnow()
        comment = (data.comment or "").strip()
        # Notatka kierownika z wersji roboczej (pole `manager_comment`) — front
        # podpowiada ją przy wysyłce; wysyłka zapisuje w tym polu uwagi z wysyłki.
        r.manager_comment = comment or None
        session.add(r)
        record_request_event(session, r.id, "draft", actor_user=current_user)
        try:
            # Do dziennika (dostępnego dla administratora) tylko liczba pozycji —
            # treść wersji roboczej jest przed administratorem ukryta.
            record_event(
                session, action="request.draft_saved",
                user_id=current_user.id, username=current_user.username,
                target_type="access_request", target_id=r.id,
                details={"items": item_count, "node_type": ntype,
                         "has_comment": bool(comment)},
                commit=False,
            )
        except Exception:
            pass
        session.flush()
        # Ponowna kontrola w tej samej transakcji (zapis trzyma już blokadę
        # SQLite): obieg nie poszedł dalej i nikt nie przejął wniosku.
        conn = session.connection()
        fresh = conn.execute(
            _sa_select(WorkflowInstance.current_node_id, WorkflowInstance.status)
            .where(WorkflowInstance.id == inst.id)
        ).first()
        fresh_taker = conn.execute(
            _sa_select(AccessRequest.taken_over_by_id).where(AccessRequest.id == r.id)
        ).scalar()
        if (not fresh or fresh[0] != observed_node
                or fresh[1] != WorkflowInstanceStatus.active
                or fresh_taker != observed_taker):
            raise HTTPException(status.HTTP_409_CONFLICT,
                "Wniosek zmienił stan w międzyczasie (wysłany dalej albo przejęty). "
                "Odśwież wniosek.")
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    session.refresh(r)
    return _request_out(session, r, current_user)


def _notify_taken_over(session: Session, r: AccessRequest, dept: Optional[Department],
                       taker: User, extra_ids: tuple = ()) -> None:
    """E-mail o przejęciu: kierownik komórki, jego zastępcy oraz osoby z
    `extra_ids` (np. poprzednio przejmujący) — bez samego przejmującego."""
    try:
        from services.after_commit import defer
        from services.email_alerts import notify_request_taken_over
        from services.permissions import dept_deputy_ids
        taker_name = taker.full_name or taker.username
        targets = [dept.manager_user_id] if dept and dept.manager_user_id else []
        if dept:
            targets += sorted(dept_deputy_ids(session, dept.id))
        targets += [x for x in extra_ids if x]
        sent: set[str] = set()
        for uid in targets:
            u = session.get(User, uid)
            if not u or not u.is_active or not u.email or u.id == taker.id \
                    or u.email in sent:
                continue
            sent.add(u.email)
            defer(session, notify_request_taken_over,
                  to_address=u.email, request_id=r.id, worker_name=r.worker_name,
                  dept_name=dept.name if dept else "", taker_name=taker_name,
                  from_name=taker_name, from_email=taker.email)
    except Exception as exc:
        _log.warning("Powiadomienie o przejęciu wniosku nie zostało zlecone: %s", exc)


@router.post("/{request_id}/take-over")
def take_over_request(
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """„Przejmij" — przełożony (kierownik / zastępca komórki wyżej, dyrektor
    jednostki) przejmuje wniosek czekający u kierownika komórki. Od tej chwili
    krok kierowniczy wykonuje wyłącznie on; kierownik komórki dostaje 403.

    Przełożony stojący wyżej niż obecny przejmujący może przejąć wniosek
    ponownie. Przejęcie, które wygasło (przejmujący nieaktywny albo bez
    stanowiska), nie blokuje nowego. Zapis jest warunkowy — gdy w międzyczasie
    ktoś inny przejął wniosek albo obieg poszedł dalej → 409."""
    from services.workflow import (
        can_take_over, claim_take_over, effective_taker_id, record_request_event,
    )
    from services.audit import record_event

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    inst, node = _active_node(session, request_id)
    dept = session.get(Department, r.department_id) if r.department_id else None
    ok, code, reason = can_take_over(session, r, current_user, node.get("type"), dept)
    if not ok:
        raise HTTPException(code, reason)

    prev_taker_id = effective_taker_id(session, r, dept)
    prev_taker_name = r.taken_over_by_name if prev_taker_id else None
    if not claim_take_over(session, r, current_user,
                           expected_taker_id=r.taken_over_by_id,
                           expected_node_id=inst.current_node_id):
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Wniosek zmienił stan w międzyczasie (przejął go ktoś inny albo został "
            "wysłany dalej). Odśwież wniosek.")

    taker_name = current_user.full_name or current_user.username
    note = f"Przejęcie od: {prev_taker_name}" if prev_taker_name else None
    record_request_event(session, r.id, "take_over", actor_user=current_user, note=note)
    try:
        record_event(
            session, action="request.taken_over",
            user_id=current_user.id, username=current_user.username,
            target_type="access_request", target_id=r.id,
            details={"department_id": r.department_id,
                     "node_type": node.get("type"),
                     "taken_over_by_name": taker_name,
                     "previous_taker_id": prev_taker_id},
            commit=False,
        )
    except Exception:
        pass

    # Poinformuj kierownika komórki (i zastępców) oraz poprzednio przejmującego.
    _notify_taken_over(session, r, dept, current_user, extra_ids=(prev_taker_id,))

    session.commit()
    session.refresh(r)
    return _request_out(session, r, current_user)


@router.post("/{request_id}/release")
def release_request(
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """„Oddaj” — przejmujący (albo superadmin) zwalnia przejęcie wniosku.
    Wniosek wraca do kierownika komórki (z powiadomieniem o etapie); przełożeni
    mogą go znowu przejąć. Tylko na etapie kierownika komórki."""
    from services.workflow import (
        is_manager_stage, clear_take_over, record_request_event, _notify_stage,
    )
    from services.audit import record_event

    r = session.get(AccessRequest, request_id)
    if not r:
        raise HTTPException(404, "Wniosek nie istnieje")
    _check_access(current_user, r, session)

    _inst, node = _active_node(session, request_id)
    if not r.taken_over_by_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Wniosek nie jest przejęty.")
    if r.taken_over_by_id != current_user.id and not has_role(current_user, "superadmin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
            "Przejęcie może oddać tylko osoba, która przejęła wniosek, albo superadmin.")
    dept = session.get(Department, r.department_id) if r.department_id else None
    if not is_manager_stage(session, node.get("type"), dept):
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Przejęcie można oddać tylko, gdy wniosek czeka na etapie kierownika komórki.")

    prev_id, prev_name = r.taken_over_by_id, r.taken_over_by_name
    clear_take_over(r)
    session.add(r)
    # Superadmin zwalniający cudze przejęcie — w historii widać czyje.
    note = f"Zwolniono przejęcie: {prev_name}" if prev_id != current_user.id else None
    record_request_event(session, r.id, "release", actor_user=current_user, note=note)
    try:
        record_event(
            session, action="request.take_over_released",
            user_id=current_user.id, username=current_user.username,
            target_type="access_request", target_id=r.id,
            details={"department_id": r.department_id, "node_type": node.get("type"),
                     "released_taker_name": prev_name},
            commit=False,
        )
    except Exception:
        pass
    # Kierownik komórki znów jest adresatem kroku — przypomnij mu o wniosku.
    _notify_stage(session, r, node, dept, current_user)
    session.commit()
    session.refresh(r)
    return _request_out(session, r, current_user)


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
    from models import WorkflowInstanceStatus
    if inst.status != WorkflowInstanceStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)

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
    from models import WorkflowInstanceStatus
    if inst.status != WorkflowInstanceStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, STEP_ALREADY_DONE_MSG)

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
