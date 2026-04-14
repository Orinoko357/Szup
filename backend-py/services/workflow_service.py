from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.numeracja_service import generate_numer
from services.notification_service import create_notification, notify_it

logger = logging.getLogger(__name__)


def resolve_szablon(pracownik_id: int, session: Session) -> dict:
    """Resolve workflow template for an employee (komorka-specific or tenant default)."""
    prac = session.execute(
        text("SELECT komorka_id, tenant_id FROM pracownicy WHERE id=:id"),
        {"id": pracownik_id},
    ).mappings().first()
    if not prac:
        raise HTTPException(status_code=404, detail="Pracownik nie istnieje.")

    komorka_id = prac["komorka_id"]
    tenant_id = prac["tenant_id"]
    szablon = None

    if komorka_id:
        row = session.execute(
            text("""SELECT ws.* FROM workflow_przypisania wp
                      JOIN workflow_szablony ws ON ws.id=wp.szablon_id
                     WHERE wp.komorka_id=:kid AND ws.aktywny=1"""),
            {"kid": komorka_id},
        ).mappings().first()
        if row:
            szablon = dict(row)

    if not szablon:
        row = session.execute(
            text("""SELECT ws.* FROM workflow_przypisania wp
                      JOIN workflow_szablony ws ON ws.id=wp.szablon_id
                     WHERE wp.typ='TENANT_DEFAULT' AND wp.tenant_id=:tid AND ws.aktywny=1"""),
            {"tid": tenant_id},
        ).mappings().first()
        if row:
            szablon = dict(row)

    if not szablon:
        raise HTTPException(
            status_code=422,
            detail="Brak skonfigurowanej ścieżki zatwierdzania dla tej komórki. Skontaktuj się z IT.",
        )

    poziomy = session.execute(
        text("""SELECT wl.*, p.id as prac_id,
                       u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
                       p.stanowisko as zatwierdzajacy_stanowisko
                  FROM workflow_poziomy wl
                  LEFT JOIN pracownicy p ON p.id=wl.zatwierdzajacy_id
                  LEFT JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                 WHERE wl.szablon_id=:sid ORDER BY wl.kolejnosc"""),
        {"sid": szablon["id"]},
    ).mappings().all()

    return {"szablon": szablon, "poziomy": [dict(p) for p in poziomy]}


def _snapshot_etapy(wniosek_id: int, poziomy: list, session: Session):
    now = datetime.utcnow()
    for p in poziomy:
        session.execute(
            text("""INSERT INTO wnioski_etapy
                     (wniosek_id, kolejnosc, nazwa, zatwierdzajacy_id, opcjonalny,
                      opis_warunku_pominiecia, przypomnienie_dni, eskalacja_dni, status, data_przypisania)
                    VALUES (:wid,:k,:n,:zid,:o,:op,:r,:e,'OCZEKUJE',
                            CASE WHEN :k=1 THEN :now ELSE NULL END)"""),
            {"wid": wniosek_id, "k": p["kolejnosc"], "n": p["nazwa"],
             "zid": p.get("zatwierdzajacy_id"), "o": p.get("opcjonalny", False),
             "op": p.get("opis_warunku_pominiecia"), "r": p.get("przypomnienie_dni"),
             "e": p.get("eskalacja_dni"), "now": now},
        )
    # Ensure first stage has data_przypisania
    session.execute(
        text("UPDATE wnioski_etapy SET data_przypisania=:now WHERE wniosek_id=:wid AND kolejnosc=1"),
        {"now": now, "wid": wniosek_id},
    )


