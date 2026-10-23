"""
Wspólne reguły struktury organizacyjnej (3.10).

  • `live_department` — komórka, do której wolno coś przypisać (wniosek,
    pracownika): istnieje, nie jest zarchiwizowana i jest aktywna. Inaczej 400.
  • `higher_approvers` / `higher_approval_orphans` — czy komórka z akceptacją
    wyższą ma osobę, która może tę akceptację wykonać (te same reguły co
    adresaci kroku w services.workflow). Komórka bez takiej osoby zostaje
    z flagą, ale lista kontrolna (/settings/health) zgłasza ją jako błąd.
  • `is_system_request` — wnioski zakładane automatycznie przez operacje
    superadmina (np. odebranie uprawnień przy usunięciu grupy). To nie są
    wnioski o ustanie stosunku pracy i obieg musi je rozpoznawać.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models import AccessRequest, Department, User

# Zakres INTEGER w SQLite — id spoza niego nie istnieje (bez OverflowError → 500).
_MAX_DB_INT = 2 ** 63 - 1


def db_int_ok(value: Any) -> bool:
    """Czy wartość mieści się w zakresie klucza w bazie (SQLite INTEGER)."""
    try:
        return -_MAX_DB_INT - 1 <= int(value) <= _MAX_DB_INT
    except (TypeError, ValueError):
        return False


def live_department(session: Session, dept_id: Optional[int]) -> Department:
    """Komórka, do której można przypisać wniosek lub pracownika.

    Rzuca HTTPException(400), gdy komórka nie istnieje (także id spoza zakresu
    bazy), została zarchiwizowana przez superadmina (`archived_at`) albo jest
    nieaktywna (`is_active=False`). Zwraca komórkę."""
    dept = session.get(Department, dept_id) if dept_id is not None and db_int_ok(dept_id) else None
    if dept is None:
        raise HTTPException(400, "Wskazana komórka nie istnieje")
    if getattr(dept, "archived_at", None):
        raise HTTPException(400, f"Komórka „{dept.name}” została zlikwidowana — wybierz inną komórkę")
    if not dept.is_active:
        raise HTTPException(400, f"Komórka „{dept.name}” jest nieaktywna — wybierz aktywną komórkę")
    return dept


# ---------------------------------------------------------------------------
# Akceptacja wyższa — czy jest osoba uprawniona
# ---------------------------------------------------------------------------

_HIGHER_NODE = {"id": "structure-check", "type": "higher_manager_approve"}


def higher_approvers(session: Session, dept: Department) -> list[int]:
    """Aktywne konta, które mogą wykonać akceptację wyższą wniosku komórki
    `dept`: (odpowiedzialny) kierownik komórki nadrzędnej i zastępcy, a gdy
    w łańcuchu nie ma nikogo — dyrektor jednostki. Bez kierownika i zastępców
    samej komórki (wyjątek: dyrektor jednostki). Działa także dla komórki
    jeszcze niezapisanej (walidacja przy tworzeniu).

    Rezerwa superadmina z obiegu (gdy w strukturze nie ma nikogo) się tu NIE
    liczy — to sytuacja awaryjna, którą trzeba naprawić w strukturze."""
    from services.workflow import _stage_actor_info
    ids, fallback = _stage_actor_info(session, _HIGHER_NODE, dept, None)
    if fallback:
        return []
    out: list[int] = []
    for uid in ids:
        u = session.get(User, uid)
        if u and u.is_active and uid not in out:
            out.append(uid)
    return out


def higher_approval_orphans(session: Session,
                            dept_ids: Optional[Iterable[int]] = None) -> list[Department]:
    """Aktywne (niezarchiwizowane) komórki z akceptacją wyższą, której nie ma
    kto wykonać — wnioski utknęłyby na tym kroku. `dept_ids` zawęża sprawdzenie."""
    stmt = (select(Department)
            .where(Department.requires_higher_approval == True)  # noqa: E712
            .where(Department.is_active == True)  # noqa: E712
            .where(Department.archived_at == None))  # noqa: E711
    if dept_ids is not None:
        ids = [int(x) for x in dept_ids]
        if not ids:
            return []
        stmt = stmt.where(Department.id.in_(ids))  # type: ignore[attr-defined]
    return [d for d in session.exec(stmt.order_by(Department.name)).all()
            if not higher_approvers(session, d)]


# ---------------------------------------------------------------------------
# Wnioski systemowe
# ---------------------------------------------------------------------------

# Prefiks komentarzy (`manager_comment` i `it_comment`) wniosków zakładanych
# automatycznie przez operacje superadmina. Takie wnioski mają też
# `request_type_id = None` i od razu status `completed`.
SYSTEM_REQUEST_PREFIX = "[SYSTEM] "


def is_system_request(req: Optional[AccessRequest]) -> bool:
    """Czy wniosek założył system (operacja superadmina), a nie człowiek
    w obiegu — np. odebranie uprawnień po usunięciu grupy. Nie jest to
    wniosek o ustanie stosunku pracy."""
    if req is None or getattr(req, "request_type_id", None) is not None:
        return False
    return (req.manager_comment or "").startswith(SYSTEM_REQUEST_PREFIX) \
        or (getattr(req, "it_comment", None) or "").startswith(SYSTEM_REQUEST_PREFIX)
