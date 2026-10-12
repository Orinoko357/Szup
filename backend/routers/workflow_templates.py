"""
Router: szablony obiegu wniosków (WorkflowTemplate).

Zarządza: admin. Odczyt: każdy zalogowany (żeby HR / manager mógł zobaczyć
strukturę obiegu przy tworzeniu wniosku).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import NODE_TYPES, RequestType, User, WorkflowInstance, WorkflowTemplate
from services.auth_service import get_current_user
from services.permissions import require_admin
from services.workflow import WorkflowGraphError, parse_graph

router = APIRouter()


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


@router.get("/node-types")
def list_node_types(_: User = Depends(require_admin)):
    """Lista typów węzłów zrozumiałych przez silnik — dla frontendowej palety."""
    catalog = [
        {"type": "start",
         "label": "Zgłoszenie / Start",
         "description": "Rozpoczęcie obiegu. Zawsze pierwszy węzeł.",
         "icon": "play"},
        {"type": "select_permissions",
         "label": "Wybór uprawnień + podpis",
         "description": "Kierownik wybiera systemy i uprawnienia dla pracownika.",
         "icon": "list-checks"},
        {"type": "manager_approve",
         "label": "Akceptacja kierownika bezpośredniego + podpis",
         "description": "Kierownik referatu / biura zatwierdza wniosek.",
         "icon": "user-check"},
        {"type": "higher_manager_approve",
         "label": "Akceptacja kierownika wyższego rzędu + podpis",
         "description": ("Kierownik wydziału nadrzędnego zatwierdza. Silnik "
                         "pomija ten węzeł jeśli wydział pracownika nie ma "
                         "flagi 'wymaga akceptacji wyższego rzędu'."),
         "icon": "crown"},
        {"type": "it_execute",
         "label": "Realizacja przez IT",
         "description": "Pracownik IT realizuje wniosek technicznie.",
         "icon": "wrench"},
        {"type": "end",
         "label": "Zakończenie",
         "description": "Zamknięcie obiegu. Musi być co najmniej jeden.",
         "icon": "flag"},
    ]
    return {"node_types": catalog, "raw": list(NODE_TYPES)}


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
    return _serialize(session, t)


@router.patch("/{template_id}")
def update_template(
    template_id: int,
    data: TemplatePatch,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
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
    for k, v in payload.items():
        setattr(t, k, v)
    session.add(t); session.commit(); session.refresh(t)
    return _serialize(session, t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
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
    session.delete(t); session.commit()