def submit_wniosek(wniosek_id: int, inicjujacy_user_id: int, session: Session) -> dict:
    w = session.execute(
        text("SELECT * FROM wnioski WHERE id=:id"),
        {"id": wniosek_id},
    ).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    w = dict(w)

    if w["status"] not in ("SZKIC", "WYMAGA_POPRAWY"):
        raise HTTPException(status_code=400, detail="Wniosek nie może być złożony w obecnym statusie.")

    numer = w.get("numer")
    if not numer:
        numer = generate_numer(session)

    result = resolve_szablon(w["pracownik_id"], session)
    szablon = result["szablon"]
    poziomy = result["poziomy"]

    session.execute(text("DELETE FROM wnioski_etapy WHERE wniosek_id=:id"), {"id": wniosek_id})
    _snapshot_etapy(wniosek_id, poziomy, session)

    session.execute(
        text("UPDATE wnioski SET numer=:n, szablon_id=:sid, status='W_TOKU', aktualny_etap_kolejnosc=1, data_ostatniej_zmiany=:dt WHERE id=:id"),
        {"n": numer, "sid": szablon["id"], "dt": datetime.utcnow(), "id": wniosek_id},
    )
    session.commit()

    if poziomy:
        first = poziomy[0]
        if first.get("zatwierdzajacy_id"):
            u_row = session.execute(
                text("SELECT uzytkownik_id FROM pracownicy WHERE id=:id"),
                {"id": first["zatwierdzajacy_id"]},
            ).mappings().first()
            if u_row:
                create_notification(
                    u_row["uzytkownik_id"], "WNIOSEK_DO_ZATWIERDZENIA",
                    f"Nowy wniosek {numer} oczekuje na Twoją akceptację (Etap 1: {first.get('nazwa') or ''}).",
                    f"/wnioski/{wniosek_id}", session,
                )

    return {"numer": numer, "szablon": szablon, "poziomy": poziomy}


