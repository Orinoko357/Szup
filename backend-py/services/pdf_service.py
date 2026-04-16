from __future__ import annotations
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings

logger = logging.getLogger(__name__)


def _ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def generate_wniosek_pdf(wniosek_id: int, user_ctx: Any, session: Session) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        raise ImportError("reportlab is not installed")

    w = session.execute(
        text("""SELECT w.*, t.nazwa as tenant_nazwa,
                       u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                       p.stanowisko, j.nazwa as komorka_nazwa, p.data_zatrudnienia,
                       ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa
                  FROM wnioski w
                  JOIN tenants t ON t.id=w.tenant_id
                  JOIN pracownicy p ON p.id=w.pracownik_id
                  JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                  LEFT JOIN jednostki_org j ON j.id=p.jednostka_id
                  JOIN pracownicy pi ON pi.id=w.inicjujacy_id
                  JOIN uzytkownicy ui ON ui.id=pi.uzytkownik_id
                 WHERE w.id=:id"""),
        {"id": wniosek_id},
    ).mappings().first()
    if not w:
        raise ValueError(f"Wniosek {wniosek_id} not found")
    w = dict(w)

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
        text("""SELECT we.*, u.imie || ' ' || u.nazwisko as zatw_nazwa, p.stanowisko as zatw_stanowisko
                  FROM wnioski_etapy we
                  LEFT JOIN pracownicy p ON p.id=we.zatwierdzajacy_id
                  LEFT JOIN uzytkownicy u ON u.id=p.uzytkownik_id
                 WHERE we.wniosek_id=:id ORDER BY we.kolejnosc"""),
        {"id": wniosek_id},
    ).mappings().all()

    dir_path = os.path.join(settings.PDF_STORAGE_PATH, str(w["tenant_id"]))
    _ensure_dir(dir_path)
    numer = (w.get("numer") or str(wniosek_id)).replace("/", "_")
    file_path = os.path.join(dir_path, f"{numer}.pdf")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], alignment=1, fontSize=14)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Heading2"], alignment=1, fontSize=12)
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8)

    doc = SimpleDocTemplate(file_path, pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []

    # Header
    story.append(Paragraph(w.get("tenant_nazwa", ""), title_style))
    story.append(Paragraph("WNIOSEK O NADANIE UPRAWNIEŃ W SYSTEMACH TELEINFORMATYCZNYCH", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Numer wniosku: <b>{w.get('numer', '')}</b>", normal_style))
    story.append(Paragraph(f"Data: {datetime.now().strftime('%d.%m.%Y')}", normal_style))
    story.append(Spacer(1, 0.5*cm))

    # Employee data
    story.append(Paragraph("<b>DANE PRACOWNIKA</b>", normal_style))
    emp_data = [
        ["Imię i nazwisko:", w.get("pracownik_nazwa", "")],
        ["Stanowisko:", w.get("stanowisko") or "—"],
        ["Komórka organizacyjna:", w.get("komorka_nazwa") or "—"],
        ["Data zatrudnienia:", str(w.get("data_zatrudnienia") or "—")],
    ]
    emp_table = Table(emp_data, colWidths=[5*cm, 12*cm])
    emp_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 0.5*cm))

    # Permissions table
    story.append(Paragraph("<b>WNIOSKOWANE UPRAWNIENIA</b>", normal_style))
    perm_headers = [["System", "Moduł", "Zakres", "Uprzywilejowany", "Uzasadnienie"]]
    perm_data = []
    for p in pozycje:
        p = dict(p)
        perm_data.append([
            p.get("system_nazwa", ""),
            p.get("modul_nazwa") or "—",
            p.get("zakres_nazwa", ""),
            "TAK" if p.get("uprzywilejowany") else "NIE",
            p.get("uzasadnienie") or "—",
        ])
    perm_table = Table(perm_headers + perm_data, colWidths=[3.5*cm, 3*cm, 3*cm, 2.5*cm, 5*cm])
    perm_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ]))
    story.append(perm_table)
    story.append(Spacer(1, 0.5*cm))

    # Approval history
    story.append(Paragraph("<b>HISTORIA ZATWIERDZEŃ</b>", normal_style))
    for e in etapy:
        e = dict(e)
        status_map = {"ZATWIERDZONY": "✓", "ODRZUCONY": "✗", "POMINIĘTY": "P"}
        status_sym = status_map.get(e.get("status", ""), "○")
        data = ""
        if e.get("data_akcji"):
            try:
                da = e["data_akcji"]
                if isinstance(da, str):
                    da = datetime.fromisoformat(da[:19])
                data = da.strftime("%d.%m.%Y")
            except Exception:
                data = str(e.get("data_akcji", ""))
        line = f"{status_sym} Etap {e.get('kolejnosc')}: {e.get('nazwa') or ''} | {e.get('zatw_nazwa') or '—'} ({e.get('zatw_stanowisko') or '—'}) | {data}"
        if e.get("komentarz"):
            line += f" | {e['komentarz']}"
        story.append(Paragraph(line, small_style))
    story.append(Spacer(1, 0.5*cm))

    # Signature section
    story.append(Paragraph("<b>ZATWIERDZENIE KOŃCOWE</b>", normal_style))
    last_approved = None
    for e in etapy:
        e = dict(e)
        if e.get("status") == "ZATWIERDZONY":
            last_approved = e
    story.append(Paragraph(f"Imię i nazwisko: {last_approved['zatw_nazwa'] if last_approved else '__________________________'}", normal_style))
    story.append(Paragraph(f"Stanowisko: {last_approved['zatw_stanowisko'] if last_approved else '__________________________'}", normal_style))
    story.append(Paragraph("Data: __________________________", normal_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("Podpis kwalifikowany złożony poza systemem: □ TAK", normal_style))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Podpis własnoręczny: ____________________________________________", normal_style))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"Wniosek: {w.get('numer', '')} | Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')} | System ZUP v2.0.0", small_style))

    doc.build(story)

    uid = user_ctx.userId if user_ctx else None
    session.execute(
        text("UPDATE wnioski SET pdf_sciezka=:p, pdf_wygenerowany_przez=:uid, pdf_data_generowania=:dt WHERE id=:id"),
        {"p": file_path, "uid": uid, "dt": datetime.utcnow(), "id": wniosek_id},
    )
    session.commit()

    logger.info(f"PDF generated: {file_path}")
    return file_path
