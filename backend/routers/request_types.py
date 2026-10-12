"""
Router: typy wniosków (RequestType). Każdy typ ma przypisany szablon obiegu.

Zarządza: admin. Odczyt: każdy zalogowany (żeby HR mogła wybrać typ przy
tworzeniu wniosku).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import AccessRequest, RequestType, User, WorkflowTemplate
from services.auth_service import get_current_user
from services.permissions import require_admin

router = APIRouter()


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
    tpl = session.get(WorkflowTemplate, data.workflow_template_id)
    if not tpl:
        raise HTTPException(400, "Szablon obiegu nie istnieje")
    if not tpl.is_active:
        raise HTTPException(400, "Szablon obiegu jest nieaktywny")
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
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    t = session.get(RequestType, type_id)
    if not t:
        raise HTTPException(404, "Typ wniosku nie istnieje")
    payload = data.model_dump(exclude_unset=True)
    if "workflow_template_id" in payload and payload["workflow_template_id"]:
        tpl = session.get(WorkflowTemplate, payload["workflow_template_id"])
        if not tpl:
            raise HTTPException(400, "Szablon obiegu nie istnieje")
    for k, v in payload.items():
        setattr(t, k, v)
    session.add(t); session.commit(); session.refresh(t)
    return _serialize(session, t)


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
