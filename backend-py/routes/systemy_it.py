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


class SystemIn(BaseModel):
    tenant_id: Optional[int] = None
    nazwa: str
    opis: Optional[str] = None
    wlasciciel: Optional[str] = None
    poziom_krytycznosci: str = "NORMALNY"
    aktywny: Optional[bool] = True


class ModulIn(BaseModel):
    nazwa: str
    opis: Optional[str] = None
    aktywny: Optional[bool] = True


class ZakresIn(BaseModel):
    nazwa: str
    opis: Optional[str] = None
    modul_id: Optional[int] = None
    uprzywilejowany: Optional[bool] = False


@router.get("/")
async def list_systemy(tenant_id: Optional[int] = None,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(get_current_user)):
    q = """SELECT s.*, u.imie || ' ' || u.nazwisko as dodany_przez_nazwa,
                  COUNT(DISTINCT z.id) as liczba_zakresow
             FROM systemy_it s
             LEFT JOIN uzytkownicy u ON u.id=s.dodany_przez
             LEFT JOIN zakres_uprawnien z ON z.system_id=s.id
            WHERE s.aktywny=1"""
    params = {}
    if tenant_id:
        q += " AND (s.tenant_id=:tid OR s.tenant_id IS NULL)"
        params["tid"] = tenant_id
    q += " GROUP BY s.id, u.imie, u.nazwisko ORDER BY s.nazwa"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{system_id}")
async def get_system(system_id: int, session: Session = Depends(get_session),
                      current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(text("SELECT * FROM systemy_it WHERE id=:id"), {"id": system_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="System nie istnieje.")
    result = dict(row)
    moduly = session.execute(text("SELECT * FROM modul_systemu WHERE system_id=:id ORDER BY nazwa"), {"id": system_id}).mappings().all()
    zakresy = session.execute(
        text("SELECT z.*, m.nazwa as modul_nazwa FROM zakres_uprawnien z LEFT JOIN modul_systemu m ON m.id=z.modul_id WHERE z.system_id=:id ORDER BY z.nazwa"),
        {"id": system_id},
    ).mappings().all()
    result["moduly"] = [dict(m) for m in moduly]
    result["zakresy"] = [dict(z) for z in zakresy]
    return result


@router.post("/", status_code=201)
async def create_system(body: SystemIn, request: Request,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("INSERT INTO systemy_it (tenant_id,nazwa,opis,wlasciciel,poziom_krytycznosci,dodany_przez,data_dodania) VALUES (:tid,:n,:o,:w,:pk,:dp,:dd) RETURNING *"),
        {"tid": body.tenant_id, "n": body.nazwa, "o": body.opis, "w": body.wlasciciel,
         "pk": body.poziom_krytycznosci, "dp": current_user.userId, "dd": datetime.utcnow()},
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="SYSTEM_IT_CREATE", tabela_docelowa="systemy_it",
                rekord_id=result["id"], nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.put("/{system_id}")
async def update_system(system_id: int, body: SystemIn, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE systemy_it SET nazwa=:n, opis=:o, wlasciciel=:w, poziom_krytycznosci=:pk, aktywny=:a, tenant_id=:tid WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "o": body.opis, "w": body.wlasciciel, "pk": body.poziom_krytycznosci,
         "a": body.aktywny if body.aktywny is not None else True, "tid": body.tenant_id, "id": system_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="System nie istnieje.")
    return dict(row)


@router.post("/{system_id}/moduly", status_code=201)
async def create_modul(system_id: int, body: ModulIn, session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("INSERT INTO modul_systemu (system_id,nazwa,opis) VALUES (:sid,:n,:o) RETURNING *"),
        {"sid": system_id, "n": body.nazwa, "o": body.opis},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/moduly/{modul_id}")
async def update_modul(modul_id: int, body: ModulIn, session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE modul_systemu SET nazwa=:n, opis=:o, aktywny=:a WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "o": body.opis, "a": body.aktywny if body.aktywny is not None else True, "id": modul_id},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.post("/{system_id}/zakresy", status_code=201)
async def create_zakres(system_id: int, body: ZakresIn, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("INSERT INTO zakres_uprawnien (system_id,modul_id,nazwa,opis,uprzywilejowany) VALUES (:sid,:mid,:n,:o,:u) RETURNING *"),
        {"sid": system_id, "mid": body.modul_id, "n": body.nazwa, "o": body.opis, "u": body.uprzywilejowany or False},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/zakresy/{zakres_id}")
async def update_zakres(zakres_id: int, body: ZakresIn, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE zakres_uprawnien SET nazwa=:n, opis=:o, modul_id=:mid, uprzywilejowany=:u WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "o": body.opis, "mid": body.modul_id, "u": body.uprzywilejowany or False, "id": zakres_id},
    ).mappings().first()
    session.commit()
    return dict(row)
