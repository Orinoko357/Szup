"""
Router: szablony obiegu wniosków (WorkflowTemplate).

Zarządza: admin. Odczyt: każdy zalogowany (żeby HR / manager mógł zobaczyć
strukturę obiegu przy tworzeniu wniosku).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import RequestType, User, WorkflowInstance, WorkflowTemplate
from services.permissions import require_admin
from services.workflow import WorkflowGraphError, parse_graph

router = APIRouter()


def _audit(session: Session, request: Request, user: User, action: str, *,
           template_id: int, name: str, version: int,
           details: Optional[dict] = None) -> None:
    """Zmiana szablonu obiegu decyduje, kto akceptuje wnioski — ślad w audit logu."""
    from services.audit import record_event, request_meta
    meta = request_meta(request)
    record_event(session, action=action, user_id=user.id, username=user.username,
                 target_type="workflow_template", target_id=template_id, ip=meta["ip"],
                 user_agent=meta["user_agent"],
                 details={"name": name, "version": version, **(details or {})})


def _serialize(session: Session, t: WorkflowTemplate) -> dict:
    creator = session.get(User, t.created_by_user_id) if t.created_by_user_id else None
    uses_count = len(session.exec(
        select(RequestType).where(RequestType.workflow_template_id == t.id)
    ).all())
    active_instances = len(session.exec(
        select(WorkflowInstance)
        .where(WorkflowInstance.template_id == t.id)
        .where(WorkflowInstance.status == "active")
    ).all())
    return {
        "id": t.id, "name": t.name, "description": t.description,
        "version": t.version, "graph_json": t.graph_json,
        "is_active": t.is_active,
        "created_at": t.created_at,
        "created_by_user_id": t.created_by_user_id,
        "created_by_name": (creator.full_name or creator.username) if creator else None,
        "used_by_request_types_count": uses_count,
        "active_instances_count": active_instances,
    }


class TemplateIn(BaseModel):
    name: str
    description: Optional[str] = None
    graph_json: str
    is_active: bool = True


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    graph_json: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/")
def list_templates(
    is_active: Optional[bool] = Query(None),
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    q = select(WorkflowTemplate).order_by(WorkflowTemplate.name)
    if is_active is not None:
        q = q.where(WorkflowTemplate.is_active == is_active)
    return [_serialize(session, t) for t in session.exec(q).all()]


@router.get("/{template_id}")
def get_template(
    template_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    t = session.get(WorkflowTemplate, template_id)
    if not t:
        raise HTTPException(404, "Szablon nie istnieje")
    return _serialize(session, t)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_template(
    data: TemplateIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin),
):
    try:
        parse_graph(data.graph_json)
    except WorkflowGraphError as exc:
        raise HTTPException(400, str(exc))
    t = WorkflowTemplate(
        name=data.name.strip(),
        description=data.description,
        graph_json=data.graph_json,
        is_active=data.is_active,
        version=1,
        created_by_user_id=user.id,
    )
    session.add(t); session.commit(); session.refresh(t)
    _audit(session, request, user, "workflow_template.created", template_id=t.id,
           name=t.name, version=t.version, details={"is_active": t.is_active})
    return _serialize(session, t)


@router.patch("/{template_id}")
def update_template(
    template_id: int,
    data: TemplatePatch,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin),
):
    t = session.get(WorkflowTemplate, template_id)
    if not t:
        raise HTTPException(404, "Szablon nie istnieje")
    payload = data.model_dump(exclude_unset=True)
    if "graph_json" in payload:
        try:
            parse_graph(payload["graph_json"])
        except WorkflowGraphError as exc:
            raise HTTPException(400, str(exc))
        # Nowa wersja szablonu — trwające instancje trzymają snapshot,
        # więc nic im się nie stanie.
        t.version = (t.version or 1) + 1
    changed = sorted(k for k, v in payload.items() if getattr(t, k) != v)
    for k, v in payload.items():
        setattr(t, k, v)
    session.add(t); session.commit(); session.refresh(t)
    if changed:
        # Sam graf bywa duży — zapisujemy nazwy zmienionych pól i nową wersję.
        _audit(session, request, user, "workflow_template.updated", template_id=t.id,
               name=t.name, version=t.version,
               details={"changed": changed, "is_active": t.is_active})
    return _serialize(session, t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin),
):
    t = session.get(WorkflowTemplate, template_id)
    if not t:
        raise HTTPException(404, "Szablon nie istnieje")
    # Blokada: szablon użyty przez RequestType
    used = session.exec(
        select(RequestType).where(RequestType.workflow_template_id == template_id)
    ).first()
    if used:
        raise HTTPException(400, f'Szablon jest używany przez typ wniosku "{used.name}" — najpierw odepnij.')
    # Blokada: trwające instancje
    active = session.exec(
        select(WorkflowInstance)
        .where(WorkflowInstance.template_id == template_id)
        .where(WorkflowInstance.status == "active")
    ).first()
    if active:
        raise HTTPException(400, "Szablon ma trwające instancje — zaczekaj aż się zakończą lub odrzuć wnioski.")
    name, version = t.name, t.version
    session.delete(t); session.commit()
    _audit(session, request, user, "workflow_template.deleted", template_id=template_id,
           name=name, version=version)
