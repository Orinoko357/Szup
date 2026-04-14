from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, get_client_ip

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class StrukturIn(BaseModel):
    tenant_id: int
    nazwa: str
    typ_wezla: Optional[str] = "WYDZIAL"
    nadrzedny_id: Optional[int] = None
    kolejnosc: Optional[int] = 0
    aktywna: Optional[bool] = True


@router.get("/")
async def list_struktura(tenant_id: Optional[int] = None,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(get_current_user)):
    if tenant_id:
        rows = session.execute(
            text("SELECT s.*, t.nazwa as tenant_nazwa FROM struktura_org s JOIN tenants t ON t.id=s.tenant_id WHERE s.tenant_id=:tid ORDER BY s.tenant_id, s.kolejnosc"),
            {"tid": tenant_id},
        ).mappings().all()
    else:
        rows = session.execute(
            text("SELECT s.*, t.nazwa as tenant_nazwa FROM struktura_org s JOIN tenants t ON t.id=s.tenant_id ORDER BY s.tenant_id, s.kolejnosc")
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/", status_code=201)
async def create_struktura(body: StrukturIn, session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc, aktywna) VALUES (:tid,:n,:t,:nad,:k,1) RETURNING *"),
        {"tid": body.tenant_id, "n": body.nazwa, "t": body.typ_wezla or "WYDZIAL",
         "nad": body.nadrzedny_id, "k": body.kolejnosc or 0},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/{node_id}")
async def update_struktura(node_id: int, body: StrukturIn, session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE struktura_org SET nazwa=:n, typ_wezla=:t, nadrzedny_id=:nad, kolejnosc=:k, aktywna=:a WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "t": body.typ_wezla or "WYDZIAL", "nad": body.nadrzedny_id,
         "k": body.kolejnosc or 0, "a": body.aktywna if body.aktywna is not None else True, "id": node_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Nie znaleziono węzła.")
    return dict(row)


@router.delete("/{node_id}")
async def delete_struktura(node_id: int, session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    session.execute(text("UPDATE struktura_org SET aktywna=0 WHERE id=:id"), {"id": node_id})
    session.commit()
    return {"message": "Węzeł dezaktywowany."}
