"""
Router: Rejestr oprogramowania (systemy IT) i uprawnień — IT staff / admin.

Konwencje:
- Każdy zalogowany może czytać listę systemów i uprawnień (kierownik wydziału
  wybiera zakres do wniosku, pracownik ogląda „Moje uprawnienia" itp.).
- Zarządzać rejestrem (create/update/delete) może tylko IT staff / admin.
- Pole `access_only=True` oznacza „dostęp do systemu bez dodatkowych uprawnień".
  Dla takich systemów utrzymujemy w bazie dokładnie JEDNO syntetyczne
  `SystemPermission` o nazwie „Dostęp" — dzięki temu cały workflow wniosków
  (RequestItem.permission_id) pozostaje bez zmian. Router automatycznie
  dodaje/usuwa to uprawnienie przy zmianie flagi.
- Pole `all_units=True` oznacza „dostępne we wszystkich jednostkach".
  Gdy `all_units=False`, zakres definiowany jest tabelą M:N
  `PermissionSystemUnit`. Endpoint GET `/` przyjmuje opcjonalny
  `?unit_id=X` — wtedy zwraca systemy widoczne dla tej jednostki.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status,
)
from pydantic import BaseModel
from sqlalchemy import case
from sqlmodel import Session, select

from database import get_session
from models import (
    PermissionSystem,
    SoftwareVendor,
    PermissionSystemUnit,
    SystemPermission,
    Unit,
    User,
)
from services.auth_service import get_current_user
from services.permissions import require_it_staff

router = APIRouter()


ACCESS_PERM_NAME = "Dostęp"
# „Super uprawnienia" — dostępne domyślnie przy KAŻDYM oprogramowaniu, bez
# definiowania ich ręcznie. Utrzymywane jak `ACCESS_PERM_NAME`: syntetyczny
# wiersz SystemPermission, dzięki czemu przechodzą przez wniosek, ewidencję
# uprawnień i ślad audytowy tak samo jak zwykłe pozycje.
ADMIN_PERM_NAME = "Uprawnienia administratora"

# Nazwy zarezerwowane — administrator nie może ich utworzyć ręcznie.
SYNTHETIC_PERM_NAMES = (ACCESS_PERM_NAME, ADMIN_PERM_NAME)

# Uprawnienia usunięte miękko (usunięcie posiadanej grupy przez superadmina)
# zostają w bazie tylko dla historii — rejestr oprogramowania ich nie pokazuje
# i nie pozwala ich edytować, kopiować ani przywrócić.
_LIVE_PERM = SystemPermission.deleted_at == None  # noqa: E711


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _system_unit_ids(session: Session, system_id: int) -> list[int]:
    rows = session.exec(
        select(PermissionSystemUnit.unit_id)
        .where(PermissionSystemUnit.system_id == system_id)
    ).all()
    return sorted(int(r) for r in rows)


def _set_system_units(session: Session, system_id: int, unit_ids: list[int]) -> None:
    """Zastąp listę jednostek dla systemu."""
    # Zwaliduj, że jednostki istnieją (podniesie 400 na pierwszym błędnym).
    for uid in unit_ids:
        if not session.get(Unit, uid):
            raise HTTPException(400, f"Jednostka id={uid} nie istnieje")

    current = session.exec(
        select(PermissionSystemUnit).where(PermissionSystemUnit.system_id == system_id)
    ).all()
    for row in current:
        session.delete(row)
    # flush, żeby nie zderzyć się z PK przy ponownym insert tej samej pary
    session.flush()
    for uid in set(unit_ids):
        session.add(PermissionSystemUnit(system_id=system_id, unit_id=uid))


def _sync_access_only(session: Session, s: PermissionSystem) -> None:
    """Zapewnij spójność: dokładnie jedno syntetyczne uprawnienie „Dostęp".

    Dotyczy dwóch przypadków, w których administrator NIE definiuje listy
    uprawnień z góry:
      - `access_only=True` — sam dostęp do systemu,
      - system z POLAMI wypełnianymi przez wnioskodawcę — to kierownik wpisuje
        we wniosku, czego pracownik potrzebuje (np. nazwy rejestrów/modułów),
        więc lista predefiniowana jest zbędna.

    - Włączenie: jeśli nie ma żadnego uprawnienia, tworzymy „Dostęp".
      Jeśli są jakieś uprawnienia, błąd — użytkownik musi je najpierw usunąć
      (zabezpieczenie przed utratą kontekstu we wnioskach historycznych).
    - Wyłączenie: usuwamy syntetyczne „Dostęp" TYLKO jeśli jest
      jedynym uprawnieniem i nigdy nie było użyte we wniosku.
    """
    from models import RequestItem

    # „Uprawnienia administratora" są niezależne od trybu systemu — wykluczamy
    # je z tej logiki, inaczej blokowałyby tryb „tylko dostęp" i pola wnioskodawcy.
    perms = [p for p in session.exec(
        select(SystemPermission).where(SystemPermission.system_id == s.id)
    ).all() if p.permission_name != ADMIN_PERM_NAME]

    if s.access_only:
        if perms and not (len(perms) == 1 and perms[0].permission_name == ACCESS_PERM_NAME):
            msg = ('Nie można ustawić trybu "dostęp bez dodatkowych uprawnień" — '
                   'usuń najpierw istniejące uprawnienia w tym systemie.')
            raise HTTPException(400, msg)
        if not perms:
            p = SystemPermission(
                system_id=s.id,
                permission_name=ACCESS_PERM_NAME,
                description="Dostęp do systemu (bez dodatkowych uprawnień)",
            )
            session.add(p)
    else:
        # Wyłączamy access_only — usuwamy auto-uprawnienie „Dostęp", ale tylko
        # gdy nie jest referencjonowane przez żaden RequestItem.
        for p in perms:
            if p.permission_name != ACCESS_PERM_NAME:
                continue
            used = session.exec(
                select(RequestItem).where(RequestItem.permission_id == p.id)
            ).first()
            if not used:
                session.delete(p)


def _sync_admin_option(session: Session, s: PermissionSystem) -> None:
    """Utrzymuje syntetyczne „Uprawnienia administratora" zgodnie z flagą.

    Włączone → wiersz istnieje (można o nie wnioskować przy tym programie).
    Wyłączone → usuwamy, ale TYLKO gdy nie zostało użyte w żadnym wniosku
    (inaczej straciłaby sens historia uprawnień).
    """
    from models import RequestItem

    existing = session.exec(
        select(SystemPermission)
        .where(SystemPermission.system_id == s.id)
        .where(SystemPermission.permission_name == ADMIN_PERM_NAME)
    ).first()

    if getattr(s, "admin_option", True):
        if not existing:
            session.add(SystemPermission(
                system_id=s.id,
                permission_name=ADMIN_PERM_NAME,
                description="Pełne uprawnienia administracyjne w tym systemie",
            ))
    elif existing:
        used = session.exec(
            select(RequestItem).where(RequestItem.permission_id == existing.id)
        ).first()
        if not used:
            session.delete(existing)


# Typy pól dodatkowych definiowanych przy oprogramowaniu (format starszych baz —
# przy starcie `database._migrate_custom_fields_to_permissions` przenosi je na
# uprawnienia z kontrolką). "select" — jedna wartość z listy; "multiselect" —
# dowolnie wiele wartości (przechowywane jako tekst rozdzielony przecinkami, żeby
# `custom_values` pozostało prostą mapą label→tekst i działało w podglądzie
# wniosku i w rejestrze uprawnień).
CUSTOM_FIELD_TYPES = ("text", "textarea", "select", "multiselect")
# Typy wymagające zdefiniowanej listy opcji.
OPTION_FIELD_TYPES = ("select", "multiselect")

# Kontrolka doprecyzowująca POJEDYNCZE uprawnienie na wniosku.
# "none" = zwykły checkbox (tak wygląda wszystko, co przyszło z importu).
INPUT_TYPES = ("none", "text", "textarea", "radio", "select", "multiselect")
# Typy, przy których trzeba podać listę opcji.
INPUT_OPTION_TYPES = ("radio", "select", "multiselect")


def _parse_options(raw: Optional[str]) -> list[str]:
    """Opcje uprawnienia zapisane jako JSON → lista tekstów."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return _normalize_options(data if isinstance(data, list) else [])


