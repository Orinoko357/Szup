"""
Nocne migawki stanu upoważnień — „kto co miał danego dnia".

Raz na dobę (o 23:50, patrz `services/scheduler.py`) zapisujemy zamrożony obraz
efektywnych uprawnień wszystkich osób. Migawka jest niezależna od późniejszych
zmian w bazie — pozwala odtworzyć stan sprzed lat (retencja ≥ 5 lat).

Dane trzymamy jako skompresowany JSON (jedna migawka = jeden wiersz w tabeli),
co przy setkach osób daje kilkadziesiąt kB dziennie zamiast tysięcy wierszy.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, col, select

from models import (
    Department,
    PermissionDeclaration,
    PermissionSnapshot,
    Unit,
    User,
)

_log = logging.getLogger("szup.snapshots")


def local_today() -> str:
    """Bieżąca data LOKALNA (RRRR-MM-DD). Migawka 23:50 dotyczy dnia jej wykonania."""
    return datetime.now().strftime("%Y-%m-%d")


def build_rows(session: Session) -> list[dict]:
    """Zbierz efektywne uprawnienia wszystkich osób + kod oświadczenia (jeśli był).

    Reużywa `_effective_permissions` (odtworzenie stanu z ukończonych wniosków),
    żeby migawka była spójna z tym, co pokazuje „Moje uprawnienia" i rejestr.
    """
    from routers.users import _effective_permissions

    users = session.exec(
        select(User).where(User.is_active == True)  # noqa: E712
    ).all()

    # Nazwy jednostek/wydziałów per użytkownik (bieżące przypisanie).
    dept_ids = list({u.department_id for u in users if u.department_id})
    dept_map = {d.id: d for d in session.exec(
        select(Department).where(col(Department.id).in_(dept_ids)))} if dept_ids else {}
    unit_ids = list({d.unit_id for d in dept_map.values() if d.unit_id})
    unit_map = {u.id: u for u in session.exec(
        select(Unit).where(col(Unit.id).in_(unit_ids)))} if unit_ids else {}

    # request_id → kod oświadczenia (do powiązania nadania z oświadczeniem).
    ref_by_req: dict[int, str] = {
        d.request_id: d.reference_code
        for d in session.exec(select(PermissionDeclaration)).all()
    }

    rows: list[dict] = []
    for u in users:
        eff = _effective_permissions(session, u.id)
        perms = eff.get("permissions", [])
        if not perms:
            continue
        dept = dept_map.get(u.department_id)
        unit = unit_map.get(dept.unit_id) if dept else None
        for p in perms:
            rows.append({
                "worker_user_id": u.id,
                "username": u.username,
                "worker_name": u.full_name or u.username,
                "unit_name": unit.name if unit else None,
                "department_name": dept.name if dept else None,
                "system_name": p.get("system_name"),
                "permission_name": p.get("permission_name"),
                "custom_values": p.get("custom_values") or {},
                "granted_at": p.get("granted_at"),
                "reference_code": ref_by_req.get(p.get("request_id")),
            })

    rows.sort(key=lambda r: (
        (r["worker_name"] or "").lower(),
        (r["system_name"] or "").lower(),
        (r["permission_name"] or "").lower(),
    ))
    return rows


def _pack(rows: list[dict], generated_at: str) -> tuple[bytes, str]:
    """JSON → (gzip, sha256 kanonicznego JSON-a)."""
    payload = {"generated_at": generated_at, "rows": rows}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return gzip.compress(canonical), digest


def unpack(snap: PermissionSnapshot) -> dict:
    """Rozpakuj migawkę → {"generated_at", "rows":[...]}."""
    if not snap.data_gz:
        return {"generated_at": None, "rows": []}
    return json.loads(gzip.decompress(snap.data_gz).decode("utf-8"))


def get_by_date(session: Session, snapshot_date: str) -> Optional[PermissionSnapshot]:
    return session.exec(
        select(PermissionSnapshot)
        .where(PermissionSnapshot.snapshot_date == snapshot_date)
    ).first()


# `generated_by` migawki nocnej (harmonogram). Ręczne mają login admina.
NIGHTLY_GENERATOR = "system"


def create_snapshot(
    session: Session,
    generated_by: str = NIGHTLY_GENERATOR,
    for_date: Optional[str] = None,
    force: bool = False,
) -> PermissionSnapshot:
    """Utwórz migawkę dla danego dnia. Idempotentne: jedna migawka na datę.

    `force=True` nadpisuje istniejącą migawkę tego dnia (np. ręczne odświeżenie
    po korekcie danych). Bez `force` zwraca istniejącą, jeśli już jest — z jednym
    wyjątkiem: migawka nocna zastępuje RĘCZNĄ z tego samego dnia. Ręczna powstaje
    w trakcie dnia, a nocna ma utrwalić stan na jego koniec; inaczej ręczne
    odświeżenie rano blokowałoby nocny zapis.
    """
    date = for_date or local_today()
    existing = get_by_date(session, date)
    nightly_over_manual = (
        existing is not None
        and generated_by == NIGHTLY_GENERATOR
        and existing.generated_by != NIGHTLY_GENERATOR
    )
    if existing and not force and not nightly_over_manual:
        return existing

    rows = build_rows(session)
    generated_at = datetime.utcnow().isoformat()
    data_gz, digest = _pack(rows, generated_at)
    persons = len({r["worker_user_id"] for r in rows})

    if existing:
        existing.created_at = datetime.utcnow()
        existing.generated_by = generated_by
        existing.person_count = persons
        existing.permission_count = len(rows)
        existing.content_sha256 = digest
        existing.data_gz = data_gz
        snap = existing
    else:
        snap = PermissionSnapshot(
            snapshot_date=date, generated_by=generated_by,
            person_count=persons, permission_count=len(rows),
            content_sha256=digest, data_gz=data_gz,
        )
    session.add(snap)
    session.commit()
    session.refresh(snap)
    _log.info("Migawka uprawnień %s: %d osób, %d pozycji (%s)",
              date, persons, len(rows), generated_by)
    return snap
