from __future__ import annotations
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from schemas import BaseSchema
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip
from services.workflow_service import resolve_szablon

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class SzablonIn(BaseSchema):
    tenant_id: int
    nazwa: str
    opis: Optional[str] = None
    aktywny: Optional[bool] = True


class SzablonUpdate(BaseSchema):
    nazwa: Optional[str] = None
    opis: Optional[str] = None
    aktywny: Optional[bool] = True


class PoziomIn(BaseSchema):
    kolejnosc: int
    nazwa: Optional[str] = None
    zatwierdzajacy_id: Optional[int] = None
    opcjonalny: Optional[bool] = False
    opis_warunku_pominiecia: Optional[str] = None
    przypomnienie_dni: Optional[int] = 3
    eskalacja_dni: Optional[int] = 7


class ReorderItem(BaseSchema):
    id: int
    kolejnosc: int


class ReorderIn(BaseSchema):
    kolejnosci: List[ReorderItem]


class PrzypisanieIn(BaseSchema):
    szablon_id: int
    typ: str
    komorka_id: Optional[int] = None
    tenant_id: Optional[int] = None


# ===== SZABLONY =====

@router.get("/szablony")
async def list_szablony(tenant_id: Optional[int] = None,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(get_current_user)):
    q = """SELECT ws.*, t.nazwa as tenant_nazwa,
                  COUNT(DISTINCT wp.id) as liczba_przypisań,
                  COUNT(DISTINCT wl.id) as liczba_poziomow
             FROM workflow_szablony ws
             LEFT JOIN tenants t ON t.id=ws.tenant_id
             LEFT JOIN workflow_przypisania wp ON wp.szablon_id=ws.id
             LEFT JOIN workflow_poziomy wl ON wl.szablon_id=ws.id
            WHERE ws.aktywny=1"""
    params = {}
    if tenant_id:
        q += " AND ws.tenant_id=:tid"
        params["tid"] = tenant_id
    q += " GROUP BY ws.id, t.nazwa ORDER BY ws.tenant_id, ws.nazwa"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/szablony/{szablon_id}")
