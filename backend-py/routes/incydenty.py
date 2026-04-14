from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, require_roles, write_audit, get_client_ip
from services.notification_service import notify_it

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class IncydentIn(BaseModel):
    tenant_id: int
    tytul: str
    opis: Optional[str] = None
    typ: str
    poziom: str = "NISKI"
    dotyczy_nis2: Optional[bool] = False


class IncydentUpdate(BaseModel):
    tytul: str
    opis: Optional[str] = None
    typ: str
    poziom: str
    status: str
    dzialania_naprawcze: Optional[str] = None
    dotyczy_nis2: Optional[bool] = False


@router.get("/")
async def list_incydenty(tenant_id: Optional[int] = None, status: Optional[str] = None,
                          format: Optional[str] = None,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT ri.*, t.nazwa as tenant_nazwa, u.imie || ' ' || u.nazwisko as zglaszajacy_nazwa
             FROM rejestr_incydentow ri
             JOIN tenants t ON t.id=ri.tenant_id
             JOIN uzytkownicy u ON u.id=ri.zglaszajacy_id
            WHERE 1=1"""
    params: dict = {}
    if tenant_id:
        q += " AND ri.tenant_id=:tid"
        params["tid"] = tenant_id
    if status:
        q += " AND ri.status=:s"
        params["s"] = status
    q += " ORDER BY ri.data_zgloszenia DESC"
    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]

    if format in ("xlsx", "csv"):
        from services.excel_service import send_xlsx, send_csv
        cols = [
            {"header": "Tytuł", "key": "tytul"},
            {"header": "Jednostka", "key": "tenant_nazwa"},
            {"header": "Typ", "key": "typ"},
            {"header": "Poziom", "key": "poziom"},
            {"header": "Status", "key": "status"},
            {"header": "Data zgłoszenia", "key": "data_zgloszenia"},
            {"header": "NIS2", "key": "dotyczy_nis2"},
            {"header": "Zgłaszający", "key": "zglaszajacy_nazwa"},
        ]
        if format == "xlsx":
            return send_xlsx(data, cols, "Rejestr_incydentow", "Incydenty")
        return send_csv(data, cols, "Rejestr_incydentow")

    return data


@router.get("/{incydent_id}")
async def get_incydent(incydent_id: int, session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("SELECT ri.*, t.nazwa as tenant_nazwa, u.imie || ' ' || u.nazwisko as zglaszajacy_nazwa FROM rejestr_incydentow ri JOIN tenants t ON t.id=ri.tenant_id JOIN uzytkownicy u ON u.id=ri.zglaszajacy_id WHERE ri.id=:id"),
        {"id": incydent_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Incydent nie istnieje.")
    return dict(row)


@router.post("/", status_code=201)
async def create_incydent(body: IncydentIn, request: Request,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("INSERT INTO rejestr_incydentow (tenant_id,tytul,opis,typ,poziom,zglaszajacy_id,dotyczy_nis2,data_zgloszenia) VALUES (:tid,:t,:o,:typ,:p,:uid,:n,:dt) RETURNING *"),
        {"tid": body.tenant_id, "t": body.tytul, "o": body.opis, "typ": body.typ,
         "p": body.poziom, "uid": current_user.userId, "n": body.dotyczy_nis2 or False,
         "dt": datetime.utcnow()},
    ).mappings().first()
    session.commit()
    result = dict(row)
    notify_it("NOWY_INCYDENT", f"Nowy incydent: {body.tytul} ({body.poziom})",
              f"/incydenty/{result['id']}", session)
    write_audit(session, tenant_id=body.tenant_id, user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="INCYDENT_UTWORZONO", tabela_docelowa="rejestr_incydentow", rekord_id=result["id"],
                nowe_dane=result, ip_adres=get_client_ip(request))
    return result


@router.put("/{incydent_id}")
async def update_incydent(incydent_id: int, body: IncydentUpdate,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import datetime
    row = session.execute(
        text("""UPDATE rejestr_incydentow SET tytul=:t, opis=:o, typ=:typ, poziom=:p, status=:s,
                dzialania_naprawcze=:d, dotyczy_nis2=:n,
                data_zamkniecia=CASE WHEN :s='ZAMKNIETY' THEN :dt ELSE data_zamkniecia END
                WHERE id=:id RETURNING *"""),
        {"t": body.tytul, "o": body.opis, "typ": body.typ, "p": body.poziom, "s": body.status,
         "d": body.dzialania_naprawcze, "n": body.dotyczy_nis2 or False,
         "dt": datetime.utcnow(), "id": incydent_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Incydent nie istnieje.")
    return dict(row)


@router.delete("/{incydent_id}")
async def delete_incydent(incydent_id: int, session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles("SUPERADMIN"))):
    session.execute(text("DELETE FROM rejestr_incydentow WHERE id=:id"), {"id": incydent_id})
    session.commit()
    return {"message": "Incydent usunięty."}
