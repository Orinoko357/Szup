from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class KomorkaIn(BaseModel):
    tenant_id: Optional[int] = None
    struktura_org_id: Optional[int] = None
    nazwa: str
    kod: Optional[str] = None
    aktywna: Optional[bool] = True


@router.get("/")
async def list_komorki(tenant_id: Optional[int] = None, struktura_org_id: Optional[int] = None,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(get_current_user)):
    q = "SELECT k.*, s.nazwa as struktura_nazwa, t.nazwa as tenant_nazwa FROM komorki_org k LEFT JOIN struktura_org s ON s.id=k.struktura_org_id JOIN tenants t ON t.id=k.tenant_id WHERE 1=1"
    params = {}
    if tenant_id:
        q += " AND k.tenant_id=:tid"
        params["tid"] = tenant_id
    if struktura_org_id:
        q += " AND k.struktura_org_id=:sid"
        params["sid"] = struktura_org_id
    q += " ORDER BY k.nazwa"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{komorka_id}")
async def get_komorka(komorka_id: int, session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("SELECT k.*, s.nazwa as struktura_nazwa FROM komorki_org k LEFT JOIN struktura_org s ON s.id=k.struktura_org_id WHERE k.id=:id"),
        {"id": komorka_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Nie znaleziono komórki.")
    return dict(row)


@router.post("/", status_code=201)
async def create_komorka(body: KomorkaIn, session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("INSERT INTO komorki_org (tenant_id, struktura_org_id, nazwa, kod) VALUES (:tid,:sid,:n,:k) RETURNING *"),
        {"tid": body.tenant_id, "sid": body.struktura_org_id, "n": body.nazwa, "k": body.kod},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/{komorka_id}")
async def update_komorka(komorka_id: int, body: KomorkaIn, session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE komorki_org SET nazwa=:n, kod=:k, struktura_org_id=:sid, aktywna=:a WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "k": body.kod, "sid": body.struktura_org_id,
         "a": body.aktywna if body.aktywna is not None else True, "id": komorka_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Nie znaleziono komórki.")
    return dict(row)


@router.delete("/{komorka_id}")
async def delete_komorka(komorka_id: int, session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    session.execute(text("UPDATE komorki_org SET aktywna=0 WHERE id=:id"), {"id": komorka_id})
    session.commit()
    return {"message": "Komórka dezaktywowana."}
