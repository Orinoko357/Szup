from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from schemas import BaseSchema
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip

router = APIRouter()

# Columns used to build a display name — falls back to p.imie/nazwisko when no account
_NAME_COLS = """
    COALESCE(u.imie,     p.imie)     AS imie,
    COALESCE(u.nazwisko, p.nazwisko) AS nazwisko,
    COALESCE(u.email,    p.email)    AS email,
    u.username, u.rola
"""


class PracownikIn(BaseSchema):
    uzytkownik_id: Optional[int] = None   # null => pracownik bez konta systemowego
    tenant_id: int
    jednostka_id: Optional[int] = None
    stanowisko: Optional[str] = None
    # used when uzytkownik_id is None
    imie: Optional[str] = None
    nazwisko: Optional[str] = None
    email: Optional[str] = None
    data_zatrudnienia: Optional[str] = None
    data_zwolnienia: Optional[str] = None
    aktywny: Optional[bool] = True
    przelozony_id: Optional[int] = None


@router.get("")
async def list_pracownicy(tenant_id: Optional[int] = None, jednostka_id: Optional[int] = None,
                           aktywny: Optional[str] = None, q: Optional[str] = None,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(get_current_user)):
    query = f"""SELECT p.id, p.uzytkownik_id, p.tenant_id, p.jednostka_id,
                      p.stanowisko, p.data_zatrudnienia, p.data_zwolnienia, p.aktywny,
                      p.przelozony_id,
                      {_NAME_COLS},
                      j.nazwa as jednostka_nazwa, t.nazwa as tenant_nazwa,
                      pr.id as przel_id,
                      COALESCE(pu.imie, prd.imie) || ' ' || COALESCE(pu.nazwisko, prd.nazwisko) as przel_nazwa
                 FROM pracownicy p
                 LEFT JOIN uzytkownicy u   ON u.id  = p.uzytkownik_id
                 LEFT JOIN jednostki_org j ON j.id  = p.jednostka_id
                 LEFT JOIN tenants t        ON t.id  = p.tenant_id
                 LEFT JOIN pracownicy pr    ON pr.id = p.przelozony_id
                 LEFT JOIN uzytkownicy pu   ON pu.id = pr.uzytkownik_id
                 LEFT JOIN pracownicy prd   ON prd.id = pr.id
                WHERE 1=1"""
    params: dict = {}

    effective_tenant = tenant_id
    if current_user.rola in ("KIEROWNIK", "PRACOWNIK"):
        effective_tenant = effective_tenant or current_user.tenantId

    if effective_tenant:
        query += " AND p.tenant_id=:tid"
        params["tid"] = effective_tenant
    if jednostka_id:
        query += " AND p.jednostka_id=:jid"
        params["jid"] = jednostka_id
    if aktywny is not None:
        query += " AND p.aktywny=:a"
        params["a"] = aktywny == "true"
    if q:
        query += """ AND (COALESCE(u.imie,p.imie) LIKE :q
                       OR COALESCE(u.nazwisko,p.nazwisko) LIKE :q
                       OR COALESCE(u.email,p.email) LIKE :q)"""
        params["q"] = f"%{q}%"

    query += " ORDER BY COALESCE(u.nazwisko,p.nazwisko), COALESCE(u.imie,p.imie)"
    rows = session.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/:id/podwladni", include_in_schema=False)
@router.get("/{prac_id}/podwladni")
async def get_podwladni(prac_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(get_current_user)):
    rows = session.execute(
        text(f"""SELECT p.id, {_NAME_COLS}, p.stanowisko, j.nazwa as jednostka_nazwa,
                       p.aktywny,
                       (SELECT COUNT(*) FROM uprawnienia up WHERE up.pracownik_id=p.id AND up.aktywne=1) as liczba_uprawnien
                  FROM pracownicy p
                  LEFT JOIN uzytkownicy u   ON u.id = p.uzytkownik_id
                  LEFT JOIN jednostki_org j ON j.id = p.jednostka_id
                 WHERE p.przelozony_id=:id AND p.aktywny=1
                 ORDER BY COALESCE(u.nazwisko, p.nazwisko)"""),
        {"id": prac_id},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{prac_id}")
async def get_pracownik(prac_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text(f"""SELECT p.*, {_NAME_COLS},
                       j.nazwa as jednostka_nazwa, t.nazwa as tenant_nazwa,
                       COALESCE(pu.imie,prd.imie) || ' ' || COALESCE(pu.nazwisko,prd.nazwisko) as przel_nazwa,
                       pr.stanowisko as przel_stanowisko
                  FROM pracownicy p
                  LEFT JOIN uzytkownicy u   ON u.id  = p.uzytkownik_id
                  LEFT JOIN jednostki_org j ON j.id  = p.jednostka_id
                  LEFT JOIN tenants t        ON t.id  = p.tenant_id
                  LEFT JOIN pracownicy pr    ON pr.id = p.przelozony_id
                  LEFT JOIN uzytkownicy pu   ON pu.id = pr.uzytkownik_id
                  LEFT JOIN pracownicy prd   ON prd.id = pr.id
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


@router.post("", status_code=201)
async def create_pracownik(body: PracownikIn, request: Request,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN", "KADRY"))):
    if not body.uzytkownik_id and not body.imie:
        raise HTTPException(status_code=422, detail="Podaj imię i nazwisko lub powiąż konto użytkownika.")
    row = session.execute(
        text("""INSERT INTO pracownicy
                    (uzytkownik_id, tenant_id, jednostka_id, stanowisko,
                     imie, nazwisko, email,
                     data_zatrudnienia, przelozony_id, aktywny)
                VALUES (:uid,:tid,:jid,:s,:imie,:nazwisko,:email,:d,:p,1) RETURNING *"""),
        {"uid": body.uzytkownik_id, "tid": body.tenant_id, "jid": body.jednostka_id,
         "s": body.stanowisko,
         "imie": body.imie, "nazwisko": body.nazwisko, "email": body.email,
         "d": body.data_zatrudnienia, "p": body.przelozony_id},
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
        text("""UPDATE pracownicy
                   SET jednostka_id=:jid, stanowisko=:s,
                       imie=:imie, nazwisko=:nazwisko, email=:email,
                       data_zatrudnienia=:dt, data_zwolnienia=:dz,
                       aktywny=:a, przelozony_id=:p
                 WHERE id=:id RETURNING *"""),
        {"jid": body.jednostka_id, "s": body.stanowisko,
         "imie": body.imie, "nazwisko": body.nazwisko, "email": body.email,
         "dt": body.data_zatrudnienia, "dz": body.data_zwolnienia,
         "a": body.aktywny if body.aktywny is not None else True,
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
