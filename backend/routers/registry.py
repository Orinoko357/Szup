"""
Rejestr nadanych uprawnień — dla pracowników IT / admina.

Zestawienie WSZYSTKICH nadanych uprawnień (pozycji `RequestItem.kind='grant'`)
z wniosków, które doszły do realizacji (status pending_it/completed), złączone
z oświadczeniem wnioskującego (`PermissionDeclaration`) po `request_id`.

Do audytu (NIS2/KSC/RODO): kto, komu, jakie uprawnienie, kiedy, na podstawie
jakiego oświadczenia (data + osoba) i pod jakim kodem referencyjnym.
Eksport CSV jak w audit logu (`;`, UTF-8 z BOM).
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from database import get_session
from models import (
    AccessRequest,
    Department,
    PermissionDeclaration,
    PermissionSystem,
    RequestItem,
    RequestStatus,
    SystemPermission,
    Unit,
    User,
)
from services.permissions import require_it_staff

router = APIRouter()

# Wnioski, których pozycje uznajemy za „nadane" (skierowane do IT lub zamknięte).
_GRANTED_STATUSES = (RequestStatus.pending_it, RequestStatus.completed)


def _rows(session: Session, *, unit_id=None, system_id=None, q=None,
          date_from=None, date_to=None, only_with_declaration=False,
          limit=None, offset=0):
    """Buduje wiersze rejestru (lista dictów). Bez paginacji, gdy limit=None."""
    stmt = (
        select(RequestItem, AccessRequest)
        .join(AccessRequest, col(RequestItem.request_id) == col(AccessRequest.id))
        .where(RequestItem.kind == "grant")
        # Do rejestru trafiają WYŁĄCZNIE pozycje faktycznie zrealizowane przez IT
        # (odhaczone na etapie realizacji). Dzięki temu nie pokazujemy pozycji,
        # które dopiero czekają na realizację ani odmówionych (odmowa czyści
        # `fulfilled`). Finalne „Realizuj" odhacza wszystkie nieodmówione pozycje.
        .where(col(RequestItem.fulfilled) == True)   # noqa: E712
        .where(col(RequestItem.denied) == False)     # noqa: E712
        .where(col(AccessRequest.status).in_(_GRANTED_STATUSES))
    )
    if unit_id:
        stmt = stmt.where(AccessRequest.unit_id == unit_id)
    if system_id:
        stmt = stmt.where(RequestItem.system_id == system_id)
    if date_from:
        stmt = stmt.where(AccessRequest.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AccessRequest.created_at <= date_to)
    stmt = stmt.order_by(col(AccessRequest.created_at).desc(), col(RequestItem.id).desc())
    pairs = session.exec(stmt).all()

    # Oświadczenia po request_id (jedno na wniosek — ostatnie wygrywa).
    req_ids = list({r.id for _, r in pairs})
    decls: dict[int, PermissionDeclaration] = {}
    if req_ids:
        for d in session.exec(
            select(PermissionDeclaration)
            .where(col(PermissionDeclaration.request_id).in_(req_ids))
        ).all():
            decls[d.request_id] = d

    sys_ids = list({it.system_id for it, _ in pairs})
    perm_ids = list({it.permission_id for it, _ in pairs})
    sys_map = {s.id: s for s in session.exec(
        select(PermissionSystem).where(col(PermissionSystem.id).in_(sys_ids)))} if sys_ids else {}
    perm_map = {p.id: p for p in session.exec(
        select(SystemPermission).where(col(SystemPermission.id).in_(perm_ids)))} if perm_ids else {}
    dept_ids = list({r.department_id for _, r in pairs if r.department_id})
    unit_ids = list({r.unit_id for _, r in pairs if r.unit_id})
    dept_map = {d.id: d for d in session.exec(
        select(Department).where(col(Department.id).in_(dept_ids)))} if dept_ids else {}
    unit_map = {u.id: u for u in session.exec(
        select(Unit).where(col(Unit.id).in_(unit_ids)))} if unit_ids else {}

    ql = (q or "").strip().lower()
    out = []
    for it, req in pairs:
        dec = decls.get(req.id)
        if only_with_declaration and not dec:
            continue
        worker = req.worker_name or ""
        if ql and ql not in worker.lower():
            continue
        perm = perm_map.get(it.permission_id)
        sysrow = sys_map.get(it.system_id)
        vals = {}
        if it.custom_values:
            try:
                loaded = json.loads(it.custom_values)
                if isinstance(loaded, dict):
                    vals = {str(k): str(v) for k, v in loaded.items()}
            except (json.JSONDecodeError, TypeError):
                vals = {}
        out.append({
            "request_id": req.id,
            "worker_name": worker,
            "worker_user_id": req.worker_user_id,
            "unit_name": (unit_map.get(req.unit_id).name if req.unit_id in unit_map else None),
            "department_name": (dept_map.get(req.department_id).name
                                if req.department_id in dept_map else None),
            "system_name": sysrow.name if sysrow else None,
            "permission_name": perm.permission_name if perm else None,
            "group_name": getattr(perm, "group_name", None) if perm else None,
            "subgroup_name": getattr(perm, "subgroup_name", None) if perm else None,
            "custom_values": vals,
            "granted_at": (req.completed_at or req.approved_at or req.created_at),
            "request_status": req.status.value if hasattr(req.status, "value") else req.status,
            # Kolumny oświadczenia:
            "declared_by_name": dec.declared_by_name if dec else None,
            "declared_date": dec.declared_date if dec else None,
            "declaration_at": dec.approved_at if dec else None,
            "reference_code": dec.reference_code if dec else None,
        })

    total = len(out)
    if limit is not None:
        out = out[offset:offset + limit]
    return out, total


@router.get("/granted")
def granted_registry(
    unit_id: Optional[int] = None,
    system_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    only_with_declaration: bool = False,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    rows, total = _rows(
        session, unit_id=unit_id, system_id=system_id, q=q,
        date_from=date_from, date_to=date_to,
        only_with_declaration=only_with_declaration, limit=limit, offset=offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/granted.csv")
def granted_registry_csv(
    unit_id: Optional[int] = None,
    system_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    only_with_declaration: bool = False,
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    rows, _total = _rows(
        session, unit_id=unit_id, system_id=system_id, q=q,
        date_from=date_from, date_to=date_to,
        only_with_declaration=only_with_declaration, limit=None)

    buf = io.StringIO()
    buf.write("﻿")  # BOM — Excel poprawnie odczyta UTF-8
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Nr wniosku", "Pracownik", "Jednostka", "Wydział", "System",
                "Uprawnienie", "Grupa", "Podgrupa", "Zakres", "Data nadania", "Status",
                "Oświadczenie — osoba", "Oświadczenie — data", "Kod"])
    for r in rows:
        zakres = "; ".join(f"{k}: {v}" for k, v in (r["custom_values"] or {}).items())
        granted = r["granted_at"]
        w.writerow([
            r["request_id"], r["worker_name"], r["unit_name"] or "",
            r["department_name"] or "", r["system_name"] or "",
            r["permission_name"] or "", r["group_name"] or "",
            r["subgroup_name"] or "", zakres,
            granted.isoformat() if hasattr(granted, "isoformat") else (granted or ""),
            r["request_status"] or "",
            r["declared_by_name"] or "", r["declared_date"] or "",
            r["reference_code"] or "",
        ])
    buf.seek(0)
    fname = f"szup-rejestr-uprawnien-{datetime.utcnow().date()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/declarations/{reference_code}")
def declaration_detail(
    reference_code: str,
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    """Szczegół pojedynczego oświadczenia (zamrożona treść) — do podglądu/druku."""
    dec = session.exec(
        select(PermissionDeclaration)
        .where(PermissionDeclaration.reference_code == reference_code)
    ).first()
    if not dec:
        raise HTTPException(404, "Oświadczenie nie istnieje")
    items = []
    if dec.items_snapshot:
        try:
            items = json.loads(dec.items_snapshot)
        except (json.JSONDecodeError, TypeError):
            items = []
    return {
        "reference_code": dec.reference_code,
        "request_id": dec.request_id,
        "worker_name": dec.worker_name,
        "worker_user_id": dec.worker_user_id,
        "declared_by_name": dec.declared_by_name,
        "declared_by_login": dec.declared_by_login,
        "declared_date": dec.declared_date,
        "approved_at": dec.approved_at,
        "declaration_text": dec.declaration_text,
        "items": items,
    }
