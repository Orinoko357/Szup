from __future__ import annotations
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user, require_roles, write_audit, get_client_ip
from services.workflow_service import (
    submit_wniosek,
    zatwierdz,
    odrzuc,
    odeslij,
    pomin_etap,
)

router = APIRouter()


class PozycjaIn(BaseModel):
    system_id: int
    modul_id: Optional[int] = None
    zakres_id: int
    uzasadnienie: Optional[str] = None


class WniosekIn(BaseModel):
    pracownik_id: int
    pozycje: List[PozycjaIn]
    uwagi_inicjujacego: Optional[str] = None
    zloz: Optional[bool] = False


class ZatwierdzIn(BaseModel):
    etap_kolejnosc: int
    komentarz: Optional[str] = None


class OdrzucIn(BaseModel):
    etap_kolejnosc: int
    powod: str


class OdeslijIn(BaseModel):
    etap_kolejnosc: int
    komentarz: str


class PominIn(BaseModel):
    etap_kolejnosc: int
    powod: str


class ZrealizujIn(BaseModel):
    uwagi: Optional[str] = None
    pozycje_do_usuniecia: Optional[List[int]] = []


class ItOdrzucIn(BaseModel):
    powod: str


class PozycjaUpdate(BaseModel):
    zakres_id: Optional[int] = None
    uzasadnienie: Optional[str] = None


