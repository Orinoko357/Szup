"""
Router: Słownik dostawców oprogramowania + umowy serwisowe.

Uprawnienia jak w rejestrze oprogramowania — odczyt dla zalogowanych,
zapis dla `require_it_staff` (IT + admin + superadmin).

Status umowy NIE jest osobną flagą — wyliczamy go z dat (`_vendor_status`),
żeby nie mógł rozjechać się z rzeczywistością.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from models import PermissionSystem, SoftwareVendor, User, VendorContract
from services.auth_service import get_current_user
from services.permissions import require_it_staff

router = APIRouter()

# Ile dni przed końcem umowy zaczynamy ostrzegać (pomarańczowo).
EXPIRY_WARN_DAYS = 30


# ---------------------------------------------------------------------------
# Status umowy — jedno źródło prawdy dla listy i dla alertów na pulpicie
# ---------------------------------------------------------------------------

def _vendor_status(session: Session, vendor_id: int) -> dict:
    """Wylicza stan umów serwisowych dostawcy.

    status:
      "active"   — jakaś umowa trwa (dzień końcowy WŁĄCZNIE),
      "expiring" — trwa, ale kończy się w ciągu EXPIRY_WARN_DAYS dni,
      "expired"  — były umowy, wszystkie się skończyły,
      "none"     — brak wpisanych umów.
    """
    rows = session.exec(
        select(VendorContract).where(VendorContract.vendor_id == vendor_id)
    ).all()
    if not rows:
        return {"status": "none", "active_until": None, "days_left": None,
                "contract_count": 0}

    today = datetime.utcnow().date()
    # Dzień końcowy liczy się włącznie — umowa do 21.07 jest ważna przez cały 21.07.
    ends = [c.valid_to.date() for c in rows if c.valid_to]
    active_ends = [d for d in ends if d >= today]

    if not active_ends:
        last = max(ends) if ends else None
        return {
            "status": "expired",
            "active_until": last.isoformat() if last else None,
            "days_left": None,
            "contract_count": len(rows),
        }

    furthest = max(active_ends)
    days_left = (furthest - today).days
    return {
        "status": "expiring" if days_left <= EXPIRY_WARN_DAYS else "active",
        "active_until": furthest.isoformat(),
        "days_left": days_left,
        "contract_count": len(rows),
    }


def _serialize_vendor(session: Session, v: SoftwareVendor) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "nip": v.nip,
        "address": v.address,
        "postal_code": v.postal_code,
        "city": v.city,
        "contact_person": v.contact_person,
        "phone": v.phone,
        "email": v.email,
        "website": v.website,
        "notes": v.notes,
        "is_active": v.is_active,
        **_vendor_status(session, v.id),
    }


def _serialize_contract(c: VendorContract) -> dict:
    return {
        "id": c.id,
        "vendor_id": c.vendor_id,
        "contract_number": c.contract_number,
        "description": c.description,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_to": c.valid_to.isoformat() if c.valid_to else None,
        "notes": c.notes,
    }


# ---------------------------------------------------------------------------
# Schematy
# ---------------------------------------------------------------------------

class VendorCreate(BaseModel):
    name: str
    nip: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    nip: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ContractIn(BaseModel):
    contract_number: Optional[str] = None
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: datetime
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    contract_number: Optional[str] = None
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# UWAGA na kolejność tras: ścieżki stałe („/contract-alerts", „/contracts/…")
# MUSZĄ być zadeklarowane PRZED „/{vendor_id}", inaczej FastAPI dopasuje je
# do parametru ścieżki.
# ---------------------------------------------------------------------------

@router.get("/")
def list_vendors(
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    rows = session.exec(select(SoftwareVendor).order_by(SoftwareVendor.name)).all()
    return [_serialize_vendor(session, v) for v in rows]


@router.get("/contract-alerts")
def contract_alerts(
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Umowy wygasłe i wygasające — dane dla pulpitu IT."""
    expired, expiring = [], []
    for v in session.exec(select(SoftwareVendor)).all():
        st = _vendor_status(session, v.id)
        entry = {"vendor_id": v.id, "vendor_name": v.name,
                 "active_until": st["active_until"], "days_left": st["days_left"]}
        if st["status"] == "expired":
            expired.append(entry)
        elif st["status"] == "expiring":
            expiring.append(entry)
    expiring.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 999)
    return {
        "expired_count": len(expired),
        "expiring_count": len(expiring),
        "expired": expired,
        "expiring": expiring,
        "warn_days": EXPIRY_WARN_DAYS,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_vendor(
    data: VendorCreate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    if not data.name.strip():
        raise HTTPException(400, "Nazwa dostawcy jest wymagana")
    v = SoftwareVendor(**data.model_dump())
    v.name = v.name.strip()
    session.add(v); session.commit(); session.refresh(v)
    return _serialize_vendor(session, v)


# --- Umowy serwisowe (dzieci) ----------------------------------------------
# Edycja/usuwanie po WŁASNYM id umowy — jak `PATCH /departments/deputies/{id}`.

@router.patch("/contracts/{contract_id}")
def update_contract(
    contract_id: int,
    data: ContractUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    c = session.get(VendorContract, contract_id)
    if not c:
        raise HTTPException(404, "Umowa nie istnieje")
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(c, field, value)
    if not c.valid_to:
        raise HTTPException(400, "Data końca umowy jest wymagana")
    _validate_period(c.valid_from, c.valid_to)
    session.add(c); session.commit(); session.refresh(c)
    return _serialize_contract(c)


@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    c = session.get(VendorContract, contract_id)
    if not c:
        raise HTTPException(404, "Umowa nie istnieje")
    session.delete(c); session.commit()


@router.get("/{vendor_id}/contracts")
def list_contracts(
    vendor_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    if not session.get(SoftwareVendor, vendor_id):
        raise HTTPException(404, "Dostawca nie istnieje")
    rows = session.exec(
        select(VendorContract)
        .where(VendorContract.vendor_id == vendor_id)
        .order_by(VendorContract.valid_to.desc())
    ).all()
    return [_serialize_contract(c) for c in rows]


@router.post("/{vendor_id}/contracts", status_code=status.HTTP_201_CREATED)
def add_contract(
    vendor_id: int,
    data: ContractIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    if not session.get(SoftwareVendor, vendor_id):
        raise HTTPException(404, "Dostawca nie istnieje")
    _validate_period(data.valid_from, data.valid_to)
    c = VendorContract(vendor_id=vendor_id, **data.model_dump())
    session.add(c); session.commit(); session.refresh(c)
    return _serialize_contract(c)


# --- Pojedynczy dostawca ----------------------------------------------------

@router.get("/{vendor_id}")
def get_vendor(
    vendor_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    v = session.get(SoftwareVendor, vendor_id)
    if not v:
        raise HTTPException(404, "Dostawca nie istnieje")
    return _serialize_vendor(session, v)


@router.patch("/{vendor_id}")
def update_vendor(
    vendor_id: int,
    data: VendorUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    v = session.get(SoftwareVendor, vendor_id)
    if not v:
        raise HTTPException(404, "Dostawca nie istnieje")
    # exclude_unset (nie exclude_none) — pozwala wyczyścić pole i ustawić False.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    if not (v.name or "").strip():
        raise HTTPException(400, "Nazwa dostawcy jest wymagana")
    session.add(v); session.commit(); session.refresh(v)
    return _serialize_vendor(session, v)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor(
    vendor_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    v = session.get(SoftwareVendor, vendor_id)
    if not v:
        raise HTTPException(404, "Dostawca nie istnieje")

    used = session.exec(
        select(PermissionSystem).where(PermissionSystem.vendor_id == vendor_id)
    ).first()
    if used:
        raise HTTPException(
            400,
            f'Nie można usunąć — dostawca jest przypisany do oprogramowania '
            f'„{used.name}". Najpierw zmień dostawcę w rejestrze.',
        )

    # Umowy usuwamy razem z dostawcą — bez niego nie mają sensu.
    # flush() PRZED usunięciem dostawcy: bez tego SQLAlchemy może wysłać
    # DELETE dostawcy przed DELETE umów i klucz obcy odrzuci operację.
    for c in session.exec(
        select(VendorContract).where(VendorContract.vendor_id == vendor_id)
    ).all():
        session.delete(c)
    session.flush()
    session.delete(v)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
            "Nie można usunąć dostawcy — jest powiązany z innymi rekordami.")


def _validate_period(valid_from: Optional[datetime], valid_to: Optional[datetime]) -> None:
    if valid_from and valid_to and valid_from.date() > valid_to.date():
        raise HTTPException(400, "Data początku umowy jest późniejsza niż data końca.")
