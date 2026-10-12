"""Migracja historycznych „pól wnioskodawcy" na uprawnienia z kontrolką.

Wcześniej program mógł mieć ALBO listę uprawnień, ALBO pola definiowane przy
samym programie. Ten podział zniknął — pole stało się uprawnieniem. Migracja
rusza produkcyjne dane, więc pilnujemy dwóch rzeczy: że pola faktycznie
przechodzą na uprawnienia i że NIC z historii wniosków nie znika.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from database import _migrate_custom_fields_to_permissions, engine
from models import PermissionSystem, SystemPermission

LEGACY_FIELDS = [
    {"label": "Zakres uprawnień", "type": "textarea", "required": True,
     "description": "Moduły lub rejestry", "options": [], "value": None},
    {"label": "Moduły", "type": "multiselect", "required": False,
     "description": None, "options": ["FK", "KP"], "value": None},
]


def _make_legacy_system(api, sup, name="Stary program"):
    """Program w STARYM modelu: pola przy programie + syntetyczny „Dostęp"."""
    sid = api.post("/systems/", token=sup,
                   json={"name": name, "all_units": True}).json()["id"]
    with Session(engine) as s:
        row = s.get(PermissionSystem, sid)
        row.custom_fields = json.dumps(LEGACY_FIELDS, ensure_ascii=False)
        s.add(row)
        s.add(SystemPermission(system_id=sid, permission_name="Dostęp",
                               description="Dostęp do systemu"))
        s.commit()
    return sid


def _perms(sid):
    with Session(engine) as s:
        return {p.permission_name: p for p in s.exec(
            select(SystemPermission).where(SystemPermission.system_id == sid)).all()}


def test_fields_become_permissions(api):
    sup = api.setup_superadmin()
    sid = _make_legacy_system(api, sup)

    _migrate_custom_fields_to_permissions()

    perms = _perms(sid)
    assert "Zakres uprawnień" in perms and "Moduły" in perms

    scope = perms["Zakres uprawnień"]
    assert scope.input_type == "textarea"
    assert scope.input_required is True
    assert scope.description == "Moduły lub rejestry"

    mods = perms["Moduły"]
    assert mods.input_type == "multiselect"
    assert json.loads(mods.options) == ["FK", "KP"]
    assert mods.input_required is False

    # Pola przy programie przestają istnieć — jeden model, nie dwa naraz.
    with Session(engine) as s:
        assert s.get(PermissionSystem, sid).custom_fields is None


def test_unused_synthetic_access_is_removed(api):
    """Syntetyczny „Dostęp" obsługiwał programy z polami — teraz zbędny."""
    sup = api.setup_superadmin()
    sid = _make_legacy_system(api, sup)

    _migrate_custom_fields_to_permissions()

    assert "Dostęp" not in _perms(sid)


def test_used_synthetic_access_is_kept_but_deactivated(api):
    """Jeśli „Dostęp" jest w historii wniosków — zostaje, tylko wygaszony.

    Skasowanie zerwałoby ewidencję osób, którym to uprawnienie nadano.
    """
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")
    sid = _make_legacy_system(api, sup, "Uzywany")
    pid = _perms(sid)["Dostęp"].id

    rid = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "P", "unit_id": unit, "department_id": dep,
        "items": [{"system_id": sid, "permission_id": pid, "kind": "grant"}],
        "request_type_id": api.request_type(sup, "NEW_EMP"),
    })
    assert rid.status_code in (200, 201), rid.text

    _migrate_custom_fields_to_permissions()

    perms = _perms(sid)
    assert "Dostęp" in perms                      # nie skasowane…
    assert perms["Dostęp"].is_active is False     # …ale poza wyborem
    assert "Zakres uprawnień" in perms


def test_migration_is_idempotent(api):
    """Wielokrotny start aplikacji nie może dublować uprawnień."""
    sup = api.setup_superadmin()
    sid = _make_legacy_system(api, sup)

    _migrate_custom_fields_to_permissions()
    before = sorted(_perms(sid))
    _migrate_custom_fields_to_permissions()

    assert sorted(_perms(sid)) == before