@router.get("/moje/do-zatwierdzenia")
async def moje_do_zatwierdzenia(session: Session = Depends(get_session),
                                  current_user: CurrentUser = Depends(get_current_user)):
    prac = session.execute(
        text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not prac:
        return []
    rows = session.execute(
        text("""SELECT w.id, w.numer, w.status, w.data_ostatniej_zmiany,
                       we.kolejnosc as etap_kolejnosc, we.nazwa as etap_nazwa, we.data_przypisania,
                       u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                       t.nazwa as tenant_nazwa, t.skrot
                  FROM wnioski_etapy we
                  JOIN wnioski w ON w.id=we.wniosek_id
                  JOIN pracownicy p ON p.id=w.pracownik_id
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  JOIN tenants t ON t.id=w.tenant_id
                 WHERE we.zatwierdzajacy_id=:pid AND we.status='OCZEKUJE'
                   AND w.status='W_TOKU'
                 ORDER BY we.data_przypisania"""),
        {"pid": prac["id"]},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/")
async def list_wnioski(status: Optional[str] = None, tenant_id: Optional[int] = None,
                        pracownik_id: Optional[int] = None, page: int = 1, limit: int = 20,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(get_current_user)):
    offset = (page - 1) * limit
    q = """SELECT w.id, w.numer, w.status, w.data_utworzenia, w.data_ostatniej_zmiany,
                  w.aktualny_etap_kolejnosc, w.tenant_id,
                  u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                  ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa,
                  t.nazwa as tenant_nazwa, t.skrot as tenant_skrot,
                  COUNT(poz.id) as liczba_pozycji
             FROM wnioski w
             JOIN pracownicy p ON p.id=w.pracownik_id
             JOIN uzytkownicy u ON u.id=p.uzytkownik_id
             JOIN pracownicy pi ON pi.id=w.inicjujacy_id
             JOIN uzytkownicy ui ON ui.id=pi.uzytkownik_id
             JOIN tenants t ON t.id=w.tenant_id
             LEFT JOIN pozycje_wniosku poz ON poz.wniosek_id=w.id
            WHERE 1=1"""
    params: dict = {}

    if current_user.rola in ("KIEROWNIK", "PRACOWNIK"):
        prac = session.execute(
            text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
            {"uid": current_user.userId},
        ).mappings().first()
        if prac:
            q += " AND (w.inicjujacy_id=:pid OR w.pracownik_id=:pid)"
            params["pid"] = prac["id"]
        params["ttid"] = current_user.tenantId
        q += " AND w.tenant_id=:ttid"
    elif current_user.rola not in ("SUPERADMIN", "IT_ADMIN", "KADRY"):
        raise HTTPException(status_code=403, detail="Brak uprawnień.")

    if tenant_id and current_user.rola in ("IT_ADMIN", "SUPERADMIN"):
        q += " AND w.tenant_id=:tid"
        params["tid"] = tenant_id
    if status:
        q += " AND w.status=:status"
        params["status"] = status
    if pracownik_id:
        q += " AND w.pracownik_id=:wpid"
        params["wpid"] = pracownik_id

    q += " GROUP BY w.id, u.imie, u.nazwisko, ui.imie, ui.nazwisko, t.nazwa, t.skrot"
    q += " ORDER BY w.data_ostatniej_zmiany DESC"

    count_q = f"SELECT COUNT(*) as cnt FROM ({q}) sub"
    total_row = session.execute(text(count_q), params).mappings().first()
    total = total_row["cnt"] if total_row else 0

    q += f" LIMIT :lim OFFSET :off"
    params["lim"] = limit
    params["off"] = offset
    rows = session.execute(text(q), params).mappings().all()
    return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.get("/{wniosek_id}")
async def get_wniosek(wniosek_id: int, session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("""SELECT w.*, t.nazwa as tenant_nazwa,
                       u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                       p.stanowisko, k.nazwa as komorka_nazwa,
                       ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa
                  FROM wnioski w
                  JOIN pracownicy p ON p.id=w.pracownik_id
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  LEFT JOIN komorki_org k ON k.id=p.komorka_id
                  JOIN tenants t ON t.id=w.tenant_id
                  JOIN pracownicy pi ON pi.id=w.inicjujacy_id
                  JOIN uzytkownicy ui ON ui.id=pi.uzytkownik_id
                 WHERE w.id=:id"""),
        {"id": wniosek_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    result = dict(row)

    pozycje = session.execute(
        text("""SELECT poz.*, s.nazwa as system_nazwa, m.nazwa as modul_nazwa,
                       z.nazwa as zakres_nazwa, z.uprzywilejowany
                  FROM pozycje_wniosku poz
                  JOIN systemy_it s ON s.id=poz.system_id
                  LEFT JOIN modul_systemu m ON m.id=poz.modul_id
                  JOIN zakres_uprawnien z ON z.id=poz.zakres_id
                 WHERE poz.wniosek_id=:id ORDER BY s.nazwa"""),
        {"id": wniosek_id},
    ).mappings().all()

    etapy = session.execute(
        text("""SELECT we.*, u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
                       pz.stanowisko as zatwierdzajacy_stanowisko
                  FROM wnioski_etapy we
                  LEFT JOIN pracownicy pz ON pz.id=we.zatwierdzajacy_id
                  LEFT JOIN uzytkownicy u ON u.id=pz.uzytkownik_id
                 WHERE we.wniosek_id=:id ORDER BY we.kolejnosc"""),
        {"id": wniosek_id},
    ).mappings().all()

    result["pozycje"] = [dict(p) for p in pozycje]
    result["etapy"] = [dict(e) for e in etapy]
    return result


@router.post("/", status_code=201)
async def create_wniosek(body: WniosekIn, request: Request,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    inic = session.execute(
        text("SELECT id, tenant_id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not inic:
        raise HTTPException(status_code=403, detail="Nie masz profilu pracownika.")

    prac = session.execute(
        text("SELECT tenant_id FROM pracownicy WHERE id=:id"),
        {"id": body.pracownik_id},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=404, detail="Pracownik nie istnieje.")
    effective_tenant = prac["tenant_id"]

    now = datetime.utcnow()
    row = session.execute(
        text("INSERT INTO wnioski (tenant_id,pracownik_id,inicjujacy_id,status,uwagi_inicjujacego,data_utworzenia,data_ostatniej_zmiany) VALUES (:tid,:pid,:iid,'SZKIC',:u,:dt,:dt) RETURNING *"),
        {"tid": effective_tenant, "pid": body.pracownik_id, "iid": inic["id"],
         "u": body.uwagi_inicjujacego, "dt": now},
    ).mappings().first()
    session.commit()
    wniosek_id = row["id"]

    for p in body.pozycje:
        session.execute(
            text("INSERT INTO pozycje_wniosku (wniosek_id,system_id,modul_id,zakres_id,uzasadnienie,dodana_przez) VALUES (:wid,:sid,:mid,:zid,:u,:dp)"),
            {"wid": wniosek_id, "sid": p.system_id, "mid": p.modul_id,
             "zid": p.zakres_id, "u": p.uzasadnienie, "dp": current_user.userId},
        )
    session.commit()

    write_audit(session, tenant_id=effective_tenant, user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="WNIOSEK_UTWORZONO", tabela_docelowa="wnioski", rekord_id=wniosek_id,
                nowe_dane={"pracownik_id": body.pracownik_id, "pozycje": len(body.pozycje)},
                ip_adres=get_client_ip(request))

    if body.zloz:
        try:
            submit_wniosek(wniosek_id, current_user.userId, session)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    final = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    return dict(final)


@router.post("/{wniosek_id}/submit")
async def submit(wniosek_id: int, session: Session = Depends(get_session),
                  current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    try:
        result = submit_wniosek(wniosek_id, current_user.userId, session)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wniosek_id}/zatwierdz")
async def zatwierdz_route(wniosek_id: int, body: ZatwierdzIn,
                           session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    prac = session.execute(
        text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=403, detail="Brak profilu pracownika.")
    try:
        return zatwierdz(wniosek_id, body.etap_kolejnosc, prac["id"], body.komentarz, current_user, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wniosek_id}/odrzuc")
async def odrzuc_route(wniosek_id: int, body: OdrzucIn,
                        session: Session = Depends(get_session),
                        current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    prac = session.execute(
        text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=403, detail="Brak profilu pracownika.")
    try:
        return odrzuc(wniosek_id, body.etap_kolejnosc, prac["id"], body.powod, current_user, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wniosek_id}/odeslij")
async def odeslij_route(wniosek_id: int, body: OdeslijIn,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    prac = session.execute(
        text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=403, detail="Brak profilu pracownika.")
    try:
        return odeslij(wniosek_id, body.etap_kolejnosc, prac["id"], body.komentarz, current_user, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wniosek_id}/pomin")
async def pomin_route(wniosek_id: int, body: PominIn,
                       session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    prac = session.execute(
        text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=403, detail="Brak profilu pracownika.")
    try:
        return pomin_etap(wniosek_id, body.etap_kolejnosc, prac["id"], body.powod, current_user, session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{wniosek_id}/zrealizuj")
async def zrealizuj(wniosek_id: int, body: ZrealizujIn, request: Request,
                     session: Session = Depends(get_session),
                     current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    w = dict(w)
    if w["status"] != "OCZEKUJE_IT":
        raise HTTPException(status_code=400, detail="Wniosek nie oczekuje na realizację IT.")

    pozycje = session.execute(
        text("SELECT poz.*, z.uprzywilejowany FROM pozycje_wniosku poz JOIN zakres_uprawnien z ON z.id=poz.zakres_id WHERE poz.wniosek_id=:id"),
        {"id": wniosek_id},
    ).mappings().all()

    now = datetime.utcnow()
    for p in pozycje:
        p = dict(p)
        if body.pozycje_do_usuniecia and p["id"] in body.pozycje_do_usuniecia:
            continue
        up_row = session.execute(
            text("INSERT INTO uprawnienia (tenant_id,pracownik_id,system_id,modul_id,zakres_id,wniosek_id,nadane_przez,data_od) VALUES (:tid,:pid,:sid,:mid,:zid,:wid,:np,:dt) RETURNING id"),
            {"tid": w["tenant_id"], "pid": w["pracownik_id"], "sid": p["system_id"],
             "mid": p["modul_id"], "zid": p["zakres_id"], "wid": w["id"],
             "np": current_user.userId, "dt": now},
        ).mappings().first()
        if p.get("uprzywilejowany"):
            write_audit(session, tenant_id=w["tenant_id"], user_id=current_user.userId,
                        username=current_user.username, rola=current_user.rola,
                        akcja="NADANIE_UPRZYWILEJOWANEGO", tabela_docelowa="uprawnienia",
                        rekord_id=up_row["id"], ip_adres=get_client_ip(request))

    session.execute(
        text("UPDATE wnioski SET status='ZREALIZOWANY', zrealizowal_it_id=:uid, data_realizacji=:dt, uwagi_realizacji=:u, data_ostatniej_zmiany=:dt WHERE id=:id"),
        {"uid": current_user.userId, "dt": now, "u": body.uwagi, "id": wniosek_id},
    )
    session.commit()

    inic_user = session.execute(
        text("SELECT u.id as uid FROM pracownicy p JOIN uzytkownicy u ON u.id=p.uzytkownik_id WHERE p.id=:pid"),
        {"pid": w["inicjujacy_id"]},
    ).mappings().first()
    if inic_user:
        from services.notification_service import create_notification
        create_notification(inic_user["uid"], "WNIOSEK_ZREALIZOWANY",
                            f"Wniosek {w.get('numer')} został zrealizowany. Uprawnienia zostały nadane.",
                            f"/wnioski/{wniosek_id}", session)

    write_audit(session, tenant_id=w["tenant_id"], user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="WNIOSEK_REALIZACJA", tabela_docelowa="wnioski", rekord_id=wniosek_id,
                nowe_dane={"uwagi": body.uwagi}, ip_adres=get_client_ip(request))
    return {"message": "Wniosek zrealizowany. Uprawnienia nadane."}


@router.post("/{wniosek_id}/it-odrzuc")
async def it_odrzuc(wniosek_id: int, body: ItOdrzucIn, request: Request,
                     session: Session = Depends(get_session),
                     current_user: CurrentUser = Depends(require_roles("IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    session.execute(
        text("UPDATE wnioski SET status='ODRZUCONY', odrzucil_id=:uid, data_odrzucenia=:dt, powod_odrzucenia=:p, data_ostatniej_zmiany=:dt WHERE id=:id"),
        {"uid": current_user.userId, "dt": datetime.utcnow(), "p": body.powod, "id": wniosek_id},
    )
    session.commit()
    write_audit(session, tenant_id=w["tenant_id"], user_id=current_user.userId,
                username=current_user.username, rola=current_user.rola,
                akcja="WNIOSEK_IT_ODRZUCONY", tabela_docelowa="wnioski", rekord_id=wniosek_id,
                nowe_dane={"powod": body.powod}, ip_adres=get_client_ip(request))
    return {"message": "Wniosek odrzucony."}


@router.get("/{wniosek_id}/pdf")
async def get_pdf(wniosek_id: int, session: Session = Depends(get_session),
                   current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("SELECT pdf_sciezka, numer, tenant_id FROM wnioski WHERE id=:id"),
        {"id": wniosek_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    row = dict(row)
    pdf_path = row.get("pdf_sciezka")
    if not pdf_path or not os.path.exists(pdf_path):
        from services.pdf_service import generate_wniosek_pdf
        try:
            pdf_path = generate_wniosek_pdf(wniosek_id, current_user, session)
        except Exception as e:
            raise HTTPException(status_code=500, detail="Nie można wygenerować PDF.")
    numer = (row.get("numer") or str(wniosek_id)).replace("/", "_")
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"{numer}.pdf",
                        headers={"Content-Disposition": f"inline; filename={numer}.pdf"})


@router.put("/{wniosek_id}/pozycje/{poz_id}")
async def update_pozycja(wniosek_id: int, poz_id: int, body: PozycjaUpdate, request: Request,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    from datetime import datetime
    row = session.execute(
        text("UPDATE pozycje_wniosku SET zakres_id=:zid, uzasadnienie=:u, zmodyfikowana_przez=:uid, data_modyfikacji=:dt WHERE id=:pid AND wniosek_id=:wid RETURNING *"),
        {"zid": body.zakres_id, "u": body.uzasadnienie, "uid": current_user.userId,
         "dt": datetime.utcnow(), "pid": poz_id, "wid": wniosek_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Pozycja nie istnieje.")
    result = dict(row)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="EDYCJA_POZYCJI_PRZEZ_ZATWIERDZAJACEGO",
                tabela_docelowa="pozycje_wniosku", rekord_id=poz_id,
                nowe_dane=body.model_dump(), ip_adres=get_client_ip(request))
    return result


@router.delete("/{wniosek_id}/pozycje/{poz_id}")
async def delete_pozycja(wniosek_id: int, poz_id: int, request: Request,
                          session: Session = Depends(get_session),
                          current_user: CurrentUser = Depends(require_roles("KIEROWNIK", "IT_ADMIN", "SUPERADMIN"))):
    row = session.execute(
        text("DELETE FROM pozycje_wniosku WHERE id=:pid AND wniosek_id=:wid RETURNING id"),
        {"pid": poz_id, "wid": wniosek_id},
    ).mappings().first()
    session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Pozycja nie istnieje.")
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="USUNIECIE_POZYCJI_PRZEZ_ZATWIERDZAJACEGO",
                tabela_docelowa="pozycje_wniosku", rekord_id=poz_id,
                ip_adres=get_client_ip(request))
    return {"message": "Pozycja usunięta."}