def zatwierdz(wniosek_id: int, etap_kolejnosc: int, zatwierdzajacy_prac_id: int,
               komentarz: Optional[str], user_ctx: Any, session: Session) -> dict:
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    w = dict(w)
    if w["status"] != "W_TOKU":
        raise HTTPException(status_code=400, detail="Wniosek nie jest w toku.")

    etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc=:k"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()
    if not etap:
        raise HTTPException(status_code=404, detail="Etap nie istnieje.")
    etap = dict(etap)

    if etap["status"] != "OCZEKUJE":
        raise HTTPException(status_code=400, detail="Etap nie oczekuje na zatwierdzenie.")
    if etap.get("zatwierdzajacy_id") != zatwierdzajacy_prac_id:
        raise HTTPException(status_code=403, detail="Nie jesteś zatwierdzającym tego etapu.")

    now = datetime.utcnow()
    session.execute(
        text("UPDATE wnioski_etapy SET status='ZATWIERDZONY', data_akcji=:dt, komentarz=:k WHERE wniosek_id=:wid AND kolejnosc=:kol"),
        {"dt": now, "k": komentarz, "wid": wniosek_id, "kol": etap_kolejnosc},
    )

    next_etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc>:k ORDER BY kolejnosc LIMIT 1"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()

    if next_etap:
        next_etap = dict(next_etap)
        session.execute(
            text("UPDATE wnioski_etapy SET data_przypisania=:dt, status='OCZEKUJE' WHERE id=:id"),
            {"dt": now, "id": next_etap["id"]},
        )
        session.execute(
            text("UPDATE wnioski SET aktualny_etap_kolejnosc=:k, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"k": next_etap["kolejnosc"], "dt": now, "id": wniosek_id},
        )
        session.commit()

        if next_etap.get("zatwierdzajacy_id"):
            u_row = session.execute(
                text("SELECT uzytkownik_id FROM pracownicy WHERE id=:id"),
                {"id": next_etap["zatwierdzajacy_id"]},
            ).mappings().first()
            if u_row:
                create_notification(
                    u_row["uzytkownik_id"], "WNIOSEK_DO_ZATWIERDZENIA",
                    f"Wniosek {w.get('numer')} oczekuje na Twoją akceptację (Etap {next_etap['kolejnosc']}: {next_etap.get('nazwa') or ''}).",
                    f"/wnioski/{wniosek_id}", session,
                )
    else:
        session.execute(
            text("UPDATE wnioski SET status='OCZEKUJE_IT', aktualny_etap_kolejnosc=NULL, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"dt": now, "id": wniosek_id},
        )
        session.commit()

        notify_it("WNIOSEK_DO_REALIZACJI",
                   f"Wniosek {w.get('numer')} oczekuje na realizację IT.",
                   f"/wnioski/{wniosek_id}", session)

        try:
            from services.pdf_service import generate_wniosek_pdf
            generate_wniosek_pdf(wniosek_id, user_ctx, session)
        except Exception as e:
            logger.error(f"PDF generation failed for wniosek {wniosek_id}: {e}")

    from dependencies import write_audit
    write_audit(session, tenant_id=w.get("tenant_id"), user_id=user_ctx.userId,
                username=user_ctx.username, rola=user_ctx.rola,
                akcja="ZATWIERDZENIE_ETAPU", tabela_docelowa="wnioski_etapy",
                rekord_id=etap["id"],
                nowe_dane={"komentarz": komentarz, "etapKolejnosc": etap_kolejnosc, "wniosekId": wniosek_id})
    return {"success": True}


def odrzuc(wniosek_id: int, etap_kolejnosc: int, zatwierdzajacy_prac_id: int,
            powod: str, user_ctx: Any, session: Session) -> dict:
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    w = dict(w)

    etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc=:k"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()
    if not etap:
        raise HTTPException(status_code=404, detail="Etap nie istnieje.")
    etap = dict(etap)

    if etap.get("zatwierdzajacy_id") != zatwierdzajacy_prac_id:
        raise HTTPException(status_code=403, detail="Nie jesteś zatwierdzającym tego etapu.")

    now = datetime.utcnow()
    session.execute(
        text("UPDATE wnioski_etapy SET status='ODRZUCONY', data_akcji=:dt, komentarz=:p WHERE id=:id"),
        {"dt": now, "p": powod, "id": etap["id"]},
    )
    session.execute(
        text("UPDATE wnioski SET status='ODRZUCONY', odrzucil_id=:uid, data_odrzucenia=:dt, powod_odrzucenia=:p, data_ostatniej_zmiany=:dt WHERE id=:id"),
        {"uid": user_ctx.userId, "dt": now, "p": powod, "id": wniosek_id},
    )
    session.commit()

    inic_row = session.execute(
        text("SELECT u.id as uid FROM pracownicy p JOIN uzytkownicy u ON u.id=p.uzytkownik_id WHERE p.id=:pid"),
        {"pid": w["inicjujacy_id"]},
    ).mappings().first()
    if inic_row:
        create_notification(inic_row["uid"], "WNIOSEK_ODRZUCONY",
                            f"Wniosek {w.get('numer')} został odrzucony. Powód: {powod}",
                            f"/wnioski/{wniosek_id}", session)

    from dependencies import write_audit
    write_audit(session, tenant_id=w.get("tenant_id"), user_id=user_ctx.userId,
                username=user_ctx.username, rola=user_ctx.rola,
                akcja="ODRZUCENIE_WNIOSKU", tabela_docelowa="wnioski", rekord_id=wniosek_id,
                nowe_dane={"powod": powod, "etapKolejnosc": etap_kolejnosc})
    return {"success": True}


def odeslij(wniosek_id: int, etap_kolejnosc: int, zatwierdzajacy_prac_id: int,
             komentarz: str, user_ctx: Any, session: Session) -> dict:
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    w = dict(w)

    etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc=:k"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()
    if not etap:
        raise HTTPException(status_code=404, detail="Etap nie istnieje.")
    etap = dict(etap)

    if etap.get("zatwierdzajacy_id") != zatwierdzajacy_prac_id:
        raise HTTPException(status_code=403, detail="Nie jesteś zatwierdzającym tego etapu.")

    now = datetime.utcnow()
    session.execute(
        text("UPDATE wnioski_etapy SET status='ODESŁANY', data_akcji=:dt, komentarz=:k WHERE id=:id"),
        {"dt": now, "k": komentarz, "id": etap["id"]},
    )

    if etap_kolejnosc > 1:
        session.execute(
            text("UPDATE wnioski_etapy SET status='OCZEKUJE', data_przypisania=:dt, data_akcji=NULL, data_przypomnienia=NULL WHERE wniosek_id=:wid AND kolejnosc=:k"),
            {"dt": now, "wid": wniosek_id, "k": etap_kolejnosc - 1},
        )
        session.execute(
            text("UPDATE wnioski SET aktualny_etap_kolejnosc=:k, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"k": etap_kolejnosc - 1, "dt": now, "id": wniosek_id},
        )
        session.commit()

        prev = session.execute(
            text("SELECT zatwierdzajacy_id FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc=:k"),
            {"wid": wniosek_id, "k": etap_kolejnosc - 1},
        ).mappings().first()
        if prev and prev["zatwierdzajacy_id"]:
            u_row = session.execute(
                text("SELECT uzytkownik_id FROM pracownicy WHERE id=:id"),
                {"id": prev["zatwierdzajacy_id"]},
            ).mappings().first()
            if u_row:
                create_notification(u_row["uzytkownik_id"], "WNIOSEK_ODESŁANY",
                                    f"Wniosek {w.get('numer')} został odesłany do poprawy. Proszę o ponowne zatwierdzenie.",
                                    f"/wnioski/{wniosek_id}", session)
    else:
        session.execute(
            text("UPDATE wnioski SET status='WYMAGA_POPRAWY', aktualny_etap_kolejnosc=NULL, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"dt": now, "id": wniosek_id},
        )
        session.commit()

        inic_row = session.execute(
            text("SELECT u.id as uid FROM pracownicy p JOIN uzytkownicy u ON u.id=p.uzytkownik_id WHERE p.id=:pid"),
            {"pid": w["inicjujacy_id"]},
        ).mappings().first()
        if inic_row:
            create_notification(inic_row["uid"], "WNIOSEK_WYMAGA_POPRAWY",
                                f"Wniosek {w.get('numer')} wymaga poprawy. Komentarz: {komentarz}",
                                f"/wnioski/{wniosek_id}", session)

    from dependencies import write_audit
    write_audit(session, tenant_id=w.get("tenant_id"), user_id=user_ctx.userId,
                username=user_ctx.username, rola=user_ctx.rola,
                akcja="ODESLANIE_DO_POPRAWY", tabela_docelowa="wnioski", rekord_id=wniosek_id,
                nowe_dane={"komentarz": komentarz, "etapKolejnosc": etap_kolejnosc})
    return {"success": True}


def pomin_etap(wniosek_id: int, etap_kolejnosc: int, zatwierdzajacy_prac_id: int,
                powod: str, user_ctx: Any, session: Session) -> dict:
    w = session.execute(text("SELECT * FROM wnioski WHERE id=:id"), {"id": wniosek_id}).mappings().first()
    if not w:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")

    etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc=:k"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()
    if not etap:
        raise HTTPException(status_code=404, detail="Etap nie istnieje.")
    etap = dict(etap)

    if not etap.get("opcjonalny"):
        raise HTTPException(status_code=400, detail="Ten etap nie jest opcjonalny.")

    now = datetime.utcnow()
    session.execute(
        text("UPDATE wnioski_etapy SET status='POMINIĘTY', pominiety=1, powod_pominiecia=:p, data_akcji=:dt WHERE id=:id"),
        {"p": powod, "dt": now, "id": etap["id"]},
    )

    next_etap = session.execute(
        text("SELECT * FROM wnioski_etapy WHERE wniosek_id=:wid AND kolejnosc>:k ORDER BY kolejnosc LIMIT 1"),
        {"wid": wniosek_id, "k": etap_kolejnosc},
    ).mappings().first()

    if next_etap:
        next_etap = dict(next_etap)
        session.execute(
            text("UPDATE wnioski_etapy SET data_przypisania=:dt WHERE id=:id"),
            {"dt": now, "id": next_etap["id"]},
        )
        session.execute(
            text("UPDATE wnioski SET aktualny_etap_kolejnosc=:k, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"k": next_etap["kolejnosc"], "dt": now, "id": wniosek_id},
        )
    else:
        session.execute(
            text("UPDATE wnioski SET status='OCZEKUJE_IT', aktualny_etap_kolejnosc=NULL, data_ostatniej_zmiany=:dt WHERE id=:id"),
            {"dt": now, "id": wniosek_id},
        )
    session.commit()
    return {"success": True}
