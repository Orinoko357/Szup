from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from schemas import BaseSchema
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, get_client_ip, write_audit

router = APIRouter()
ADMIN = ("IT_ADMIN", "SUPERADMIN", "KADRY")


class JednostkaIn(BaseSchema):
    tenant_id: int
    nazwa: str
    typ: Optional[str] = "WYDZIAL"
    nadrzedny_id: Optional[int] = None
    kierownik_id: Optional[int] = None
    kolejnosc: Optional[int] = 0
    aktywna: Optional[bool] = True


@router.get("")
async def list_jednostki(
    tenant_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Zwraca płaską listę jednostek wraz z danymi kierownika i liczbą pracowników."""
    q = """
        SELECT j.*,
               t.nazwa  AS tenant_nazwa,
               u.imie   AS kier_imie,
               u.nazwisko AS kier_nazwisko,
               p.stanowisko AS kier_stanowisko,
               (SELECT COUNT(*) FROM pracownicy pr
                 WHERE pr.jednostka_id = j.id AND pr.aktywny = 1) AS liczba_pracownikow
          FROM jednostki_org j
          JOIN tenants t ON t.id = j.tenant_id
          LEFT JOIN pracownicy p  ON p.id = j.kierownik_id
          LEFT JOIN uzytkownicy u ON u.id = p.uzytkownik_id
         WHERE j.aktywna = 1
    """
    params: dict = {}
    if tenant_id:
        q += " AND j.tenant_id = :tid"
        params["tid"] = tenant_id
    elif current_user.rola not in ("SUPERADMIN",) and current_user.tenantId:
        q += " AND j.tenant_id = :tid"
        params["tid"] = current_user.tenantId
    q += " ORDER BY j.tenant_id, j.kolejnosc, j.nazwa"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{jed_id}/pracownicy")
async def get_pracownicy_jednostki(
    jed_id: int,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = session.execute(
        text("""
            SELECT p.id, p.stanowisko, p.aktywny,
                   u.imie, u.nazwisko, u.email,
                   p.id = j.kierownik_id AS jest_kierownikiem
              FROM pracownicy p
              JOIN uzytkownicy u ON u.id = p.uzytkownik_id
              JOIN jednostki_org j ON j.id = p.jednostka_id
             WHERE p.jednostka_id = :jid AND p.aktywny = 1
             ORDER BY u.nazwisko, u.imie
        """),
        {"jid": jed_id},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_jednostka(
    body: JednostkaIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles(*ADMIN)),
):
    row = session.execute(
        text("""
            INSERT INTO jednostki_org
                (tenant_id, nazwa, typ, nadrzedny_id, kierownik_id, kolejnosc, aktywna)
            VALUES (:tid, :n, :t, :nad, :kier, :k, 1)
            RETURNING *
        """),
        {
            "tid": body.tenant_id, "n": body.nazwa, "t": body.typ or "WYDZIAL",
            "nad": body.nadrzedny_id, "kier": body.kierownik_id, "k": body.kolejnosc or 0,
        },
    ).mappings().first()
    session.commit()
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="JEDNOSTKA_CREATE",
                tabela_docelowa="jednostki_org", rekord_id=result["id"],
                nowe_dane=body.model_dump(), ip_adres=get_client_ip(request))
    return result


@router.put("/{jed_id}")
async def update_jednostka(
    jed_id: int,
    body: JednostkaIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles(*ADMIN)),
):
    row = session.execute(
        text("""
            UPDATE jednostki_org
               SET nazwa=:n, typ=:t, nadrzedny_id=:nad,
                   kierownik_id=:kier, kolejnosc=:k, aktywna=:a
             WHERE id=:id
            RETURNING *
        """),
        {
            "n": body.nazwa, "t": body.typ or "WYDZIAL", "nad": body.nadrzedny_id,
            "kier": body.kierownik_id, "k": body.kolejnosc or 0,
            "a": body.aktywna if body.aktywna is not None else True, "id": jed_id,
        },
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Jednostka nie istnieje.")
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="JEDNOSTKA_UPDATE",
                tabela_docelowa="jednostki_org", rekord_id=jed_id,
                nowe_dane=body.model_dump(), ip_adres=get_client_ip(request))
    return dict(row)


@router.delete("/{jed_id}")
async def delete_jednostka(
    jed_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(require_roles(*ADMIN)),
):
    # Check for children
    children = session.execute(
        text("SELECT COUNT(*) as cnt FROM jednostki_org WHERE nadrzedny_id=:id AND aktywna=1"),
        {"id": jed_id},
    ).mappings().first()
    if children and children["cnt"] > 0:
        raise HTTPException(status_code=400, detail="Jednostka ma podjednostki — usuń je najpierw.")

    employees = session.execute(
        text("SELECT COUNT(*) as cnt FROM pracownicy WHERE jednostka_id=:id AND aktywny=1"),
        {"id": jed_id},
    ).mappings().first()
    if employees and employees["cnt"] > 0:
        raise HTTPException(status_code=400, detail="Jednostka ma przypisanych pracowników.")

    session.execute(text("UPDATE jednostki_org SET aktywna=0 WHERE id=:id"), {"id": jed_id})
    session.commit()
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="JEDNOSTKA_DELETE",
                tabela_docelowa="jednostki_org", rekord_id=jed_id,
                ip_adres=get_client_ip(request))
    return {"message": "Jednostka dezaktywowana."}
