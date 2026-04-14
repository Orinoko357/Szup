from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip

router = APIRouter()


class PracownikIn(BaseModel):
    uzytkownik_id: int
    tenant_id: int
    komorka_id: Optional[int] = None
    stanowisko: Optional[str] = None
    data_zatrudnienia: Optional[str] = None
    data_zwolnienia: Optional[str] = None
    aktywny: Optional[bool] = True
    przelozony_id: Optional[int] = None


@router.get("/")
async def list_pracownicy(tenant_id: Optional[int] = None, komorka_id: Optional[int] = None,
                           aktywny: Optional[str] = None, q: Optional[str] = None,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(get_current_user)):
    query = """SELECT p.id, p.uzytkownik_id, p.tenant_id, p.komorka_id,
                      p.stanowisko, p.data_zatrudnienia, p.data_zwolnienia, p.aktywny,
                      p.przelozony_id,
                      u.imie, u.nazwisko, u.email, u.username, u.rola,
                      k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa,
                      pr.id as przel_id,
                      pu.imie || ' ' || pu.nazwisko as przel_nazwa
                 FROM pracownicy p
                 JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                 LEFT JOIN komorki_org k ON k.id=p.komorka_id
                 LEFT JOIN tenants t ON t.id=p.tenant_id
                 LEFT JOIN pracownicy pr ON pr.id=p.przelozony_id
                 LEFT JOIN uzytkownicy pu ON pu.id=pr.uzytkownik_id
                WHERE 1=1"""
    params: dict = {}

    effective_tenant = tenant_id
    if current_user.rola in ("KIEROWNIK", "PRACOWNIK"):
        effective_tenant = effective_tenant or current_user.tenantId

    if effective_tenant:
        query += " AND p.tenant_id=:tid"
        params["tid"] = effective_tenant
    if komorka_id:
        query += " AND p.komorka_id=:kid"
        params["kid"] = komorka_id
    if aktywny is not None:
        query += " AND p.aktywny=:a"
        params["a"] = aktywny == "true"
    if q:
        query += " AND (u.imie LIKE :q OR u.nazwisko LIKE :q OR u.email LIKE :q)"
        params["q"] = f"%{q}%"

    query += " ORDER BY u.nazwisko, u.imie"
    rows = session.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/:id/podwladni", include_in_schema=False)
@router.get("/{prac_id}/podwladni")
async def get_podwladni(prac_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(get_current_user)):
    rows = session.execute(
        text("""SELECT p.id, u.imie, u.nazwisko, u.email, p.stanowisko, k.nazwa as komorka_nazwa,
                       p.aktywny,
                       (SELECT COUNT(*) FROM uprawnienia up WHERE up.pracownik_id=p.id AND up.aktywne=1) as liczba_uprawnien
                  FROM pracownicy p
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  LEFT JOIN komorki_org k ON k.id=p.komorka_id
                 WHERE p.przelozony_id=:id AND p.aktywny=1
                 ORDER BY u.nazwisko"""),
        {"id": prac_id},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{prac_id}")
async def get_pracownik(prac_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("""SELECT p.*, u.imie, u.nazwisko, u.email, u.username, u.rola,
                       k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa,
                       pu.imie || ' ' || pu.nazwisko as przel_nazwa,
                       pr.stanowisko as przel_stanowisko
                  FROM pracownicy p
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  LEFT JOIN komorki_org k ON k.id=p.komorka_id
                  LEFT JOIN tenants t ON t.id=p.tenant_id
                  LEFT JOIN pracownicy pr ON pr.id=p.przelozony_id
                  LEFT JOIN uzytkownicy pu ON pu.id=pr.uzytkownik_id
                 WHERE p.id=:id"""),
        {"id": prac_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Pracownik nie istnieje.")
    result = dict(row)
    cnt = session.execute(
        text("SELECT COUNT(*) as cnt FROM uprawnienia WHERE pracownik_id=:id AND aktywne=1"),
        {"id": prac_id},
    ).mappings().first()
    result["liczba_uprawnien"] = cnt["cnt"] if cnt else 0
    return result


@router.post("/", status_code=201)
async def create_pracownik(body: PracownikIn, request: Request,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN", "KADRY"))):
    row = session.execute(
        text("INSERT INTO pracownicy (uzytkownik_id,tenant_id,komorka_id,stanowisko,data_zatrudnienia,przelozony_id) VALUES (:uid,:tid,:kid,:s,:d,:p) RETURNING *"),
        {"uid": body.uzytkownik_id, "tid": body.tenant_id, "kid": body.komorka_id,
         "s": body.stanowisko, "d": body.data_zatrudnienia, "p": body.przelozony_id},
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="PRACOWNIK_CREATE", tabela_docelowa="pracownicy",
                rekord_id=result["id"], nowe_dane=body.model_dump(), ip_adres=get_client_ip(request))
    return result


@router.put("/{prac_id}")
async def update_pracownik(prac_id: int, body: PracownikIn, request: Request,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN", "KADRY"))):
    old = session.execute(text("SELECT * FROM pracownicy WHERE id=:id"), {"id": prac_id}).mappings().first()
    if not old:
        raise HTTPException(status_code=404, detail="Pracownik nie istnieje.")
    old = dict(old)

    row = session.execute(
        text("UPDATE pracownicy SET komorka_id=:kid, stanowisko=:s, data_zatrudnienia=:dt, data_zwolnienia=:dz, aktywny=:a, przelozony_id=:p WHERE id=:id RETURNING *"),
        {"kid": body.komorka_id, "s": body.stanowisko, "dt": body.data_zatrudnienia,
         "dz": body.data_zwolnienia, "a": body.aktywny if body.aktywny is not None else True,
         "p": body.przelozony_id, "id": prac_id},
    ).mappings().first()
    session.commit()
    result = dict(row)

    if body.data_zwolnienia and not old.get("data_zwolnienia"):
        write_audit(session, user_id=current_user.userId, username=current_user.username,
                    rola=current_user.rola, akcja="PRACOWNIK_ODEJSCIE", tabela_docelowa="pracownicy",
                    rekord_id=prac_id, nowe_dane={"data_zwolnienia": body.data_zwolnienia},
                    ip_adres=get_client_ip(request))

    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="PRACOWNIK_UPDATE", tabela_docelowa="pracownicy",
                rekord_id=prac_id, nowe_dane=body.model_dump(), stare_dane=old,
                ip_adres=get_client_ip(request))
    return result