def _validate_input(input_type: str, options: list[str]) -> tuple[str, Optional[str]]:
    """Sprawdź typ kontrolki i jej opcje; zwróć (typ, JSON opcji)."""
    t = (input_type or "none").strip() or "none"
    if t not in INPUT_TYPES:
        raise HTTPException(400, f'Nieznany typ kontrolki: "{t}".')
    opts = _normalize_options(options)
    if t in INPUT_OPTION_TYPES and not opts:
        raise HTTPException(
            400, "Dla listy wyboru podaj co najmniej jedną opcję.")
    if t not in INPUT_OPTION_TYPES:
        opts = []
    return t, (json.dumps(opts, ensure_ascii=False) if opts else None)


def _normalize_options(raw) -> list[str]:
    """Lista opcji dla pola typu `select` — bez pustych i bez duplikatów."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [p for p in raw.replace("\r", "").split("\n")]
    out: list[str] = []
    for o in raw:
        v = str(o or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def _normalize_field(d: dict) -> Optional[dict]:
    """Wspólna normalizacja pola dodatkowego (używana przy odczycie i zapisie).

    Zwraca None dla pól bez nazwy. Stare rekordy (bez `type`/`required`)
    domyślnie stają się polami tekstowymi, nieobowiązkowymi.
    """
    label = str(d.get("label") or "").strip()
    if not label:
        return None
    ftype = str(d.get("type") or "text").strip().lower()
    if ftype not in CUSTOM_FIELD_TYPES:
        ftype = "text"
    options = _normalize_options(d.get("options"))
    # Lista (jedno- i wielokrotnego wyboru) bez opcji nie ma sensu —
    # degraduj do pola tekstowego, żeby nie zostało pole nie do wypełnienia.
    if ftype in OPTION_FIELD_TYPES and not options:
        ftype = "text"
    if ftype not in OPTION_FIELD_TYPES:
        options = []
    return {
        "label": label,
        "description": (str(d.get("description") or "").strip() or None),
        "type": ftype,
        "required": bool(d.get("required")),
        "options": options,
        "value": (str(d.get("value") or "").strip() or None),
    }


def _parse_custom_fields(raw: Optional[str]) -> list[dict]:
    """Deserializuj pola dodatkowe zapisane przy PROGRAMIE (model historyczny).

    Zostaje wyłącznie na potrzeby jednorazowej migracji tych pól na uprawnienia
    z kontrolką (`_migrate_custom_fields_to_permissions` w database.py).
    Nowy kod definiuje kontrolkę przy pojedynczym uprawnieniu.
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        out = []
        for f in data:
            if not isinstance(f, dict):
                continue
            nf = _normalize_field(f)
            if nf:
                out.append(nf)
        return out
    except (json.JSONDecodeError, TypeError):
        return []


def _real_permission_count(session: Session, system_id: int) -> int:
    """Liczba REALNYCH uprawnień systemu — bez pozycji syntetycznych.

    Ma znaczenie dla filtra „bez ustawionych uprawnień" i dla przycisku
    „Ustaw domyślne": obecność samego „Dostępu" czy „Uprawnień administratora"
    NIE oznacza, że program jest skonfigurowany.
    """
    rows = session.exec(
        select(SystemPermission).where(SystemPermission.system_id == system_id)
    ).all()
    return sum(1 for p in rows
               if p.permission_name not in SYNTHETIC_PERM_NAMES
               and getattr(p, "is_active", True))


def _validate_display_order(session: Session, order: Optional[int],
                            self_id: Optional[int] = None) -> None:
    """Numer pozycji na wniosku musi być dodatni i niezajęty przez inny program.

    Unikalność jest globalna — numer wyznacza miejsce na jednej, wspólnej liście.
    """
    if order is None:
        return
    if order < 1:
        raise HTTPException(400, "Numer na wniosku musi być liczbą dodatnią (od 1).")
    q = select(PermissionSystem).where(PermissionSystem.display_order == order)
    if self_id is not None:
        q = q.where(PermissionSystem.id != self_id)
    taken = session.exec(q).first()
    if taken:
        raise HTTPException(
            400,
            f'Numer {order} jest już przypisany do „{taken.name}" — wybierz inny.',
        )


def _validate_vendor(session: Session, vendor_id: Optional[int]) -> None:
    """Dostawca musi istnieć w słowniku (None = brak przypisania)."""
    if vendor_id is None:
        return
    if not session.get(SoftwareVendor, vendor_id):
        raise HTTPException(400, "Wskazany dostawca nie istnieje w słowniku.")


def _serialize(session: Session, s: PermissionSystem) -> dict:
    vid = getattr(s, "vendor_id", None)
    vendor = session.get(SoftwareVendor, vid) if vid else None
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "is_active": s.is_active,
        "access_only": s.access_only,
        "all_units": s.all_units,
        "unit_ids": _system_unit_ids(session, s.id),
        # Pozwala odróżnić program SKONFIGUROWANY (ma listę uprawnień)
        # od takiego, który czeka na uzupełnienie.
        "permission_count": _real_permission_count(session, s.id),
        "display_order": getattr(s, "display_order", None),
        "default_checked": bool(getattr(s, "default_checked", False)),
        "admin_option": bool(getattr(s, "admin_option", True)),
        "require_scope": bool(getattr(s, "require_scope", False)),
        "vendor_id": vid,
        # Nazwa wprost, żeby front nie musiał dociągać słownika do listy.
        "vendor_name": (vendor.name if vendor else None),
    }


# ---------------------------------------------------------------------------
# Systemy
# ---------------------------------------------------------------------------

class SystemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    access_only: bool = False
    all_units: bool = True
    unit_ids: Optional[list[int]] = None   # używane gdy all_units=False
    display_order: Optional[int] = None    # pozycja na wniosku (None = bez numeru)
    default_checked: bool = False          # zaznaczone z góry na wniosku
    vendor_id: Optional[int] = None        # dostawca ze słownika
    admin_option: bool = True              # „Uprawnienia administratora" na wniosku
    require_scope: bool = True             # wymuś wybór zakresu poduprawnień (domyślnie tak)


class SystemRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    access_only: bool
    all_units: bool
    unit_ids: list[int]
    permission_count: int = 0
    display_order: Optional[int] = None
    default_checked: bool = False
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None
    admin_option: bool = True
    require_scope: bool = False


class SystemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    access_only: Optional[bool] = None
    all_units: Optional[bool] = None
    unit_ids: Optional[list[int]] = None   # jeśli podano — zastąp listę
    display_order: Optional[int] = None
    default_checked: Optional[bool] = None
    vendor_id: Optional[int] = None
    admin_option: Optional[bool] = None
    require_scope: Optional[bool] = None


