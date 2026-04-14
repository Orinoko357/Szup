from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip
from fastapi import Request

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class TenantIn(BaseModel):
    nazwa: str
    skrot: str
    regon: Optional[str] = None
    nip: Optional[str] = None
    aktywny: Optional[bool] = True
    dni_do_przegladu: Optional[int] = 365


@router.get("")
async def list_tenants(session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(get_current_user)):
    rows = session.execute(text("SELECT * FROM tenants ORDER BY nazwa")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: int, session: Session = Depends(get_session),
                     current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(text("SELECT * FROM tenants WHERE id=:id"), {"id": tenant_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Nie znaleziono jednostki.")
    return dict(row)


@router.post("", status_code=201)
async def create_tenant(body: TenantIn, request: Request,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("INSERT INTO tenants (nazwa, skrot, regon, nip, dni_do_przegladu, aktywny, data_utworzenia) VALUES (:n,:s,:r,:nip,:d,1,:dt) RETURNING *"),
        {"n": body.nazwa, "s": body.skrot, "r": body.regon, "nip": body.nip,
         "d": body.dni_do_przegladu or 365, "dt": datetime.utcnow()},
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="TENANT_CREATE", tabela_docelowa="tenants",
                rekord_id=result["id"], nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.put("/{tenant_id}")
async def update_tenant(tenant_id: int, body: TenantIn, request: Request,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE tenants SET nazwa=:n, skrot=:s, regon=:r, nip=:nip, aktywny=:a, dni_do_przegladu=:d WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "s": body.skrot, "r": body.regon, "nip": body.nip,
         "a": body.aktywny if body.aktywny is not None else True,
         "d": body.dni_do_przegladu or 365, "id": tenant_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Nie znaleziono jednostki.")
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="TENANT_UPDATE", tabela_docelowa="tenants",
                rekord_id=tenant_id, nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.delete("/{tenant_id}")
async def delete_tenant(tenant_id: int, request: Request,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles("SUPERADMIN"))):
    session.execute(text("UPDATE tenants SET aktywny=0 WHERE id=:id"), {"id": tenant_id})
    session.commit()
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="TENANT_DEACTIVATE", tabela_docelowa="tenants",
                rekord_id=tenant_id, ip_adres=get_client_ip(request))
    return {"message": "Jednostka dezaktywowana."}
