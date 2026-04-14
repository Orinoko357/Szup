from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, require_roles, write_audit, get_client_ip

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class PrzegladIn(BaseModel):
    tenant_id: int
    typ: str
    uwagi: Optional[str] = None
    pracownik_id: Optional[int] = None
    system_id: Optional[int] = None
    komorka_id: Optional[int] = None


class DecyzjaIn(BaseModel):
    decyzja: str
    uzasadnienie: str


@router.get("/")
async def list_przeglady(tenant_id: Optional[int] = None, status: Optional[str] = None,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT pr.*, t.nazwa as tenant_nazwa, u.imie || ' ' || u.nazwisko as inicjujacy_nazwa,
                  COUNT(pp.id) as liczba_pozycji,
                  COUNT(CASE WHEN pp.decyzja='POZOSTAW' THEN 1 END) as pozostaw,
                  COUNT(CASE WHEN pp.decyzja='COFNIJ' THEN 1 END) as cofnij,
                  COUNT(CASE WHEN pp.decyzja='ZMODYFIKUJ' THEN 1 END) as zmodyfikuj
             FROM przeglady pr
             JOIN tenants t ON t.id=pr.tenant_id
             JOIN uzytkownicy u ON u.id=pr.inicjujacy_id
             LEFT JOIN pozycje_przegladu pp ON pp.przeglad_id=pr.id
            WHERE 1=1"""
    params: dict = {}
    if tenant_id:
        q += " AND pr.tenant_id=:tid"
        params["tid"] = tenant_id
    if status:
        q += " AND pr.status=:s"
        params["s"] = status
    q += " GROUP BY pr.id, t.nazwa, u.imie, u.nazwisko ORDER BY pr.data_rozpoczecia DESC"
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{przeglad_id}")
async def get_przeglad(przeglad_id: int, session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("""SELECT pr.*, t.nazwa as tenant_nazwa, u.imie || ' ' || u.nazwisko as inicjujacy_nazwa
                  FROM przeglady pr
                  JOIN tenants t ON t.id=pr.tenant_id
                  JOIN uzytkownicy u ON u.id=pr.inicjujacy_id
                 WHERE pr.id=:id"""),
        {"id": przeglad_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Przegląd nie istnieje.")
    result = dict(row)

    pozycje = session.execute(
        text("""SELECT pp.*, u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                       s.nazwa as system_nazwa, z.nazwa as zakres_nazwa, z.uprzywilejowany,
                       ud.imie || ' ' || ud.nazwisko as decydent_nazwa
                  FROM pozycje_przegladu pp
                  JOIN uprawnienia up ON up.id=pp.uprawnienie_id
                  JOIN pracownicy p ON p.id=pp.pracownik_id
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  JOIN systemy_it s ON s.id=up.system_id
                  JOIN zakres_uprawnien z ON z.id=up.zakres_id
                  LEFT JOIN uzytkownicy ud ON ud.id=pp.decydent_id
                 WHERE pp.przeglad_id=:id ORDER BY u.nazwisko, s.nazwa"""),
        {"id": przeglad_id},
    ).mappings().all()
    result["pozycje"] = [dict(p) for p in pozycje]
    return result


@router.post("/", status_code=201)
async def create_przeglad(body: PrzegladIn, request: Request,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    now = datetime.utcnow()
    pr_row = session.execute(
        text("INSERT INTO przeglady (tenant_id,typ,inicjujacy_id,uwagi,data_rozpoczecia) VALUES (:tid,:t,:iid,:u,:dt) RETURNING *"),
        {"tid": body.tenant_id, "t": body.typ, "iid": current_user.userId, "u": body.uwagi, "dt": now},
    ).mappings().first()
    session.commit()
    przeglad = dict(pr_row)

    q = "SELECT up.id, up.pracownik_id FROM uprawnienia up JOIN pracownicy p ON p.id=up.pracownik_id WHERE up.aktywne=1 AND up.tenant_id=:tid"
    params: dict = {"tid": body.tenant_id}
    if body.pracownik_id:
        q += " AND up.pracownik_id=:pid"
        params["pid"] = body.pracownik_id
    if body.system_id:
        q += " AND up.system_id=:sid"
        params["sid"] = body.system_id
    if body.komorka_id:
        q += " AND p.komorka_id=:kid"
        params["kid"] = body.komorka_id

    ups = session.execute(text(q), params).mappings().all()
    for up in ups:
        session.execute(
            text("INSERT INTO pozycje_przegladu (przeglad_id,uprawnienie_id,pracownik_id) VALUES (:prid,:uid,:pid)"),
            {"prid": przeglad["id"], "uid": up["id"], "pid": up["pracownik_id"]},
        )
    session.commit()

    write_audit(session, tenant_id=body.tenant_id, user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="PRZEGLAD_INICJOWANY", tabela_docelowa="przeglady", rekord_id=przeglad["id"],
                nowe_dane={"typ": body.typ, "liczba_pozycji": len(ups)}, ip_adres=get_client_ip(request))
    przeglad["liczba_pozycji"] = len(ups)
    return przeglad


@router.patch("/pozycje/{pozycja_id}/decyzja")
async def decyzja(pozycja_id: int, body: DecyzjaIn, request: Request,
                   session: Session = Depends(get_session),
                   current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("UPDATE pozycje_przegladu SET decyzja=:d, uzasadnienie=:u, data_decyzji=:dt, decydent_id=:did WHERE id=:id RETURNING *"),
        {"d": body.decyzja, "u": body.uzasadnienie, "dt": datetime.utcnow(), "did": current_user.userId, "id": pozycja_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Pozycja nie istnieje.")
    session.commit()
    result = dict(row)

    if body.decyzja == "COFNIJ":
        session.execute(
            text("UPDATE uprawnienia SET aktywne=0, data_cofniecia=:dt, cofniete_przez=:uid, powod_cofniecia=:u WHERE id=:id"),
            {"dt": datetime.utcnow(), "uid": current_user.userId, "u": body.uzasadnienie, "id": result["uprawnienie_id"]},
        )
        session.execute(
            text("UPDATE uprawnienia SET wynik_przegladu='COFNIJ', data_ostatniego_przegladu=:dt, wymaga_przegladu=0 WHERE id=:id"),
            {"dt": datetime.utcnow().date(), "id": result["uprawnienie_id"]},
        )
    else:
        session.execute(
            text("UPDATE uprawnienia SET wynik_przegladu=:d, data_ostatniego_przegladu=:dt, wymaga_przegladu=0 WHERE id=:id"),
            {"d": body.decyzja, "dt": datetime.utcnow().date(), "id": result["uprawnienie_id"]},
        )
    session.commit()
    return result


@router.post("/{przeglad_id}/zakoncz")
async def zakoncz(przeglad_id: int, session: Session = Depends(get_session),
                   current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("UPDATE przeglady SET status='ZAKOŃCZONY', data_zakonczenia=:dt WHERE id=:id RETURNING *"),
        {"dt": datetime.utcnow(), "id": przeglad_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Przegląd nie istnieje.")
    return dict(row)


@router.post("/{przeglad_id}/anuluj")
async def anuluj(przeglad_id: int, session: Session = Depends(get_session),
                  current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("UPDATE przeglady SET status='ANULOWANY', data_zakonczenia=:dt WHERE id=:id RETURNING *"),
        {"dt": datetime.utcnow(), "id": przeglad_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Przegląd nie istnieje.")
    return dict(row)
