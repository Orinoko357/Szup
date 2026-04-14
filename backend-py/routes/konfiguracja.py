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


class NumeracjaIn(BaseModel):
    format_szablonu: str
    prefix: str
    szerokosc_sekwencji: int
    reset_co: str


class PlatformaIn(BaseModel):
    wartosc: Optional[str] = None


@router.get("/numeracja")
async def get_numeracja(session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(text("SELECT * FROM konfiguracja_numeracji LIMIT 1")).mappings().first()
    return dict(row) if row else {}


@router.put("/numeracja")
async def update_numeracja(body: NumeracjaIn, request: Request,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(
        text("UPDATE konfiguracja_numeracji SET format_szablonu=:f, prefix=:p, szerokosc_sekwencji=:s, reset_co=:r WHERE id=1 RETURNING *"),
        {"f": body.format_szablonu, "p": body.prefix, "s": body.szerokosc_sekwencji, "r": body.reset_co},
    ).mappings().first()
    session.commit()
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="NUMERACJA_AKTUALIZACJA",
                tabela_docelowa="konfiguracja_numeracji", nowe_dane=body.model_dump(),
                ip_adres=get_client_ip(request))
    return dict(row)


@router.post("/numeracja/reset")
async def reset_numeracja(request: Request, session: Session = Depends(get_session),
                           current_user: CurrentUser = Depends(require_roles(*IT))):
    from datetime import date
    session.execute(
        text("UPDATE konfiguracja_numeracji SET ostatni_numer=0, ostatni_reset=:d WHERE id=1"),
        {"d": date.today().isoformat()},
    )
    session.commit()
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="NUMERACJA_RESET_RECZNY",
                tabela_docelowa="konfiguracja_numeracji", ip_adres=get_client_ip(request))
    return {"message": "Sekwencja numeracji zresetowana."}


@router.get("/numeracja/podglad")
async def podglad_numeracji(session: Session = Depends(get_session),
                             current_user: CurrentUser = Depends(require_roles(*IT))):
    row = session.execute(text("SELECT * FROM konfiguracja_numeracji LIMIT 1")).mappings().first()
    if not row:
        return {"podglad": ""}
    cfg = dict(row)
    from datetime import date
    today = date.today()
    seq = str((cfg.get("ostatni_numer") or 0) + 1).zfill(cfg.get("szerokosc_sekwencji") or 4)
    year = str(today.year)
    month = str(today.month).zfill(2)
    fmt = cfg.get("format_szablonu") or "{PREFIX}.{SEQ}.{ROK}"
    import re
    podglad = fmt.replace("{PREFIX}", cfg.get("prefix") or "ZUP")
    podglad = re.sub(r"\{SEQ:\d+\}", seq, podglad)
    podglad = podglad.replace("{SEQ}", seq)
    podglad = podglad.replace("{ROK}", year).replace("{YEAR}", year)
    podglad = podglad.replace("{MONTH}", month)
    return {"podglad": podglad}


