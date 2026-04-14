from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip

router = APIRouter()


class NadajIn(BaseModel):
    pracownik_id: int
    system_id: int
    modul_id: Optional[int] = None
    zakres_id: int
    uzasadnienie: Optional[str] = None
    data_od: Optional[str] = None
    data_do: Optional[str] = None


class CofnijIn(BaseModel):
    powod: str


class MasoweCofniecieIn(BaseModel):
    pracownik_id: int
    powod: str


FETCH_Q = """SELECT up.id, up.aktywne, up.nadane_bezposrednio, up.data_od, up.data_do,
                    up.data_cofniecia, up.powod_cofniecia, up.wymaga_przegladu,
                    up.data_ostatniego_przegladu, up.wynik_przegladu,
                    u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                    t.nazwa as tenant_nazwa,
                    s.nazwa as system_nazwa,
                    m.nazwa as modul_nazwa,
                    z.nazwa as zakres_nazwa, z.uprzywilejowany,
                    w.numer,
                    un.username as nadane_przez_nazwa
               FROM uprawnienia up
               JOIN pracownicy p ON p.id=up.pracownik_id
               JOIN uzytkownicy u ON u.id=p.uzytkownik_id
               JOIN tenants t ON t.id=up.tenant_id
               JOIN systemy_it s ON s.id=up.system_id
               LEFT JOIN modul_systemu m ON m.id=up.modul_id
               JOIN zakres_uprawnien z ON z.id=up.zakres_id
               LEFT JOIN wnioski w ON w.id=up.wniosek_id
               LEFT JOIN uzytkownicy un ON un.id=up.nadane_przez
              WHERE 1=1"""


@router.get("")
async def list_uprawnienia(tenant_id: Optional[int] = None, pracownik_id: Optional[int] = None,
                            system_id: Optional[int] = None, aktywne: Optional[str] = None,
                            uprzywilejowany: Optional[str] = None, format: Optional[str] = None,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(get_current_user)):
    q = FETCH_Q
    params: dict = {}
    if tenant_id:
        q += " AND up.tenant_id=:tid"
        params["tid"] = tenant_id
    if pracownik_id:
        q += " AND up.pracownik_id=:pid"
        params["pid"] = pracownik_id
    if system_id:
        q += " AND up.system_id=:sid"
        params["sid"] = system_id
    if aktywne is not None:
        q += " AND up.aktywne=:a"
        params["a"] = aktywne == "true"
    if uprzywilejowany == "true":
        q += " AND z.uprzywilejowany=1"
    q += " ORDER BY t.nazwa, u.nazwisko, s.nazwa"

    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]

    if format in ("xlsx", "csv"):
        from services.excel_service import send_xlsx, send_csv
        cols = [
            {"header": "Pracownik", "key": "pracownik_nazwa"},
            {"header": "Jednostka", "key": "tenant_nazwa"},
            {"header": "System", "key": "system_nazwa"},
            {"header": "Moduł", "key": "modul_nazwa"},
            {"header": "Zakres", "key": "zakres_nazwa"},
            {"header": "Uprzywilejowany", "key": "uprzywilejowany"},
            {"header": "Data nadania", "key": "data_od"},
            {"header": "Nr wniosku", "key": "numer"},
            {"header": "Nadane bezpośrednio", "key": "nadane_bezposrednio"},
            {"header": "Aktywne", "key": "aktywne"},
            {"header": "Data cofnięcia", "key": "data_cofniecia"},
        ]
        if format == "xlsx":
            return send_xlsx(data, cols, "Rejestr_uprawnien", "Uprawnienia")
        return send_csv(data, cols, "Rejestr_uprawnien")

    return data


@router.get("/{uprawnienie_id}")
async def get_uprawnienie(uprawnienie_id: int, session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(get_current_user)):
    q = FETCH_Q + " AND up.id=:id"
    row = session.execute(text(q), {"id": uprawnienie_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Uprawnienie nie istnieje.")
    return dict(row)


@router.post("/nadaj-bezposrednio", status_code=201)
async def nadaj_bezposrednio(body: NadajIn, request: Request,
                              session: Session = Depends(get_session),
                              current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    prac = session.execute(
        text("SELECT tenant_id FROM pracownicy WHERE id=:id"),
        {"id": body.pracownik_id},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=404, detail="Pracownik nie istnieje.")

    now = datetime.utcnow()
    row = session.execute(
        text("INSERT INTO uprawnienia (tenant_id,pracownik_id,system_id,modul_id,zakres_id,nadane_bezposrednio,nadane_przez,data_od,data_do) VALUES (:tid,:pid,:sid,:mid,:zid,1,:np,:dt,:ddo) RETURNING *"),
        {"tid": prac["tenant_id"], "pid": body.pracownik_id, "sid": body.system_id,
         "mid": body.modul_id, "zid": body.zakres_id, "np": current_user.userId,
         "dt": body.data_od or now.date().isoformat(), "ddo": body.data_do},
    ).mappings().first()
    session.commit()
    result = dict(row)

    akcja = "NADANIE_BEZPOSREDNIE_SUPERADMIN" if current_user.rola == "SUPERADMIN" else "NADANIE_BEZPOSREDNIE_IT"
    write_audit(session, tenant_id=prac["tenant_id"], user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola, akcja=akcja,
                tabela_docelowa="uprawnienia", rekord_id=result["id"],
                nowe_dane={"pracownik_id": body.pracownik_id, "system_id": body.system_id,
                           "zakres_id": body.zakres_id, "uzasadnienie": body.uzasadnienie},
                ip_adres=get_client_ip(request))
    return result


@router.post("/{uprawnienie_id}/cofnij")
async def cofnij(uprawnienie_id: int, body: CofnijIn, request: Request,
                  session: Session = Depends(get_session),
                  current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    row = session.execute(
        text("UPDATE uprawnienia SET aktywne=0, data_cofniecia=:dt, cofniete_przez=:uid, powod_cofniecia=:p WHERE id=:id RETURNING *"),
        {"dt": datetime.utcnow(), "uid": current_user.userId, "p": body.powod, "id": uprawnienie_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Uprawnienie nie istnieje.")
    write_audit(session, tenant_id=row["tenant_id"], user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="UPRAWNIENIE_COFNIETE", tabela_docelowa="uprawnienia", rekord_id=uprawnienie_id,
                nowe_dane={"powod": body.powod}, ip_adres=get_client_ip(request))
    return {"message": "Uprawnienie cofnięte."}


@router.post("/masowe-cofniecie")
async def masowe_cofniecie(body: MasoweCofniecieIn, request: Request,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    result = session.execute(
        text("UPDATE uprawnienia SET aktywne=0, data_cofniecia=:dt, cofniete_przez=:uid, powod_cofniecia=:p WHERE pracownik_id=:pid AND aktywne=1"),
        {"dt": datetime.utcnow(), "uid": current_user.userId, "p": body.powod, "pid": body.pracownik_id},
    )
    session.commit()
    count = result.rowcount
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="MASOWE_COFNIECIE", tabela_docelowa="uprawnienia",
                nowe_dane={"pracownik_id": body.pracownik_id, "powod": body.powod, "liczba": count},
                ip_adres=get_client_ip(request))
    return {"message": f"Cofnięto {count} uprawnień."}
