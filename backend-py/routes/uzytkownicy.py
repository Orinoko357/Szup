from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class UzytkownikIn(BaseModel):
    username: str
    imie: str
    nazwisko: str
    email: str
    rola: str
    tenant_id: Optional[int] = None
    aktywny: Optional[bool] = True


class UzytkownikUpdate(BaseModel):
    imie: Optional[str] = None
    nazwisko: Optional[str] = None
    email: Optional[str] = None
    rola: Optional[str] = None
    tenant_id: Optional[int] = None
    aktywny: Optional[bool] = True


class BlokadaIn(BaseModel):
    zablokowany: bool


@router.get("/")
async def list_uzytkownicy(tenant_id: Optional[int] = None, rola: Optional[str] = None,
                            aktywny: Optional[str] = None,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT u.id, u.username, u.imie, u.nazwisko, u.email, u.rola,
                  u.tenant_id, u.aktywny, u.data_utworzenia, u.ostatnie_logowanie,
                  u.nieudane_logowania, u.zablokowany_do, t.nazwa as tenant_nazwa
             FROM uzytkownicy u LEFT JOIN tenants t ON t.id=u.tenant_id WHERE 1=1"""
    params = {}
    if tenant_id:
        q += " AND u.tenant_id=:tid"
        params["tid"] = tenant_id
    if rola:
        q += " AND u.rola=:rola"
        params["rola"] = rola
    if aktywny is not None:
        q += " AND u.aktywny=:a"
        params["a"] = aktywny == "true"
    q += " ORDER BY u.nazwisko, u.imie"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{user_id}")
async def get_uzytkownik(user_id: int, session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("""SELECT u.*, t.nazwa as tenant_nazwa, p.id as pracownik_id, p.stanowisko, p.komorka_id
                  FROM uzytkownicy u LEFT JOIN tenants t ON t.id=u.tenant_id
                  LEFT JOIN pracownicy p ON p.uzytkownik_id=u.id WHERE u.id=:id"""),
        {"id": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")
    return dict(row)


@router.post("/", status_code=201)
async def create_uzytkownik(body: UzytkownikIn, request: Request,
                             session: Session = Depends(get_session),
                             current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("INSERT INTO uzytkownicy (username,imie,nazwisko,email,rola,tenant_id,data_utworzenia,aktywny,wymagaj_zmiany_hasla,nieudane_logowania) VALUES (:u,:i,:n,:e,:r,:t,:dt,1,1,0) RETURNING id,username,imie,nazwisko,email,rola,tenant_id"),
        {"u": body.username, "i": body.imie, "n": body.nazwisko, "e": body.email,
         "r": body.rola, "t": body.tenant_id, "dt": datetime.utcnow()},
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="UZYTKOWNIK_CREATE", tabela_docelowa="uzytkownicy",
                rekord_id=result["id"], nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.put("/{user_id}")
async def update_uzytkownik(user_id: int, body: UzytkownikUpdate, request: Request,
                             session: Session = Depends(get_session),
                             current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE uzytkownicy SET imie=:i, nazwisko=:n, email=:e, rola=:r, tenant_id=:t, aktywny=:a WHERE id=:id RETURNING id,username,imie,nazwisko,email,rola,tenant_id,aktywny"),
        {"i": body.imie, "n": body.nazwisko, "e": body.email, "r": body.rola,
         "t": body.tenant_id, "a": body.aktywny if body.aktywny is not None else True, "id": user_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="UZYTKOWNIK_UPDATE", tabela_docelowa="uzytkownicy",
                rekord_id=user_id, nowe_dane=body.model_dump(), ip_adres=get_client_ip(request))
    return result


@router.patch("/{user_id}/blokada")
async def blokada(user_id: int, body: BlokadaIn, request: Request,
                  session: Session = Depends(get_session),
                  current_user: CurrentUser = Depends(require_roles(*IT))):
    if body.zablokowany:
        session.execute(text("UPDATE uzytkownicy SET aktywny=0, zablokowany_do=NULL WHERE id=:id"), {"id": user_id})
    else:
        session.execute(text("UPDATE uzytkownicy SET aktywny=1, nieudane_logowania=0, zablokowany_do=NULL WHERE id=:id"), {"id": user_id})
    session.commit()
    akcja = "UZYTKOWNIK_BLOCK" if body.zablokowany else "UZYTKOWNIK_UNBLOCK"
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja=akcja, tabela_docelowa="uzytkownicy",
                rekord_id=user_id, ip_adres=get_client_ip(request))
    return {"message": "Konto zablokowane." if body.zablokowany else "Konto odblokowane."}


@router.post("/{user_id}/revoke-tokens")
async def revoke_tokens(user_id: int, request: Request,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    session.execute(text("UPDATE refresh_tokens SET odwolany=1 WHERE user_id=:id"), {"id": user_id})
    session.commit()
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="TOKENY_UNIEWAZNIENIE", tabela_docelowa="uzytkownicy",
                rekord_id=user_id, ip_adres=get_client_ip(request))
    return {"message": "Tokeny unieważnione."}
