from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, require_roles

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


@router.get("/systemy")
async def rejestr_systemow(tenant_id: Optional[int] = None, format: Optional[str] = None,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT s.id, s.nazwa, t.nazwa as tenant_nazwa, s.poziom_krytycznosci,
                  s.wlasciciel, s.aktywny, s.data_dodania,
                  COUNT(DISTINCT CASE WHEN up.aktywne=1 THEN up.pracownik_id END) as aktywni_uzytkownicy,
                  MAX(pr.data_zakonczenia) as ostatni_przeglad
             FROM systemy_it s
             LEFT JOIN tenants t ON t.id=s.tenant_id
             LEFT JOIN uprawnienia up ON up.system_id=s.id
             LEFT JOIN przeglady pr ON pr.tenant_id=s.tenant_id AND pr.status='ZAKOŃCZONY'
            WHERE s.aktywny=1"""
    params: dict = {}
    if tenant_id:
        q += " AND (s.tenant_id=:tid OR s.tenant_id IS NULL)"
        params["tid"] = tenant_id
    q += " GROUP BY s.id, t.nazwa ORDER BY s.poziom_krytycznosci DESC, s.nazwa"
    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]

    if format in ("xlsx", "csv"):
        from services.excel_service import send_xlsx, send_csv
        cols = [
            {"header": "System", "key": "nazwa"},
            {"header": "Jednostka", "key": "tenant_nazwa"},
            {"header": "Krytyczność", "key": "poziom_krytycznosci"},
            {"header": "Właściciel", "key": "wlasciciel"},
            {"header": "Aktywni użytkownicy", "key": "aktywni_uzytkownicy"},
            {"header": "Ostatni przegląd", "key": "ostatni_przeglad"},
            {"header": "Status", "key": "aktywny"},
        ]
        if format == "xlsx":
            return send_xlsx(data, cols, "Rejestr_systemow", "Systemy IT")
        return send_csv(data, cols, "Rejestr_systemow")
    return data


@router.get("/uprzywilejowani")
async def rejestr_uprzywilejowanych(tenant_id: Optional[int] = None, format: Optional[str] = None,
                                     session: Session = Depends(get_session),
                                     current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT up.id, up.data_od, up.aktywne,
                  u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                  t.nazwa as tenant_nazwa,
                  s.nazwa as system_nazwa,
                  z.nazwa as zakres_nazwa,
                  w.numer
             FROM uprawnienia up
             JOIN pracownicy p ON p.id=up.pracownik_id
             JOIN uzytkownicy u ON u.id=p.uzytkownik_id
             JOIN tenants t ON t.id=up.tenant_id
             JOIN systemy_it s ON s.id=up.system_id
             JOIN zakres_uprawnien z ON z.id=up.zakres_id
             LEFT JOIN wnioski w ON w.id=up.wniosek_id
            WHERE z.uprzywilejowany=1 AND up.aktywne=1"""
    params: dict = {}
    if tenant_id:
        q += " AND up.tenant_id=:tid"
        params["tid"] = tenant_id
    q += " ORDER BY t.nazwa, u.nazwisko"
    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]

    if format in ("xlsx", "csv"):
        from services.excel_service import send_xlsx, send_csv
        cols = [
            {"header": "Pracownik", "key": "pracownik_nazwa"},
            {"header": "Jednostka", "key": "tenant_nazwa"},
            {"header": "System", "key": "system_nazwa"},
            {"header": "Zakres", "key": "zakres_nazwa"},
            {"header": "Data nadania", "key": "data_od"},
            {"header": "Nr wniosku", "key": "numer"},
            {"header": "Aktywne", "key": "aktywne"},
        ]
        if format == "xlsx":
            return send_xlsx(data, cols, "Uprzywilejowani", "Uprzywilejowani")
        return send_csv(data, cols, "Uprzywilejowani")
    return data


