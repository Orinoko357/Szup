"""
Router: typy wniosków (RequestType). Każdy typ ma przypisany szablon obiegu.

Zarządza: admin. Odczyt: każdy zalogowany (żeby HR mogła wybrać typ przy
tworzeniu wniosku).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import AccessRequest, RequestType, User, WorkflowTemplate
from services.auth_service import get_current_user
from services.permissions import require_admin
from services.workflow import WorkflowGraphError, check_request_graph_json

router = APIRouter()


def _usable_template(session: Session, template_id: int) -> WorkflowTemplate:
    """Szablon, który można przypisać typowi wniosku: istnieje, jest aktywny
    i spełnia reguły obiegu (etap kierownika, realizacja IT) — inaczej 400."""
    tpl = session.get(WorkflowTemplate, template_id)
    if not tpl:
        raise HTTPException(400, "Szablon obiegu nie istnieje")
    if not tpl.is_active:
        raise HTTPException(400, "Szablon obiegu jest nieaktywny")
    try:
        check_request_graph_json(tpl.graph_json)
    except WorkflowGraphError as exc:
        raise HTTPException(400, f"Szablonu „{tpl.name}” nie można przypisać do typu "
                                 f"wniosku: {exc}")
    return tpl


def _serialize(session: Session, t: RequestType) -> dict:
    tpl = session.get(WorkflowTemplate, t.workflow_template_id) if t.workflow_template_id else None
    used = len(session.exec(
        select(AccessRequest).where(AccessRequest.request_type_id == t.id)
    ).all())
    return {
        "id": t.id,
        "name": t.name,
        "code": t.code,
        "description": t.description,
        "workflow_template_id": t.workflow_template_id,
        "workflow_template_name": tpl.name if tpl else None,
        "workflow_template_version": tpl.version if tpl else None,
        "is_active": t.is_active,
        "icon": t.icon,
        "used_by_requests_count": used,
        "created_at": t.created_at,
    }


class RequestTypeIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    workflow_template_id: int
    is_active: bool = True
    icon: Optional[str] = None


class RequestTypePatch(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    workflow_template_id: Optional[int] = None
    is_active: Optional[bool] = None
    icon: Optional[str] = None


@router.get("/")
def list_request_types(
    is_active: Optional[bool] = Query(None),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    q = select(RequestType).order_by(RequestType.name)
    if is_active is not None:
        q = q.where(RequestType.is_active == is_active)
    return [_serialize(session, t) for t in session.exec(q).all()]


@router.get("/{type_id}")
def get_request_type(
    type_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    t = session.get(RequestType, type_id)
    if not t:
        raise HTTPException(404, "Typ wniosku nie istnieje")
    return _serialize(session, t)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_request_type(
    data: RequestTypeIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    _usable_template(session, data.workflow_template_id)
    t = RequestType(
        name=data.name.strip(),
        code=(data.code or None),
        description=data.description,
        workflow_template_id=data.workflow_template_id,
        is_active=data.is_active,
        icon=data.icon,
    )
    session.add(t); session.commit(); session.refresh(t)
    return _serialize(session, t)


@router.patch("/{type_id}")
def update_request_type(
    type_id: int,
    data: RequestTypePatch,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin),
):
    t = session.get(RequestType, type_id)
    if not t:
        raise HTTPException(404, "Typ wniosku nie istnieje")
    payload = data.model_dump(exclude_unset=True)
    if "workflow_template_id" in payload:
        if not payload["workflow_template_id"]:
            raise HTTPException(400, "Typ wniosku musi mieć przypisany szablon obiegu.")
        _usable_template(session, payload["workflow_template_id"])
    old_tpl_id = t.workflow_template_id
    for k, v in payload.items():
        setattr(t, k, v)
    session.add(t); session.commit(); session.refresh(t)
    if t.workflow_template_id != old_tpl_id:
        _template_changed(session, request, user, t, old_tpl_id)
    return _serialize(session, t)


def _template_changed(session: Session, request: Request, user: User,
                      t: RequestType, old_tpl_id: int | None) -> None:
    """Zmiana szablonu typu wniosku decyduje, kto akceptuje nowe wnioski —
    wpis w dzienniku audytu i zdarzenie bezpieczeństwa wysokiej wagi."""
    from models import SecuritySeverity
    from services.audit import record_event, request_meta
    from services.security_events import emit
    meta = request_meta(request)
    old_tpl = session.get(WorkflowTemplate, old_tpl_id) if old_tpl_id else None
    new_tpl = session.get(WorkflowTemplate, t.workflow_template_id)
    details = {"request_type_id": t.id, "code": t.code, "name": t.name,
               "old_template_id": old_tpl_id,
               "old_template_name": old_tpl.name if old_tpl else None,
               "new_template_id": t.workflow_template_id,
               "new_template_name": new_tpl.name if new_tpl else None}
    record_event(session, action="request_type.template_changed", user_id=user.id,
                 username=user.username, target_type="request_type", target_id=t.id,
                 ip=meta["ip"], user_agent=meta["user_agent"], details=details)
    emit(session, event_type="request_type.template_changed", source="request_types",
         severity=SecuritySeverity.high,
         summary=(f"Zmieniono szablon obiegu typu wniosku „{t.name}”: "
                  f"„{details['old_template_name']}” → „{details['new_template_name']}” "
                  f"— przez {user.username}"),
         details=details, user_id=user.id, ip=meta["ip"], commit=True)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request_type(
    type_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    t = session.get(RequestType, type_id)
    if not t:
        raise HTTPException(404, "Typ wniosku nie istnieje")
    used = session.exec(
        select(AccessRequest).where(AccessRequest.request_type_id == type_id)
    ).first()
    if used:
        raise HTTPException(400, "Typ jest używany przez istniejące wnioski — najpierw je zamknij lub przenieś.")
    session.delete(t); session.commit()