@router.get("/platforma")
async def get_platforma(session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    rows = session.execute(text("SELECT * FROM konfiguracja_platformy ORDER BY klucz")).mappings().all()
    return [dict(r) for r in rows]


@router.put("/platforma/{klucz}")
async def update_platforma(klucz: str, body: PlatformaIn,
                            session: Session = Depends(get_session),
                            current_user: CurrentUser = Depends(require_roles("SUPERADMIN"))):
    existing = session.execute(
        text("SELECT klucz FROM konfiguracja_platformy WHERE klucz=:k"),
        {"k": klucz},
    ).mappings().first()
    if existing:
        row = session.execute(
            text("UPDATE konfiguracja_platformy SET wartosc=:v WHERE klucz=:k RETURNING *"),
            {"v": body.wartosc, "k": klucz},
        ).mappings().first()
    else:
        row = session.execute(
            text("INSERT INTO konfiguracja_platformy (klucz,wartosc) VALUES (:k,:v) RETURNING *"),
            {"k": klucz, "v": body.wartosc},
        ).mappings().first()
    session.commit()
    return dict(row)


@router.get("/dashboard")
async def dashboard(session: Session = Depends(get_session),
                     current_user: CurrentUser = Depends(get_current_user)):
    rola = current_user.rola
    stats: dict = {}

    if rola in ("IT_ADMIN", "SUPERADMIN"):
        wit = session.execute(text("SELECT COUNT(*) as cnt FROM wnioski WHERE status='OCZEKUJE_IT'")).mappings().first()
        upa = session.execute(text("SELECT COUNT(*) as cnt FROM uprawnienia WHERE aktywne=1")).mappings().first()
        prz = session.execute(text("SELECT COUNT(*) as cnt FROM uprawnienia WHERE wymaga_przegladu=1")).mappings().first()
        inc = session.execute(text("SELECT COUNT(*) as cnt FROM rejestr_incydentow WHERE status IN ('OTWARTY','W_TRAKCIE')")).mappings().first()
        esc = session.execute(text("SELECT COUNT(*) as cnt FROM wnioski_etapy WHERE status='OCZEKUJE' AND data_eskalacji IS NOT NULL")).mappings().first()
        stats["wnioski_oczekujace_it"] = wit["cnt"] if wit else 0
        stats["uprawnienia_aktywne"] = upa["cnt"] if upa else 0
        stats["przeglady_zagle"] = prz["cnt"] if prz else 0
        stats["incydenty_otwarte"] = inc["cnt"] if inc else 0
        stats["eskalacje_aktywne"] = esc["cnt"] if esc else 0
        last_wnioski = session.execute(
            text("""SELECT w.id, w.numer, w.status, w.data_ostatniej_zmiany, t.skrot as tenant_skrot,
                           u.imie || ' ' || u.nazwisko as pracownik_nazwa
                      FROM wnioski w JOIN pracownicy p ON p.id=w.pracownik_id
                      JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                      JOIN tenants t ON t.id=w.tenant_id
                     ORDER BY w.data_ostatniej_zmiany DESC LIMIT 10""")
        ).mappings().all()
        stats["ostatnie_wnioski"] = [dict(r) for r in last_wnioski]

    if rola == "KIEROWNIK":
        prac = session.execute(
            text("SELECT id FROM pracownicy WHERE uzytkownik_id=:uid"),
            {"uid": current_user.userId},
        ).mappings().first()
        if prac:
            prac_id = prac["id"]
            do_zatw = session.execute(
                text("""SELECT COUNT(*) as cnt FROM wnioski_etapy we
                          JOIN wnioski w ON w.id=we.wniosek_id
                         WHERE we.zatwierdzajacy_id=:pid AND we.status='OCZEKUJE' AND w.status='W_TOKU'"""),
                {"pid": prac_id},
            ).mappings().first()
            moje_w = session.execute(
                text("SELECT COUNT(*) as cnt FROM wnioski WHERE inicjujacy_id=:pid AND status NOT IN ('ZREALIZOWANY','ODRZUCONY')"),
                {"pid": prac_id},
            ).mappings().first()
            podwl = session.execute(
                text("SELECT COUNT(*) as cnt FROM pracownicy WHERE przelozony_id=:pid AND aktywny=1"),
                {"pid": prac_id},
            ).mappings().first()
            stats["do_zatwierdzenia"] = do_zatw["cnt"] if do_zatw else 0
            stats["moje_wnioski_w_toku"] = moje_w["cnt"] if moje_w else 0
            stats["liczba_podwladnych"] = podwl["cnt"] if podwl else 0

    if rola == "KADRY":
        nowy_p = session.execute(
            text("SELECT COUNT(*) as cnt FROM pracownicy WHERE date(data_zatrudnienia) >= date('now', '-30 days')")
        ).mappings().first()
        w_toku = session.execute(
            text("SELECT COUNT(*) as cnt FROM wnioski WHERE status IN ('W_TOKU','OCZEKUJE_IT')")
        ).mappings().first()
        stats["nowi_pracownicy_30d"] = nowy_p["cnt"] if nowy_p else 0
        stats["wnioski_w_toku"] = w_toku["cnt"] if w_toku else 0

    return stats