@router.get("/przeglady")
async def rejestr_przeglady(tenant_id: Optional[int] = None, format: Optional[str] = None,
                             session: Session = Depends(get_session),
                             current_user: CurrentUser = Depends(require_roles(*IT))):
    q = """SELECT pr.id, pr.typ, pr.status, pr.data_rozpoczecia, pr.data_zakonczenia,
                  t.nazwa as tenant_nazwa,
                  u.imie || ' ' || u.nazwisko as inicjujacy_nazwa,
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
    q += " GROUP BY pr.id, t.nazwa, u.imie, u.nazwisko ORDER BY pr.data_rozpoczecia DESC"
    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]

    if format in ("xlsx", "csv"):
        from services.excel_service import send_xlsx, send_csv
        cols = [
            {"header": "Nr", "key": "id"},
            {"header": "Jednostka", "key": "tenant_nazwa"},
            {"header": "Typ", "key": "typ"},
            {"header": "Status", "key": "status"},
            {"header": "Data rozp.", "key": "data_rozpoczecia"},
            {"header": "Data zak.", "key": "data_zakonczenia"},
            {"header": "Inicjujący", "key": "inicjujacy_nazwa"},
            {"header": "Pozostaw", "key": "pozostaw"},
            {"header": "Cofnij", "key": "cofnij"},
            {"header": "Zmodyfikuj", "key": "zmodyfikuj"},
        ]
        if format == "xlsx":
            return send_xlsx(data, cols, "Rejestr_przeglady", "Przeglądy")
        return send_csv(data, cols, "Rejestr_przeglady")
    return data


@router.get("/audit")
async def rejestr_audit(tenant_id: Optional[int] = None, user_id: Optional[int] = None,
                         akcja: Optional[str] = None, tabela: Optional[str] = None,
                         from_: Optional[str] = None, to: Optional[str] = None,
                         page: int = 1, limit: int = 50, format: Optional[str] = None,
                         session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    offset = (page - 1) * limit
    q = """SELECT al.id, al.timestamp, al.akcja, al.tabela_docelowa, al.rekord_id,
                  al.username, al.rola, al.ip_adres,
                  t.nazwa as tenant_nazwa,
                  al.stare_dane, al.nowe_dane
             FROM audit_log al
             LEFT JOIN tenants t ON t.id=al.tenant_id
            WHERE 1=1"""
    params: dict = {}
    if tenant_id:
        q += " AND al.tenant_id=:tid"
        params["tid"] = tenant_id
    if user_id:
        q += " AND al.user_id=:uid"
        params["uid"] = user_id
    if akcja:
        q += " AND al.akcja LIKE :a"
        params["a"] = f"%{akcja}%"
    if tabela:
        q += " AND al.tabela_docelowa=:tab"
        params["tab"] = tabela
    if from_:
        q += " AND al.timestamp>=:fr"
        params["fr"] = from_
    if to:
        q += " AND al.timestamp<=:to"
        params["to"] = to
    q += " ORDER BY al.timestamp DESC"

    if format not in ("xlsx", "csv"):
        count_q = f"SELECT COUNT(*) as cnt FROM ({q}) sub"
        total_row = session.execute(text(count_q), params).mappings().first()
        total = total_row["cnt"] if total_row else 0
        params["lim"] = limit
        params["off"] = offset
        paged_q = q + " LIMIT :lim OFFSET :off"
        rows = session.execute(text(paged_q), params).mappings().all()
        return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    rows = session.execute(text(q), params).mappings().all()
    data = [dict(r) for r in rows]
    from services.excel_service import send_xlsx, send_csv
    cols = [
        {"header": "Timestamp", "key": "timestamp"},
        {"header": "Akcja", "key": "akcja"},
        {"header": "Użytkownik", "key": "username"},
        {"header": "Rola", "key": "rola"},
        {"header": "Tabela", "key": "tabela_docelowa"},
        {"header": "Rekord ID", "key": "rekord_id"},
        {"header": "Jednostka", "key": "tenant_nazwa"},
        {"header": "IP", "key": "ip_adres"},
    ]
    if format == "xlsx":
        return send_xlsx(data, cols, "Audit_log", "Audit Log")
    return send_csv(data, cols, "Audit_log")