async def get_szablon(szablon_id: int, session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("SELECT ws.*, t.nazwa as tenant_nazwa FROM workflow_szablony ws LEFT JOIN tenants t ON t.id=ws.tenant_id WHERE ws.id=:id"),
        {"id": szablon_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Szablon nie istnieje.")
    result = dict(row)
    poziomy = session.execute(
        text("""SELECT wl.*, u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa, p.stanowisko as zatwierdzajacy_stanowisko
                  FROM workflow_poziomy wl
                  LEFT JOIN pracownicy p ON p.id=wl.zatwierdzajacy_id
                  LEFT JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                 WHERE wl.szablon_id=:id ORDER BY wl.kolejnosc"""),
        {"id": szablon_id},
    ).mappings().all()
    result["poziomy"] = [dict(p) for p in poziomy]
    return result


@router.post("/szablony", status_code=201)
async def create_szablon(body: SzablonIn, request: Request,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("INSERT INTO workflow_szablony (tenant_id,nazwa,opis,aktywny,utworzony_przez,data_utworzenia) VALUES (:tid,:n,:o,1,:up,:dt) RETURNING *"),
        {"tid": body.tenant_id, "n": body.nazwa, "o": body.opis, "up": current_user.userId, "dt": datetime.utcnow()},
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="WORKFLOW_SZABLON_CREATE", tabela_docelowa="workflow_szablony",
                rekord_id=result["id"], nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.put("/szablony/{szablon_id}")
async def update_szablon(szablon_id: int, body: SzablonUpdate,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    if body.aktywny is False:
        cnt = session.execute(
            text("SELECT COUNT(*) as cnt FROM wnioski WHERE szablon_id=:id AND status IN ('W_TOKU','OCZEKUJE_IT')"),
            {"id": szablon_id},
        ).mappings().first()
        if cnt and cnt["cnt"] > 0:
            raise HTTPException(status_code=400, detail="Szablon jest używany przez wnioski w toku. Nie można dezaktywować.")
    row = session.execute(
        text("UPDATE workflow_szablony SET nazwa=:n, opis=:o, aktywny=:a WHERE id=:id RETURNING *"),
        {"n": body.nazwa, "o": body.opis, "a": body.aktywny if body.aktywny is not None else True, "id": szablon_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Szablon nie istnieje.")
    return dict(row)


@router.delete("/szablony/{szablon_id}")
async def delete_szablon(szablon_id: int, session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    assigned = session.execute(
        text("SELECT COUNT(*) as cnt FROM workflow_przypisania WHERE szablon_id=:id"),
        {"id": szablon_id},
    ).mappings().first()
    if assigned and assigned["cnt"] > 0:
        raise HTTPException(status_code=400, detail=f"Szablon jest przypisany do {assigned['cnt']} komórek. Najpierw zmień przypisania.")
    in_prog = session.execute(
        text("SELECT COUNT(*) as cnt FROM wnioski WHERE szablon_id=:id AND status IN ('W_TOKU','OCZEKUJE_IT')"),
        {"id": szablon_id},
    ).mappings().first()
    if in_prog and in_prog["cnt"] > 0:
        raise HTTPException(status_code=400, detail="Szablon jest używany przez wnioski w toku.")
    session.execute(text("DELETE FROM workflow_szablony WHERE id=:id"), {"id": szablon_id})
    session.commit()
    return {"message": "Szablon usunięty."}


# ===== POZIOMY =====

@router.get("/szablony/{szablon_id}/poziomy")
async def list_poziomy(szablon_id: int, session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(get_current_user)):
    rows = session.execute(
        text("""SELECT wl.*, u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa, p.stanowisko as zatwierdzajacy_stanowisko
                  FROM workflow_poziomy wl
                  LEFT JOIN pracownicy p ON p.id=wl.zatwierdzajacy_id
                  LEFT JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                 WHERE wl.szablon_id=:id ORDER BY wl.kolejnosc"""),
        {"id": szablon_id},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/szablony/{szablon_id}/poziomy", status_code=201)
async def create_poziom(szablon_id: int, body: PoziomIn,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    if body.eskalacja_dni and body.przypomnienie_dni and body.eskalacja_dni < body.przypomnienie_dni:
        raise HTTPException(status_code=422, detail="Dni eskalacji muszą być >= dni przypomnienia.")
    row = session.execute(
        text("""INSERT INTO workflow_poziomy (szablon_id,kolejnosc,nazwa,zatwierdzajacy_id,opcjonalny,
                opis_warunku_pominiecia,przypomnienie_dni,eskalacja_dni) VALUES (:sid,:k,:n,:z,:o,:op,:r,:e) RETURNING *"""),
        {"sid": szablon_id, "k": body.kolejnosc, "n": body.nazwa, "z": body.zatwierdzajacy_id,
         "o": 1 if body.opcjonalny else 0, "op": body.opis_warunku_pominiecia,
         "r": body.przypomnienie_dni or 3, "e": body.eskalacja_dni or 7},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/poziomy/{poziom_id}")
async def update_poziom(poziom_id: int, body: PoziomIn,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    if body.eskalacja_dni and body.przypomnienie_dni and body.eskalacja_dni < body.przypomnienie_dni:
        raise HTTPException(status_code=422, detail="Dni eskalacji muszą być >= dni przypomnienia.")
    row = session.execute(
        text("""UPDATE workflow_poziomy SET nazwa=:n, zatwierdzajacy_id=:z, opcjonalny=:o,
                opis_warunku_pominiecia=:op, przypomnienie_dni=:r, eskalacja_dni=:e WHERE id=:id RETURNING *"""),
        {"n": body.nazwa, "z": body.zatwierdzajacy_id, "o": body.opcjonalny or False,
         "op": body.opis_warunku_pominiecia, "r": body.przypomnienie_dni or 3, "e": body.eskalacja_dni or 7,
         "id": poziom_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Poziom nie istnieje.")
    return dict(row)


@router.delete("/poziomy/{poziom_id}")
async def delete_poziom(poziom_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    session.execute(text("DELETE FROM workflow_poziomy WHERE id=:id"), {"id": poziom_id})
    session.commit()
    return {"message": "Poziom usunięty."}


@router.patch("/szablony/{szablon_id}/poziomy/reorder")
async def reorder_poziomy(szablon_id: int, body: ReorderIn,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles(*IT))):
    for item in body.kolejnosci:
        session.execute(
            text("UPDATE workflow_poziomy SET kolejnosc=:k WHERE id=:id AND szablon_id=:sid"),
            {"k": item.kolejnosc, "id": item.id, "sid": szablon_id},
        )
    session.commit()
    return {"message": "Kolejność zaktualizowana."}


# ===== PRZYPISANIA =====

@router.get("/przypisania")
async def list_przypisania(tenant_id: Optional[int] = None,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(get_current_user)):
    q = """SELECT wp.*, ws.nazwa as szablon_nazwa, k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa
             FROM workflow_przypisania wp
             JOIN workflow_szablony ws ON ws.id=wp.szablon_id
             LEFT JOIN komorki_org k ON k.id=wp.komorka_id
             LEFT JOIN tenants t ON t.id=wp.tenant_id
            WHERE 1=1"""
    params = {}
    if tenant_id:
        q += " AND wp.tenant_id=:tid"
        params["tid"] = tenant_id
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.put("/przypisania")
async def upsert_przypisanie(body: PrzypisanieIn,
                              session: Session = Depends(get_session),
                              current_user: CurrentUser = Depends(require_roles(*IT))):
    if body.typ == "KOMORKA" and body.komorka_id:
        existing = session.execute(
            text("SELECT id FROM workflow_przypisania WHERE komorka_id=:kid"),
            {"kid": body.komorka_id},
        ).mappings().first()
        if existing:
            session.execute(
                text("UPDATE workflow_przypisania SET szablon_id=:sid WHERE komorka_id=:kid"),
                {"sid": body.szablon_id, "kid": body.komorka_id},
            )
        else:
            session.execute(
                text("INSERT INTO workflow_przypisania (szablon_id,typ,komorka_id,tenant_id) VALUES (:sid,'KOMORKA',:kid,:tid)"),
                {"sid": body.szablon_id, "kid": body.komorka_id, "tid": body.tenant_id},
            )
    elif body.typ == "TENANT_DEFAULT" and body.tenant_id:
        existing = session.execute(
            text("SELECT id FROM workflow_przypisania WHERE typ='TENANT_DEFAULT' AND tenant_id=:tid"),
            {"tid": body.tenant_id},
        ).mappings().first()
        if existing:
            session.execute(
                text("UPDATE workflow_przypisania SET szablon_id=:sid WHERE typ='TENANT_DEFAULT' AND tenant_id=:tid"),
                {"sid": body.szablon_id, "tid": body.tenant_id},
            )
        else:
            session.execute(
                text("INSERT INTO workflow_przypisania (szablon_id,typ,tenant_id) VALUES (:sid,'TENANT_DEFAULT',:tid)"),
                {"sid": body.szablon_id, "tid": body.tenant_id},
            )
    session.commit()
    return {"message": "Przypisanie zaktualizowane."}


@router.get("/resolve/{pracownik_id}")
async def resolve_for_pracownik(pracownik_id: int,
                                 session: Session = Depends(get_session),
                                 current_user: CurrentUser = Depends(get_current_user)):
    try:
        result = resolve_szablon(pracownik_id, session)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
