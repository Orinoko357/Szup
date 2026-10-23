"""
Migawki uprawnień — przegląd historyczny „kto co miał danego dnia" (IT / admin).

Nocna migawka (23:50) zapisuje zamrożony stan efektywnych uprawnień wszystkich
osób. Tu udostępniamy listę migawek, podgląd wybranego dnia (z filtrami) i
eksport CSV do audytu. Generowanie ręczne — dla admina.
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from database import get_session
from models import PermissionSnapshot, User
from services.permissions import require_admin, require_it_staff
from services.snapshots import create_snapshot, get_by_date, unpack

router = APIRouter()


def _meta(s: PermissionSnapshot) -> dict:
    return {
        "snapshot_date": s.snapshot_date,
        "created_at": s.created_at,
        "generated_by": s.generated_by,
        "person_count": s.person_count,
        "permission_count": s.permission_count,
        "content_sha256": s.content_sha256,
    }


@router.get("")
def list_snapshots(
    limit: int = Query(400, ge=1, le=3000),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    """Lista migawek (najnowsze pierwsze) — bez danych, tylko metryki."""
    total = len(session.exec(select(PermissionSnapshot.id)).all())
    rows = session.exec(
        select(PermissionSnapshot)
        .order_by(col(PermissionSnapshot.snapshot_date).desc())
        .offset(offset).limit(limit)
    ).all()
    return {"items": [_meta(s) for s in rows], "total": total}


def _filtered_rows(snap: PermissionSnapshot, *, q=None, system=None):
    """Filtruj wiersze migawki w pamięci — migawka trzyma NAZWY, nie id, więc
    filtr po pracowniku i systemie idzie po tekście (szukajka we froncie)."""
    rows = unpack(snap).get("rows", [])
    ql = (q or "").strip().lower()
    sysname = (system or "").strip().lower()
    out = []
    for r in rows:
        if ql and ql not in (r.get("worker_name") or "").lower() \
                and ql not in (r.get("username") or "").lower():
            continue
        if sysname and sysname not in (r.get("system_name") or "").lower():
            continue
        out.append(r)
    return out


# UWAGA na kolejność: „/{snapshot_date}.csv" MUSI być zadeklarowane PRZED
# „/{snapshot_date}", inaczej parametr ścieżki połknąłby też sufiks „.csv".
@router.get("/{snapshot_date}.csv")
def snapshot_csv(
    snapshot_date: str,
    q: Optional[str] = None,
    system: Optional[str] = None,
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    snap = get_by_date(session, snapshot_date)
    if not snap:
        raise HTTPException(404, "Brak migawki dla tej daty")
    rows = _filtered_rows(snap, q=q, system=system)

    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Pracownik", "Login", "Jednostka", "Wydział", "System",
                "Uprawnienie", "Zakres", "Nadano", "Kod oświadczenia"])
    for r in rows:
        zakres = "; ".join(f"{k}: {v}" for k, v in (r.get("custom_values") or {}).items())
        w.writerow([
            r.get("worker_name") or "", r.get("username") or "",
            r.get("unit_name") or "", r.get("department_name") or "",
            r.get("system_name") or "", r.get("permission_name") or "",
            zakres, r.get("granted_at") or "", r.get("reference_code") or "",
        ])
    buf.seek(0)
    fname = f"szup-migawka-{snapshot_date}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{snapshot_date}")
def get_snapshot(
    snapshot_date: str,
    q: Optional[str] = None,
    system: Optional[str] = None,
    _: User = Depends(require_it_staff),
    session: Session = Depends(get_session),
):
    """Pełna migawka danego dnia (rozpakowana), z opcjonalnym filtrem tekstowym."""
    snap = get_by_date(session, snapshot_date)
    if not snap:
        raise HTTPException(404, "Brak migawki dla tej daty")
    rows = _filtered_rows(snap, q=q, system=system)
    return {**_meta(snap), "generated_at": unpack(snap).get("generated_at"),
            "rows": rows, "shown": len(rows)}


@router.post("/run")
def run_snapshot(
    force: bool = False,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Wygeneruj migawkę na dziś ręcznie (admin). Idempotentne bez `force`."""
    snap = create_snapshot(session, generated_by=current_user.username, force=force)
    return _meta(snap)