@router.get("/", response_model=list[SystemRead])
def list_systems(
    unit_id: Optional[int] = Query(None, description="Filtruj: tylko systemy widoczne dla tej jednostki"),
    active_only: bool = Query(False, description="Zwróć tylko is_active=True"),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    # Kolejność na wniosku: najpierw pozycje ponumerowane (rosnąco), potem
    # reszta alfabetycznie. To JEDYNE miejsce sortowania systemów — wszystkie
    # widoki (pickery kierownika/IT, rejestr) renderują listę w tej kolejności.
    q = select(PermissionSystem).order_by(
        case((PermissionSystem.display_order.is_(None), 1), else_=0),
        PermissionSystem.display_order,
        PermissionSystem.name,
    )
    if active_only:
        q = q.where(PermissionSystem.is_active == True)  # noqa: E712
    rows = session.exec(q).all()

    if unit_id is not None:
        scoped_ids = {
            int(x) for x in session.exec(
                select(PermissionSystemUnit.system_id)
                .where(PermissionSystemUnit.unit_id == unit_id)
            ).all()
        }
        rows = [s for s in rows if s.all_units or s.id in scoped_ids]

    return [_serialize(session, s) for s in rows]


@router.post("/", response_model=SystemRead, status_code=status.HTTP_201_CREATED)
def create_system(
    data: SystemCreate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    _validate_display_order(session, data.display_order)
    _validate_vendor(session, data.vendor_id)
    s = PermissionSystem(
        name=data.name,
        description=data.description,
        access_only=data.access_only,
        all_units=data.all_units,
        display_order=data.display_order,
        default_checked=bool(data.default_checked),
        vendor_id=data.vendor_id,
        admin_option=bool(data.admin_option),
        require_scope=bool(data.require_scope),
    )
    session.add(s)
    session.commit()
    session.refresh(s)

    if not data.all_units:
        _set_system_units(session, s.id, data.unit_ids or [])

    _sync_access_only(session, s)
    _sync_admin_option(session, s)
    session.commit()
    session.refresh(s)
    return _serialize(session, s)


@router.patch("/{system_id}", response_model=SystemRead)
def update_system(
    system_id: int,
    data: SystemUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    s = session.get(PermissionSystem, system_id)
    if not s:
        raise HTTPException(404, "System nie istnieje")

    payload = data.model_dump(exclude_unset=True)
    unit_ids = payload.pop("unit_ids", None)
    # Numer pozycji — sprawdzamy PRZED zapisem; własny numer nie koliduje sam ze sobą.
    if "display_order" in payload:
        _validate_display_order(session, payload["display_order"], self_id=s.id)
    if "vendor_id" in payload:
        _validate_vendor(session, payload["vendor_id"])
    for field, value in payload.items():
        setattr(s, field, value)
    session.add(s)

    # Zarządzaj zakresem jednostek:
    # - jeśli all_units ustawione na True: wyczyść listę
    # - jeśli unit_ids podane: zastąp listę (niezależnie od all_units,
    #   żeby użytkownik mógł przygotować listę zanim zdejmie „all_units")
    if s.all_units:
        current = session.exec(
            select(PermissionSystemUnit).where(PermissionSystemUnit.system_id == s.id)
        ).all()
        for row in current:
            session.delete(row)
        session.flush()
    if unit_ids is not None and not s.all_units:
        _set_system_units(session, s.id, unit_ids)

    _sync_access_only(session, s)
    _sync_admin_option(session, s)
    session.commit()
    session.refresh(s)
    return _serialize(session, s)


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_system(
    system_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    s = session.get(PermissionSystem, system_id)
    if not s:
        raise HTTPException(404, "System nie istnieje")

    # Nie pozwól usunąć systemu, dla którego istnieją uprawnienia INNE niż
    # syntetyczny „Dostęp" (bo to oznacza realne uprawnienia we wnioskach).
    perms = session.exec(
        select(SystemPermission).where(SystemPermission.system_id == system_id)
    ).all()
    real = [p for p in perms if p.permission_name != ACCESS_PERM_NAME]
    if real:
        raise HTTPException(400, "Nie można usunąć systemu — posiada uprawnienia")

    # Jeśli jedyne uprawnienie to syntetyczny „Dostęp" i nie było użyte,
    # pozwalamy usunąć (kaskadowo czyścimy powiązania).
    from models import RequestItem
    for p in perms:
        used = session.exec(
            select(RequestItem).where(RequestItem.permission_id == p.id)
        ).first()
        if used:
            raise HTTPException(400, "Nie można usunąć systemu — występuje we wnioskach")
        session.delete(p)

    # Czyszczenie powiązań z jednostkami.
    links = session.exec(
        select(PermissionSystemUnit).where(PermissionSystemUnit.system_id == system_id)
    ).all()
    for row in links:
        session.delete(row)

    session.delete(s)
    session.commit()


# ---------------------------------------------------------------------------
# Uprawnienia w systemie
# ---------------------------------------------------------------------------

class PermCreate(BaseModel):
    permission_name: str
    description: Optional[str] = None
    # Grupa, do której trafia uprawnienie. Cała logika panelu opiera się o grupy,
    # więc pozycje dodaje się WEWNĄTRZ grupy. Puste = bez grupy (pozycja luźna).
    group_name: Optional[str] = None
    # Podgrupa wewnątrz grupy (opcjonalnie). Puste = bezpośrednio w grupie.
    subgroup_name: Optional[str] = None
    # Kontrolka doprecyzowująca uprawnienie (lista / pole). Domyślnie brak —
    # uprawnienie jest wtedy zwykłym checkboxem, jak pozycje z importu.
    input_type: str = "none"
    options: list[str] = []
    input_required: bool = False
    input_prompt: Optional[str] = None


class PermRead(BaseModel):
    id: int
    system_id: int
    permission_name: str
    description: Optional[str]
    # Znaczniki pozycji syntetycznych — front rozróżnia je bez dopasowywania
    # polskich nazw (te mogłyby się zmienić).
    is_admin_option: bool = False
    is_access_only: bool = False
    # Grupa uprawnień (np. „Rejestry opłat") — front renderuje sekcje.
    group_name: Optional[str] = None
    group_order: Optional[int] = None
    # Podgrupa wewnątrz grupy — drugi poziom sekcji.
    subgroup_name: Optional[str] = None
    subgroup_order: Optional[int] = None
    external_code: Optional[str] = None
    # False = pozycja wycofana ze źródła; zostaje w ewidencji, znika z wyboru.
    is_active: bool = True
    input_type: str = "none"
    options: list[str] = []
    input_required: bool = False
    input_prompt: Optional[str] = None


def _perm_read(p: SystemPermission) -> "PermRead":
    return PermRead(
        id=p.id, system_id=p.system_id,
        permission_name=p.permission_name, description=p.description,
        is_admin_option=(p.permission_name == ADMIN_PERM_NAME),
        is_access_only=(p.permission_name == ACCESS_PERM_NAME),
        group_name=getattr(p, "group_name", None),
        group_order=getattr(p, "group_order", None),
        subgroup_name=getattr(p, "subgroup_name", None),
        subgroup_order=getattr(p, "subgroup_order", None),
        external_code=getattr(p, "external_code", None),
        is_active=bool(getattr(p, "is_active", True)),
        input_type=getattr(p, "input_type", None) or "none",
        options=_parse_options(getattr(p, "options", None)),
        input_required=bool(getattr(p, "input_required", False)),
        input_prompt=getattr(p, "input_prompt", None),
    )


class PermUpdate(BaseModel):
    permission_name: Optional[str] = None
    description: Optional[str] = None
    # Przeniesienie pozycji między grupami (albo wyjęcie z grupy). Pusty string
    # = bez grupy; None (pole pominięte) = grupa bez zmian.
    group_name: Optional[str] = None
    # Przypisanie / zmiana podgrupy. Pusty string = bez podgrupy; None = bez zmian.
    subgroup_name: Optional[str] = None
    input_type: Optional[str] = None
    options: Optional[list[str]] = None
    input_required: Optional[bool] = None
    input_prompt: Optional[str] = None


@router.get("/{system_id}/permissions", response_model=list[PermRead])
def list_permissions(
    system_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    rows = session.exec(
        select(SystemPermission).where(SystemPermission.system_id == system_id)
        .where(_LIVE_PERM)
        .order_by(SystemPermission.permission_name)
    ).all()
    # Pozycja administratora zawsze na koncu listy - to wyjatek, nie powinna
    # gubic sie alfabetycznie miedzy zwyklymi uprawnieniami.
    # Kolejność: pozycje bez grupy (dodane ręcznie) najpierw, potem grupy
    # alfabetycznie, a pozycja administratora zawsze na samym końcu — to
    # wyjątek, nie powinna gubić się między zwykłymi uprawnieniami.
    rows = sorted(rows, key=lambda p: (
        p.permission_name == ADMIN_PERM_NAME,
        (getattr(p, "group_name", None) or "").lower() != "",
        (getattr(p, "group_name", None) or "").lower(),
        p.permission_name.lower(),
    ))
    return [_perm_read(p) for p in rows]


@router.post("/{system_id}/permissions", response_model=PermRead, status_code=status.HTTP_201_CREATED)
def create_permission(
    system_id: int,
    data: PermCreate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    s = session.get(PermissionSystem, system_id)
    if not s:
        raise HTTPException(404, "System nie istnieje")
    if s.access_only:
        raise HTTPException(
            400,
            'System jest w trybie "dostęp bez dodatkowych uprawnień" — '
            'najpierw wyłącz ten tryb aby dodawać uprawnienia.',
        )
    if data.permission_name.strip() == ADMIN_PERM_NAME:
        raise HTTPException(
            400,
            f'Nazwa "{data.permission_name.strip()}" jest zarezerwowana - '
            f'te pozycje system utrzymuje sam (patrz opcje oprogramowania).',
        )
    itype, iopts = _validate_input(data.input_type, data.options)
    p = SystemPermission(
        system_id=system_id,
        permission_name=data.permission_name,
        description=data.description,
        group_name=(data.group_name or "").strip() or None,
        subgroup_name=(data.subgroup_name or "").strip() or None,
        input_type=itype,
        options=iopts,
        input_required=bool(data.input_required),
        input_prompt=(data.input_prompt or "").strip() or None,
    )
    session.add(p); session.commit(); session.refresh(p)
    return _perm_read(p)


# Domyślne uprawnienie („ustaw domyślne" przy istniejącym programie).
DEFAULT_PERMISSION = {
    "name": "Zakres uprawnień",
    "input_type": "textarea",
    "description": ("Należy wpisać wszystkie moduły lub rejestry, "
                    "do których użytkownik powinien mieć dostęp"),
}


class CopyPermsIn(BaseModel):
    # Albo kopiujemy z innego programu, albo ustawiamy definicję domyślną.
    source_system_id: Optional[int] = None
    use_default: bool = False


class CopyPermsResult(BaseModel):
    mode: str            # "fields" | "list"
    fields_copied: int
    permissions_copied: int
    details: list[str]


@router.post("/{system_id}/copy-permissions", response_model=CopyPermsResult)
def copy_permissions(
    system_id: int,
    data: CopyPermsIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Skopiuj definicję uprawnień z innego oprogramowania.

    Przydatne, gdy programy wprowadzono bez poziomów uprawnień — zamiast
    wpisywać wszystko od nowa, bierzemy gotowy wzorzec z innego systemu.
    Kopiujemy pozycje razem z ich kontrolkami (lista / pole) i grupami;
    pozycje, które cel już ma (po nazwie), pomijamy.

    `use_default=True` zakłada jedno uprawnienie „Zakres uprawnień" z polem
    opisowym — w urzędzie prawie każdy program sprowadza się do „wypisz
    moduły/rejestry", więc nie każemy tego wpisywać od zera.
    """
    target = session.get(PermissionSystem, system_id)
    if not target:
        raise HTTPException(404, "System nie istnieje")
    if target.access_only:
        raise HTTPException(
            400,
            'To oprogramowanie jest w trybie „dostęp bez dodatkowych uprawnień" — '
            'wyłącz ten tryb, żeby definiować uprawnienia.',
        )

    details: list[str] = []
    if data.use_default:
        src_perms = [SystemPermission(
            system_id=target.id,
            permission_name=DEFAULT_PERMISSION["name"],
            description=DEFAULT_PERMISSION["description"],
            input_type=DEFAULT_PERMISSION["input_type"],
            input_required=True,
        )]
    else:
        if data.source_system_id is None:
            raise HTTPException(400, "Wskaż oprogramowanie źródłowe")
        source = session.get(PermissionSystem, data.source_system_id)
        if not source:
            raise HTTPException(400, "Wskazane oprogramowanie źródłowe nie istnieje")
        if source.id == target.id:
            raise HTTPException(400, "Nie można kopiować z tego samego oprogramowania")
        src_perms = [p for p in session.exec(
            select(SystemPermission).where(SystemPermission.system_id == source.id)
            .where(_LIVE_PERM)
        ).all() if p.permission_name not in SYNTHETIC_PERM_NAMES]
        if not src_perms:
            raise HTTPException(
                400,
                f'Oprogramowanie „{source.name}" nie ma zdefiniowanych uprawnień '
                f'— nie ma czego skopiować.',
            )

    have = {p.permission_name for p in session.exec(
        select(SystemPermission).where(SystemPermission.system_id == target.id)
        .where(_LIVE_PERM)
    ).all()}
    copied = 0
    for p in src_perms:
        if p.permission_name in have:
            details.append(f'pominięto „{p.permission_name}" — już istnieje')
            continue
        session.add(SystemPermission(
            system_id=target.id,
            permission_name=p.permission_name,
            description=p.description,
            # Kopia zachowuje podział na grupy, podgrupy i kontrolki — inaczej
            # wzorzec rozsypałby się w płaską listę samych checkboxów.
            group_name=getattr(p, "group_name", None),
            subgroup_name=getattr(p, "subgroup_name", None),
            external_code=getattr(p, "external_code", None),
            input_type=getattr(p, "input_type", None) or "none",
            options=getattr(p, "options", None),
            input_required=bool(getattr(p, "input_required", False)),
            input_prompt=getattr(p, "input_prompt", None),
        ))
        copied += 1
        details.append(f'skopiowano uprawnienie „{p.permission_name}"')
    session.add(target)
    session.commit()
    return CopyPermsResult(mode="list", fields_copied=0,
                           permissions_copied=copied, details=details)


class CopyGroupIn(BaseModel):
    source_system_id: int
    group_name: str
    # Docelowa nazwa grupy w tym programie (domyślnie ta sama co źródłowa).
    target_group_name: Optional[str] = None


class CopyGroupResult(BaseModel):
    group_name: str
    copied: int
    skipped: int


@router.post("/{system_id}/copy-group", response_model=CopyGroupResult)
def copy_permission_group(
    system_id: int,
    data: CopyGroupIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Skopiuj JEDNĄ grupę uprawnień z innego programu do tego.

    Pozwala wielokrotnie użyć raz zdefiniowanej grupy (np. „Rejestry księgowe")
    w kolejnych programach bez wpisywania od nowa. Kopiuje pozycje grupy razem
    z ich kontrolkami; pozycje, które cel już ma w grupie docelowej (po nazwie),
    pomijamy.
    """
    target = session.get(PermissionSystem, system_id)
    if not target:
        raise HTTPException(404, "System nie istnieje")
    if target.access_only:
        raise HTTPException(
            400,
            'To oprogramowanie jest w trybie „dostęp bez dodatkowych uprawnień" — '
            'wyłącz ten tryb, żeby definiować uprawnienia.',
        )
    source = session.get(PermissionSystem, data.source_system_id)
    if not source:
        raise HTTPException(400, "Wskazane oprogramowanie źródłowe nie istnieje")
    if source.id == target.id:
        raise HTTPException(400, "Nie można kopiować z tego samego oprogramowania")

    src_group = (data.group_name or "").strip()
    if not src_group:
        raise HTTPException(400, "Wskaż grupę do skopiowania")
    tgt_group = (data.target_group_name or src_group).strip() or src_group

    src_perms = [p for p in session.exec(
        select(SystemPermission).where(SystemPermission.system_id == source.id)
        .where(_LIVE_PERM)
    ).all() if p.permission_name not in SYNTHETIC_PERM_NAMES
        and (getattr(p, "group_name", None) or "") == src_group]
    if not src_perms:
        raise HTTPException(
            400, f'Grupa „{src_group}" w programie „{source.name}" jest pusta lub nie istnieje.')

    # Pomijamy pozycje już obecne w grupie DOCELOWEJ (ta sama nazwa) — pozwala
    # bezpiecznie „dopisać" brakujące bez dublowania.
    have = {p.permission_name for p in session.exec(
        select(SystemPermission)
        .where(SystemPermission.system_id == target.id)
        .where(SystemPermission.group_name == tgt_group)
        .where(_LIVE_PERM)
    ).all()}

    copied = skipped = 0
    for p in src_perms:
        if p.permission_name in have:
            skipped += 1
            continue
        session.add(SystemPermission(
            system_id=target.id,
            permission_name=p.permission_name,
            description=p.description,
            group_name=tgt_group,
            subgroup_name=getattr(p, "subgroup_name", None),
            external_code=getattr(p, "external_code", None),
            input_type=getattr(p, "input_type", None) or "none",
            options=getattr(p, "options", None),
            input_required=bool(getattr(p, "input_required", False)),
            input_prompt=getattr(p, "input_prompt", None),
        ))
        copied += 1
    session.commit()
    return CopyGroupResult(group_name=tgt_group, copied=copied, skipped=skipped)


@router.patch("/permissions/{perm_id}", response_model=PermRead)
def update_permission(
    perm_id: int,
    data: PermUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    p = session.get(SystemPermission, perm_id)
    if not p or getattr(p, "deleted_at", None):
        raise HTTPException(404, "Uprawnienie nie istnieje")
    if p.permission_name == ADMIN_PERM_NAME or (
        data.permission_name or ""
    ).strip() == ADMIN_PERM_NAME:
        raise HTTPException(
            400,
            'Pozycję „Uprawnienia administratora" system utrzymuje sam — '
            'zmień ustawienia oprogramowania zamiast edytować wpis.',
        )
    payload = data.model_dump(exclude_none=True)
    if "input_type" in payload or "options" in payload:
        itype, iopts = _validate_input(
            payload.get("input_type", getattr(p, "input_type", "none")),
            payload.get("options", _parse_options(getattr(p, "options", None))),
        )
        payload["input_type"] = itype
        payload["options"] = iopts
    # Pusta nazwa grupy = wyjęcie z grupy (NULL w bazie, nie pusty string —
    # inaczej groupPerms i endpointy grupowe traktowałyby ją niespójnie).
    if "group_name" in payload:
        payload["group_name"] = (payload["group_name"] or "").strip() or None
    if "subgroup_name" in payload:
        payload["subgroup_name"] = (payload["subgroup_name"] or "").strip() or None
    if "input_prompt" in payload:
        payload["input_prompt"] = (payload["input_prompt"] or "").strip() or None
    for field, value in payload.items():
        setattr(p, field, value)
    session.add(p); session.commit(); session.refresh(p)
    return _perm_read(p)


@router.delete("/permissions/{perm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permission(
    perm_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    p = session.get(SystemPermission, perm_id)
    if not p or getattr(p, "deleted_at", None):
        raise HTTPException(404, "Uprawnienie nie istnieje")
    # Blokada przed usunięciem syntetycznego „Dostęp" gdy system jest access_only.
    s = session.get(PermissionSystem, p.system_id)
    if p.permission_name == ADMIN_PERM_NAME and getattr(s, "admin_option", True):
        raise HTTPException(
            400,
            'Pozycja "Uprawnienia administratora" jest utrzymywana automatycznie - '
            'odznacz ja w ustawieniach oprogramowania, zeby ja usunac.',
        )
    if s and s.access_only and p.permission_name == ACCESS_PERM_NAME:
        raise HTTPException(
            400,
            'Nie można usunąć uprawnienia "Dostęp" w systemie access-only — '
            'wyłącz najpierw ten tryb.',
        )
    session.delete(p); session.commit()


# ---------------------------------------------------------------------------
# Import list uprawnień z plików (CSV / TSV / Excel / wklejenie ze schowka)
# ---------------------------------------------------------------------------
#
# Dwa kroki, celowo:
#   1. /import/preview — parsuje plik i pokazuje, co z niego wyszło,
#   2. /import/commit  — zapisuje DOKŁADNIE to, co użytkownik ma na ekranie.
#
# Rozdzielenie daje ręczną korektę (poprawki nazw, odznaczenie pozycji) bez
# ponownego parsowania — commit nie może zapisać czegoś innego, niż widać.

MAX_IMPORT_BYTES = 2 * 1024 * 1024
# Zapas na nagłówki multipart i pola formularza (wklejone dane, mapowanie kolumn).
_MAX_IMPORT_REQUEST_BYTES = MAX_IMPORT_BYTES + 512 * 1024
_TOO_LARGE_MSG = f"Plik jest większy niż {MAX_IMPORT_BYTES // (1024 * 1024)} MB."


async def _read_upload_limited(file: UploadFile) -> bytes:
    """Wczytaj plik z limitem rozmiaru — porcjami, bez trzymania w pamięci
    więcej niż MAX_IMPORT_BYTES (+1 porcja). Rozmiar znany z parsera
    (`UploadFile.size`) sprawdzamy, zanim cokolwiek przeczytamy."""
    if file.size is not None and file.size > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, _TOO_LARGE_MSG)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_IMPORT_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, _TOO_LARGE_MSG)
        chunks.append(chunk)
    return b"".join(chunks)


class ImportColumn(BaseModel):
    index: int
    header: str
    role: str
    samples: list[str]


class ImportItemOut(BaseModel):
    permission_name: str
    description: Optional[str] = None
    external_code: Optional[str] = None
    status: str                      # new | existing | reactivate


class ImportPreviewOut(BaseModel):
    columns: list[ImportColumn]
    group_suggested: Optional[str]
    items: list[ImportItemOut]
    warnings: list[str]
    existing_in_group: int           # ile pozycji ma już ta grupa w bazie


class ImportItemIn(BaseModel):
    permission_name: str
    description: Optional[str] = None
    external_code: Optional[str] = None


class ImportCommitIn(BaseModel):
    group_name: str
    items: list[ImportItemIn]
    # Pozycje, których nie ma w pliku, wygaszamy (nie kasujemy — patrz model).
    deactivate_missing: bool = True


class ImportCommitOut(BaseModel):
    added: int
    reactivated: int
    updated: int
    deactivated: int
    skipped: int
    details: list[str]


def _importable_system(session: Session, system_id: int) -> PermissionSystem:
    """System, do którego wolno zaimportować listę uprawnień.

    Lista predefiniowana wyklucza się z trybem „tylko dostęp" i z polami
    wypełnianymi przez wnioskodawcę — ta sama reguła, której pilnuje
    `_sync_access_only`. Lepiej odmówić z wyjaśnieniem, niż po cichu zbudować
    system, który pyta o zakres i jednocześnie ma listę.
    """
    s = session.get(PermissionSystem, system_id)
    if not s:
        raise HTTPException(404, "System nie istnieje")
    if s.access_only:
        raise HTTPException(
            400,
            'To oprogramowanie jest w trybie „dostęp bez dodatkowych uprawnień" — '
            'wyłącz ten tryb, żeby zaimportować listę uprawnień.',
        )
    return s


def _group_perms(session: Session, system_id: int, group: str) -> list[SystemPermission]:
    """Pozycje danej grupy — bez syntetycznych, które utrzymuje router."""
    rows = session.exec(
        select(SystemPermission)
        .where(SystemPermission.system_id == system_id)
        .where(SystemPermission.group_name == group)
        .where(_LIVE_PERM)
    ).all()
    return [p for p in rows if p.permission_name not in SYNTHETIC_PERM_NAMES]


def _match_key(code: Optional[str], name: str) -> str:
    """Klucz dopasowania przy ponownym imporcie.

    Symbol ma pierwszeństwo — nazwa opisowa w systemie źródłowym bywa
    poprawiana i nie może zrywać ciągłości pozycji.
    """
    if code and code.strip():
        return f"c:{code.strip().lower()}"
    return f"n:{name.strip().lower()}"


@router.post("/{system_id}/permissions/import/preview", response_model=ImportPreviewOut)
async def preview_permission_import(
    system_id: int,
    request: Request,
    file: Optional[UploadFile] = File(None),
    pasted: Optional[str] = Form(None),
    group_name: Optional[str] = Form(None),
    roles: Optional[str] = Form(None),      # JSON: ["ignore","code","name",...]
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    from services import perm_import

    # Zadeklarowany rozmiar żądania ponad limit — odrzucamy bez czytania pliku.
    # (Body i tak sparsował już serwer; twardy limit przed aplikacją daje
    # LimitRequestBody w deploy/szup-apache.conf.)
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > _MAX_IMPORT_REQUEST_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, _TOO_LARGE_MSG)

    _importable_system(session, system_id)

    raw = None
    filename = None
    if file is not None:
        raw = await _read_upload_limited(file)
        filename = file.filename
    if not raw and not (pasted or "").strip():
        raise HTTPException(400, "Wskaż plik albo wklej dane.")

    roles_override = None
    if roles:
        try:
            parsed = json.loads(roles)
        except json.JSONDecodeError:
            raise HTTPException(400, "Nieprawidłowe mapowanie kolumn.")
        if not isinstance(parsed, list) or any(r not in perm_import.ROLES for r in parsed):
            raise HTTPException(400, "Nieprawidłowe role kolumn.")
        roles_override = parsed

    try:
        layout, items, warnings = perm_import.parse(
            raw=raw, filename=filename, pasted=pasted, roles_override=roles_override)
    except perm_import.ImportError_ as e:
        raise HTTPException(400, str(e))

    # Status każdej pozycji względem tego, co już jest w tej grupie.
    group = (group_name or layout.group_suggested or "").strip()
    existing = _group_perms(session, system_id, group) if group else []
    by_key = {_match_key(getattr(p, "external_code", None), p.permission_name): p
              for p in existing}

    out_items = []
    for it in items:
        match = by_key.get(_match_key(it.external_code, it.permission_name))
        if match is None:
            st = "new"
        elif getattr(match, "is_active", True):
            st = "existing"
        else:
            st = "reactivate"
        out_items.append(ImportItemOut(
            permission_name=it.permission_name, description=it.description,
            external_code=it.external_code, status=st))

    return ImportPreviewOut(
        columns=[ImportColumn(index=c.index, header=c.header, role=c.role,
                              samples=c.samples) for c in layout.columns],
        group_suggested=layout.group_suggested,
        items=out_items,
        warnings=warnings,
        existing_in_group=len(existing),
    )


@router.post("/{system_id}/permissions/import/commit", response_model=ImportCommitOut)
def commit_permission_import(
    system_id: int,
    data: ImportCommitIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    _importable_system(session, system_id)

    group = data.group_name.strip()
    if not group:
        raise HTTPException(400, "Podaj nazwę grupy uprawnień.")
    if not data.items:
        raise HTTPException(400, "Brak pozycji do zaimportowania.")

    existing = _group_perms(session, system_id, group)
    by_key = {_match_key(getattr(p, "external_code", None), p.permission_name): p
              for p in existing}

    added = reactivated = updated = skipped = 0
    seen_keys: set[str] = set()
    details: list[str] = []

    for it in data.items:
        name = (it.permission_name or "").strip()
        if not name:
            skipped += 1
            continue
        if name == ADMIN_PERM_NAME:
            # Pozycję administratora utrzymuje `_sync_admin_option` — import
            # nie może jej podrobić ani zduplikować.
            skipped += 1
            details.append(f'pominięto „{name}" — pozycja zarezerwowana')
            continue

        code = (it.external_code or "").strip() or None
        key = _match_key(code, name)
        if key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(key)

        p = by_key.get(key)
        if p is None:
            session.add(SystemPermission(
                system_id=system_id, permission_name=name,
                description=it.description, group_name=group,
                external_code=code, is_active=True,
            ))
            added += 1
            continue

        was_inactive = not getattr(p, "is_active", True)
        p.permission_name = name
        p.description = it.description
        p.external_code = code
        p.is_active = True
        session.add(p)
        if was_inactive:
            reactivated += 1
        else:
            updated += 1

    deactivated = 0
    if data.deactivate_missing:
        for p in existing:
            key = _match_key(getattr(p, "external_code", None), p.permission_name)
            if key in seen_keys or not getattr(p, "is_active", True):
                continue
            p.is_active = False
            session.add(p)
            deactivated += 1
            details.append(f'wygaszono „{p.permission_name}" — brak w pliku')

    session.commit()
    return ImportCommitOut(added=added, reactivated=reactivated, updated=updated,
                           deactivated=deactivated, skipped=skipped, details=details)


class GroupRenameIn(BaseModel):
    group_name: str
    new_name: str


@router.post("/{system_id}/permissions/group-rename", response_model=ImportCommitOut)
def rename_permission_group(
    system_id: int,
    data: GroupRenameIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Zmień nazwę grupy uprawnień.

    Nazwa jest podawana ręcznie przy imporcie, więc literówka jest kwestią
    czasu — bez tego jedynym wyjściem byłby ponowny import wszystkiego.
    """
    old = data.group_name.strip()
    new = data.new_name.strip()
    if not new:
        raise HTTPException(400, "Podaj nową nazwę grupy.")

    rows = _group_perms(session, system_id, old)
    if not rows:
        raise HTTPException(404, "Grupa nie istnieje w tym oprogramowaniu.")
    if new == old:
        return ImportCommitOut(added=0, reactivated=0, updated=0,
                               deactivated=0, skipped=0, details=[])
    if _group_perms(session, system_id, new):
        raise HTTPException(
            400,
            f'Grupa „{new}" już istnieje w tym oprogramowaniu. Wybierz inną '
            f'nazwę — scalanie grup mogłoby stworzyć duplikaty uprawnień.',
        )

    for p in rows:
        p.group_name = new
        session.add(p)
    session.commit()
    return ImportCommitOut(added=0, reactivated=0, updated=len(rows),
                           deactivated=0, skipped=0, details=[])


class GroupDeleteIn(BaseModel):
    group_name: str
    # Wymagany, gdy ktoś posiada uprawnienia z grupy (usuwa wtedy superadmin) —
    # trafia do audytu, wniosków o odebranie i odmówionych pozycji wniosków.
    reason: Optional[str] = None


class GroupDeleteOut(ImportCommitOut):
    # Tylko przy usunięciu grupy, którą ktoś posiadał (superadmin):
    affected_user_ids: list[int] = []
    revoke_request_ids: list[int] = []          # systemowe wnioski o odebranie (completed)
    updated_request_ids: list[int] = []         # wnioski w toku z odmówionymi pozycjami


class GroupHolderOut(BaseModel):
    user_id: int
    full_name: Optional[str] = None
    username: Optional[str] = None
    permissions: list[str]


class GroupUsageOut(BaseModel):
    holders: list[GroupHolderOut]
    in_progress_requests: list[int]


from models import RequestStatus as _RS  # noqa: E402
_IN_PROGRESS_STATUSES = (_RS.pending_selection, _RS.pending_manager, _RS.pending_it)


def _group_holders(session: Session, perm_ids: list[int]) -> list[tuple[User, list[dict]]]:
    """Osoby, które OBECNIE posiadają którekolwiek z `perm_ids` — wg uprawnień
    efektywnych (`routers.users._effective_permissions`: nadania minus
    odebrania z ukończonych wniosków). Zwraca [(użytkownik, pozycje)]."""
    from models import AccessRequest, RequestItem, RequestStatus
    from routers.users import _effective_permissions
    if not perm_ids:
        return []
    wanted = set(perm_ids)
    uids = session.exec(
        select(AccessRequest.worker_user_id)
        .join(RequestItem, RequestItem.request_id == AccessRequest.id)
        .where(RequestItem.permission_id.in_(perm_ids))
        .where(AccessRequest.status == RequestStatus.completed)
        .where(AccessRequest.worker_user_id != None)  # noqa: E711
        .distinct()
    ).all()
    out: list[tuple[User, list[dict]]] = []
    for uid in sorted({int(u) for u in uids if u}):
        held = [e for e in _effective_permissions(session, uid)["permissions"]
                if e["permission_id"] in wanted]
        user = session.get(User, uid)
        if held and user:
            out.append((user, held))
    return out


def _group_in_progress(session: Session, perm_ids: list[int]) -> list[int]:
    """Wnioski w toku, które zawierają (nieodmówione) pozycje z `perm_ids`."""
    from models import AccessRequest, RequestItem
    if not perm_ids:
        return []
    rows = session.exec(
        select(AccessRequest.id)
        .join(RequestItem, RequestItem.request_id == AccessRequest.id)
        .where(RequestItem.permission_id.in_(perm_ids))
        .where(RequestItem.denied == False)  # noqa: E712
        .where(AccessRequest.status.in_(_IN_PROGRESS_STATUSES))
        .distinct()
    ).all()
    return sorted(int(r) for r in rows)


@router.get("/{system_id}/permissions/group-usage", response_model=GroupUsageOut)
def permission_group_usage(
    system_id: int,
    group_name: str = Query(...),
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Kto posiada uprawnienia z grupy i które wnioski w toku je zawierają —
    przed usunięciem grupy (posiadaną grupę usuwa wyłącznie superadmin)."""
    rows = _group_perms(session, system_id, group_name.strip())
    if not rows:
        raise HTTPException(404, "Grupa nie istnieje w tym oprogramowaniu.")
    ids = [p.id for p in rows]
    holders = [
        GroupHolderOut(user_id=u.id, full_name=u.full_name, username=u.username,
                       permissions=[e["permission_name"] or "" for e in held])
        for u, held in _group_holders(session, ids)
    ]
    return GroupUsageOut(holders=holders,
                         in_progress_requests=_group_in_progress(session, ids))


def _system_revoke_request(session: Session, actor: User, user: User,
                           held: list[dict], comment: str, now) -> int:
    """Systemowy, od razu ZREALIZOWANY wniosek o odebranie posiadanych pozycji —
    dzięki niemu uprawnienia efektywne, migawki i historia wniosków pracownika
    pokazują odebranie. Komórka: bieżąca komórka pracownika, a gdy brak —
    komórka wniosku, którym nadano uprawnienie."""
    from models import AccessRequest, Department, RequestItem, RequestStatus
    dept = session.get(Department, user.department_id) if user.department_id else None
    if dept is not None and getattr(dept, "archived_at", None):
        dept = None
    if dept is not None:
        unit_id, dept_id = dept.unit_id, dept.id
    else:
        src = session.get(AccessRequest, held[0]["request_id"])
        unit_id, dept_id = src.unit_id, src.department_id
    actor_name = actor.full_name or actor.username
    req = AccessRequest(
        worker_name=user.full_name or user.username,
        worker_email=user.email,
        worker_position=getattr(user, "title", None) or None,
        worker_user_id=user.id,
        unit_id=unit_id, department_id=dept_id,
        kind="revoke",
        status=RequestStatus.completed,
        created_by_id=actor.id, created_by_name=actor_name,
        approved_by_id=actor.id, completed_by_id=actor.id,
        manager_comment=comment, it_comment=comment,
        created_at=now, approved_at=now, completed_at=now,
    )
    session.add(req)
    session.flush()
    for e in held:
        session.add(RequestItem(
            request_id=req.id, system_id=e["system_id"],
            permission_id=e["permission_id"], kind="revoke",
            added_by_user_id=actor.id,
            fulfilled=True, fulfilled_by_user_id=actor.id, fulfilled_at=now,
        ))
    return req.id


def _delete_held_group(session: Session, request: Request, actor: User,
                       system_id: int, group: str, rows: list[SystemPermission],
                       holders: list[tuple[User, list[dict]]],
                       reason: str) -> GroupDeleteOut:
    """Usunięcie grupy, którą ktoś posiada (superadmin): odebranie uprawnień
    posiadaczom (systemowe wnioski o odebranie), odmowa pozycji we wnioskach
    w toku, miękkie usunięcie pozycji, audyt + zdarzenie bezpieczeństwa."""
    from datetime import datetime as _dt
    from models import RequestItem, SecuritySeverity
    from services.audit import record_event, request_meta
    from services.security_events import emit as emit_security_event

    now = _dt.utcnow()
    system = session.get(PermissionSystem, system_id)
    sys_name = system.name if system else f"id={system_id}"
    ids = [p.id for p in rows]
    comment = f"Usunięcie grupy uprawnień „{group}” ({sys_name}): {reason}"

    revoke_ids: list[int] = []
    affected: list[dict] = []
    details: list[str] = []
    for user, held in holders:
        revoke_ids.append(_system_revoke_request(session, actor, user, held, comment, now))
        names = [e["permission_name"] or "" for e in held]
        affected.append({"user_id": user.id, "username": user.username,
                         "full_name": user.full_name, "permissions": names})
        details.append(f"odebrano {len(names)} uprawn. — {user.full_name or user.username}")

    in_progress = _group_in_progress(session, ids)
    if in_progress:
        items = session.exec(
            select(RequestItem)
            .where(RequestItem.request_id.in_(in_progress))
            .where(RequestItem.permission_id.in_(ids))
            .where(RequestItem.denied == False)  # noqa: E712
        ).all()
        for it in items:
            it.denied = True
            it.deny_comment = f"Uprawnienie usunięte z rejestru: {reason}"[:1000]
            it.denied_by_user_id = actor.id
            it.denied_at = now
            it.fulfilled = False
            it.fulfilled_by_user_id = None
            it.fulfilled_at = None
            session.add(it)
        details.append("odmówiono pozycji we wnioskach w toku: "
                       + ", ".join(f"#{r}" for r in in_progress))

    for p in rows:
        p.is_active = False
        p.deleted_at = now
        p.deleted_reason = reason[:1000]
        session.add(p)
    session.commit()

    meta = request_meta(request)
    audit_details = {
        "system_id": system_id, "system_name": sys_name, "group_name": group,
        "reason": reason, "permissions": [p.permission_name for p in rows],
        "affected_users": affected, "revoke_request_ids": revoke_ids,
        "updated_request_ids": in_progress,
    }
    record_event(session, action="permission_group.deleted", user_id=actor.id,
                 username=actor.username, target_type="permission_system",
                 target_id=system_id, ip=meta["ip"], user_agent=meta["user_agent"],
                 details=audit_details)
    emit_security_event(
        session, event_type="permission_group.deleted_held", source="systems",
        severity=SecuritySeverity.high,
        summary=(f"Superadmin {actor.username} usunął grupę „{group}” ({sys_name}) — "
                 f"odebrano uprawnienia {len(affected)} os.: {reason}"),
        details=audit_details, user_id=actor.id, ip=meta["ip"],
    )
    return GroupDeleteOut(
        added=0, reactivated=0, updated=0, deactivated=len(rows), skipped=0,
        details=details, affected_user_ids=[a["user_id"] for a in affected],
        revoke_request_ids=revoke_ids, updated_request_ids=in_progress,
    )


@router.post("/{system_id}/permissions/group-delete", response_model=GroupDeleteOut)
def delete_permission_group(
    system_id: int,
    data: GroupDeleteIn,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_it_staff),
):
    """Usuń całą grupę — np. gdy zaimportowano nie ten plik.

    Gdy NIKT nie posiada uprawnień z grupy: pozycje nieużyte są kasowane,
    a użyte we wnioskach wygaszane (historia uprawnień jest nienaruszalna).

    Gdy ktoś je posiada: wyłącznie superadmin, z powodem. Posiadacze tracą
    uprawnienia (systemowy, zrealizowany wniosek o odebranie), pozycje
    we wnioskach w toku są odmawiane, a same uprawnienia usuwane miękko
    (zostają w historii pod dotychczasową nazwą).
    """
    from models import RequestItem, has_role

    group = data.group_name.strip()
    rows = _group_perms(session, system_id, group)
    if not rows:
        raise HTTPException(404, "Grupa nie istnieje w tym oprogramowaniu.")

    holders = _group_holders(session, [p.id for p in rows])
    if holders:
        if not has_role(current_user, "superadmin"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Uprawnienia z tej grupy posiada {len(holders)} os. — grupę może "
                "usunąć tylko superadmin, podając powód.")
        reason = (data.reason or "").strip()
        if not reason:
            raise HTTPException(400,
                "Podaj powód usunięcia grupy — posiadacze stracą te uprawnienia.")
        return _delete_held_group(session, request, current_user, system_id, group,
                                  rows, holders, reason)

    deleted = skipped = 0
    details: list[str] = []
    for p in rows:
        used = session.exec(
            select(RequestItem).where(RequestItem.permission_id == p.id)
        ).first()
        if used:
            p.is_active = False
            session.add(p)
            skipped += 1
            details.append(f'zachowano „{p.permission_name}" — użyte we wniosku')
            continue
        session.delete(p)
        deleted += 1
    session.commit()
    return GroupDeleteOut(added=0, reactivated=0, updated=0,
                          deactivated=deleted, skipped=skipped, details=details)


class GroupStateIn(BaseModel):
    group_name: str
    is_active: bool


@router.post("/{system_id}/permissions/group-state", response_model=ImportCommitOut)
def set_group_state(
    system_id: int,
    data: GroupStateIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Wygaś albo przywróć całą grupę — np. gdy moduł programu został wyłączony."""
    rows = _group_perms(session, system_id, data.group_name.strip())
    if not rows:
        raise HTTPException(404, "Grupa nie istnieje w tym oprogramowaniu.")
    changed = 0
    for p in rows:
        if bool(getattr(p, "is_active", True)) == data.is_active:
            continue
        p.is_active = data.is_active
        session.add(p)
        changed += 1
    session.commit()
    return ImportCommitOut(
        added=0, reactivated=changed if data.is_active else 0, updated=0,
        deactivated=changed if not data.is_active else 0, skipped=0, details=[])


class SubgroupAssignIn(BaseModel):
    permission_ids: list[int]
    # Pusty/None = wyjmij zaznaczone z podgrupy (zostają bezpośrednio w grupie).
    subgroup_name: Optional[str] = None


@router.post("/{system_id}/permissions/subgroup-assign", response_model=ImportCommitOut)
def assign_subgroup(
    system_id: int,
    data: SubgroupAssignIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Masowo przypisz zaznaczone uprawnienia do podgrupy (albo wyjmij z niej).
    Pozycja administratora jest pomijana — nie wchodzi do podgrup."""
    sg = (data.subgroup_name or "").strip() or None
    ids = [int(i) for i in (data.permission_ids or [])]
    if not ids:
        return ImportCommitOut(added=0, reactivated=0, updated=0,
                               deactivated=0, skipped=0, details=[])
    rows = session.exec(
        select(SystemPermission)
        .where(SystemPermission.system_id == system_id)
        .where(SystemPermission.id.in_(ids))
        .where(_LIVE_PERM)
    ).all()
    changed = 0
    for p in rows:
        if p.permission_name == ADMIN_PERM_NAME:
            continue
        if getattr(p, "subgroup_name", None) == sg:
            continue
        p.subgroup_name = sg
        session.add(p)
        changed += 1
    session.commit()
    return ImportCommitOut(added=0, reactivated=0, updated=changed,
                           deactivated=0, skipped=0, details=[])


class GroupOrderIn(BaseModel):
    # Pełna lista nazw grup w żądanej kolejności (od góry).
    groups: list[str]


@router.post("/{system_id}/permissions/group-order")
def set_group_order(
    system_id: int,
    data: GroupOrderIn,
    session: Session = Depends(get_session),
    _: User = Depends(require_it_staff),
):
    """Ustaw kolejność GRUP w programie. Przyjmujemy pełną listę nazw grup po
    kolei; każdej pozycji danej grupy nadajemy jej indeks jako `group_order`.
    Pozycje bez grupy zostają nietknięte (i tak renderują się jako pierwsze)."""
    order = {}
    for i, g in enumerate(data.groups):
        name = (g or "").strip()
        if name and name not in order:
            order[name] = i
    rows = session.exec(
        select(SystemPermission).where(SystemPermission.system_id == system_id)
        .where(_LIVE_PERM)
    ).all()
    changed = 0
    for p in rows:
        g = (getattr(p, "group_name", None) or "").strip()
        if g in order and getattr(p, "group_order", None) != order[g]:
            p.group_order = order[g]
            session.add(p)
            changed += 1
    session.commit()
    return {"ok": True, "updated": changed}
