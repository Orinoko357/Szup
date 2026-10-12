"""
Generator PDF-ów dla wniosków SZUP.

Używany przez kierownika wydziału nadrzędnego (2-stopniowy workflow) jako dokument
do wydruku, podpisu i przesłania przez EZD FINN do Biura Informatyki Urzędu Miasta
Wodzisławia Śląskiego.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from sqlmodel import Session, select

from models import (
    AccessRequest, Department, PermissionSystem, RequestItem,
    SystemPermission, Unit, User,
)


# ---------------------------------------------------------------------------
# Fonty: reportlab Helvetica nie wspiera polskich znaków (CP1252).
# Rejestrujemy TTF wspierający CE — Arial (Windows) lub DejaVuSans (Linux).
# ---------------------------------------------------------------------------
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _register_pl_fonts() -> None:
    global _FONT_NAME, _FONT_BOLD
    regular_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    bold_candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    reg = next((p for p in regular_candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_candidates if os.path.exists(p)), None)
    if reg:
        try:
            pdfmetrics.registerFont(TTFont("PlFont", reg))
            _FONT_NAME = "PlFont"
        except Exception:
            pass
    if bold:
        try:
            pdfmetrics.registerFont(TTFont("PlFontBold", bold))
            _FONT_BOLD = "PlFontBold"
        except Exception:
            pass


_register_pl_fonts()


def _user_name(u: Optional[User]) -> str:
    if not u:
        return "—"
    return u.full_name or u.username or "—"


def generate_request_pdf(session: Session, req: AccessRequest) -> bytes:
    """Zwraca zawartość PDF-a dla danego wniosku."""
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "N", parent=styles["Normal"], fontName=_FONT_NAME, fontSize=10, leading=13,
    )
    bold = ParagraphStyle("B", parent=normal, fontName=_FONT_BOLD)
    title = ParagraphStyle(
        "T", parent=normal, fontName=_FONT_BOLD, fontSize=15,
        alignment=1, spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "ST", parent=normal, fontSize=9, alignment=1, textColor=colors.grey,
    )
    h2 = ParagraphStyle(
        "H2", parent=bold, fontSize=11, spaceBefore=10, spaceAfter=4,
    )
    small = ParagraphStyle(
        "S", parent=normal, fontSize=8.5, textColor=colors.grey,
    )

    # ------------------------------------------------------------------
    # Kontekst: wydział / jednostka / użytkownicy / lista uprawnień
    # ------------------------------------------------------------------
    dept = session.get(Department, req.department_id)
    unit = session.get(Unit, req.unit_id)
    selector = session.get(User, req.selector_by_id) if req.selector_by_id else None
    approver = session.get(User, req.approved_by_id) if req.approved_by_id else None
    creator = session.get(User, req.created_by_id) if req.created_by_id else None
    completer = session.get(User, req.completed_by_id) if req.completed_by_id else None

    items = session.exec(
        select(RequestItem).where(RequestItem.request_id == req.id)
    ).all()

    # ------------------------------------------------------------------
    # Budowa dokumentu
    # ------------------------------------------------------------------
    elements: list = []
    elements.append(Paragraph("WNIOSEK O NADANIE UPRAWNIEŃ", title))
    elements.append(Paragraph(
        "Urząd Miasta Wodzisławia Śląskiego · System Zarządzania Uprawnieniami (SZUP)",
        subtitle,
    ))
    elements.append(Spacer(1, 6 * mm))

    def row(label: str, val: Optional[str]):
        return [
            Paragraph(f"<b>{label}</b>", normal),
            Paragraph(val if val else "—", normal),
        ]

    info = [
        row("Numer wniosku", f"#{req.id}"),
        row("Data złożenia", req.created_at.strftime("%Y-%m-%d %H:%M")),
        row("Pracownik", req.worker_name),
        row("Stanowisko", req.worker_position),
        row("E-mail", req.worker_email),
        row("Telefon", req.worker_phone),
        row("Jednostka", unit.name if unit else None),
        row("Wydział", dept.name if dept else None),
        row("Złożył(a) wniosek", req.created_by_name or _user_name(creator)),
    ]
    if selector:
        info.append(
            row("Kierownik wydziału (wybór uprawnień)", _user_name(selector))
        )
        if req.selected_at:
            info.append(
                row("Data wyboru uprawnień",
                    req.selected_at.strftime("%Y-%m-%d %H:%M"))
            )
    if approver:
        info.append(
            row("Kierownik wydziału nadrzędnego (akceptacja)", _user_name(approver))
        )
        if req.approved_at:
            info.append(
                row("Data akceptacji",
                    req.approved_at.strftime("%Y-%m-%d %H:%M"))
            )
    if completer:
        info.append(
            row("Zrealizował (Biuro Informatyki)", _user_name(completer))
        )
        if req.completed_at:
            info.append(
                row("Data realizacji",
                    req.completed_at.strftime("%Y-%m-%d %H:%M"))
            )

    info_table = Table(info, colWidths=[65 * mm, 105 * mm])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(info_table)

    # Uprawnienia
    elements.append(Paragraph("Wnioskowane uprawnienia", h2))
    if items:
        data = [["Lp.", "System IT", "Uprawnienie"]]
        for i, it in enumerate(items, 1):
            s = session.get(PermissionSystem, it.system_id)
            p = session.get(SystemPermission, it.permission_id)
            data.append([
                str(i),
                s.name if s else f"#{it.system_id}",
                p.permission_name if p else f"#{it.permission_id}",
            ])
        ptable = Table(data, colWidths=[12 * mm, 75 * mm, 83 * mm])
        ptable.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(ptable)
    else:
        elements.append(Paragraph("(brak uprawnień)", normal))

    # Komentarze
    if req.selector_comment:
        elements.append(Paragraph("Komentarz kierownika wydziału (wybór uprawnień)", h2))
        elements.append(Paragraph(req.selector_comment, normal))
    if req.manager_comment:
        elements.append(Paragraph("Komentarz kierownika wydziału nadrzędnego", h2))
        elements.append(Paragraph(req.manager_comment, normal))

    # Oświadczenie wnioskującego — jeśli złożone, drukujemy jego zamrożoną
    # treść wraz z imieniem, nazwiskiem, datą i kodem referencyjnym.
    from models import PermissionDeclaration
    dec = session.exec(
        select(PermissionDeclaration)
        .where(PermissionDeclaration.request_id == req.id)
        .order_by(PermissionDeclaration.id.desc())
    ).first()
    if dec:
        elements.append(Spacer(1, 8 * mm))
        for i, line in enumerate((dec.declaration_text or "").split("\n")):
            txt = line.strip()
            if not txt:
                elements.append(Spacer(1, 2 * mm))
                continue
            elements.append(Paragraph(txt.replace("&", "&amp;"),
                                      h2 if i == 0 else small))
        elements.append(Spacer(1, 6 * mm))
        meta = [[
            Paragraph(f"<b>Imię i nazwisko:</b> {dec.declared_by_name}<br/>"
                      f"<b>Data:</b> {dec.declared_date}", normal),
            Paragraph(f"<b>Kod oświadczenia:</b><br/>"
                      f"<font size='9'>{dec.reference_code}</font>", normal),
        ]]
        meta_table = Table(meta, colWidths=[95 * mm, 75 * mm])
        meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(meta_table)

    # Miejsce na podpis
    elements.append(Spacer(1, 18 * mm))
    sig = [[
        Paragraph(
            ".........................................<br/>"
            "<font size='8'>podpis kierownika wydziału nadrzędnego</font>",
            normal,
        ),
        Paragraph(
            ".........................................<br/>"
            "<font size='8'>data i podpis — Biuro Informatyki</font>",
            normal,
        ),
    ]]
    sig_table = Table(sig, colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(sig_table)

    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        "Wniosek wygenerowany automatycznie przez system SZUP. Po podpisaniu "
        "proszę przesłać poprzez EZD FINN do Biura Informatyki Urzędu Miasta "
        "Wodzisławia Śląskiego.",
        small,
    ))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Wniosek SZUP #{req.id}",
        author="SZUP",
    )
    doc.build(elements)
    return buf.getvalue()
