#!/usr/bin/env python3
"""Naprawa szablonu obiegu do aktualnej, poprawnej wersji.

Dlaczego to potrzebne: domyślny szablon jest tworzony przez seed TYLKO gdy baza
jest pusta (`if existing: return`), a `reset_data.py` NIE usuwa szablonów. Więc
na istniejącej bazie zostaje ten szablon, który zapisał się przy pierwszym
uruchomieniu — także starszy, z osobnym krokiem „akceptacja kierownika" przed
akceptacją wyższego rzędu (podwójna akceptacja kier. 1. stopnia).

Poprawny obieg:
    Zgłoszenie (HR) → Wybór uprawnień (kierownik) →
    Akceptacja wyższego rzędu [pomijana gdy komórka bez flagi] → Realizacja (IT)

Skrypt nadpisuje graf szablonów, które NIE są zgodne z tą sekwencją. Nie usuwa
danych (użytkownicy, komórki, wnioski zostają). UWAGA: wnioski już będące
w obiegu mają zamrożony snapshot i dokończą się starą ścieżką — dotyczy to
wyłącznie NOWO składanych wniosków.

Użycie (na serwerze):
    cd /opt/szup/backend
    source /opt/szup/venv/bin/activate
    python -m tools.fix_workflow_template            # podgląd (dry-run)
    python -m tools.fix_workflow_template --yes      # zastosuj

Zależności: tylko kod aplikacji (SQLModel). Ścieżka bazy z $SZUP_DATA_DIR
(domyślnie /opt/szup/data).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SZUP_DATA_DIR", "/opt/szup/data")

CANONICAL_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "start",
         "label": "Zgłoszenie pracownika (HR)", "x": 50, "y": 100, "props": {}},
        {"id": "n2", "type": "select_permissions",
         "label": "Wybór uprawnień i zatwierdzenie (kierownik)", "x": 250, "y": 100,
         "props": {"actor": "department_manager"}},
        {"id": "n3", "type": "higher_manager_approve",
         "label": "Akceptacja kierownika wyższego rzędu", "x": 450, "y": 100,
         "props": {"skip_if_not_required": True}},
        {"id": "n4", "type": "it_execute",
         "label": "Realizacja przez IT", "x": 650, "y": 100, "props": {}},
        {"id": "n5", "type": "end",
         "label": "Zakończenie procesu", "x": 850, "y": 100, "props": {}},
    ],
    "edges": [
        {"from": "n1", "to": "n2"},
        {"from": "n2", "to": "n3"},
        {"from": "n3", "to": "n4"},
        {"from": "n4", "to": "n5"},
    ],
}
CANONICAL_TYPES = ["start", "select_permissions", "higher_manager_approve", "it_execute", "end"]


def _node_types(graph_json: str) -> list[str]:
    try:
        g = json.loads(graph_json)
        return [n.get("type") for n in g.get("nodes", [])]
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Napraw szablon(y) obiegu do poprawnej sekwencji.")
    ap.add_argument("--yes", action="store_true", help="zastosuj zmiany (bez tego tylko podgląd)")
    args = ap.parse_args()

    from sqlmodel import Session, select
    from database import engine
    from models import WorkflowTemplate

    with Session(engine) as s:
        templates = s.exec(select(WorkflowTemplate)).all()
        if not templates:
            print("Brak szablonów w bazie — nic do naprawy (seed utworzy poprawny przy starcie).")
            return 0

        to_fix = []
        for t in templates:
            types = _node_types(t.graph_json)
            ok = types == CANONICAL_TYPES
            flag = "OK" if ok else "DO NAPRAWY"
            print(f"[{flag}] szablon #{t.id} „{t.name}” (v{t.version}, active={t.is_active})")
            print(f"          węzły: {' → '.join(types) or '(pusty/niepoprawny)'}")
            if not ok:
                to_fix.append(t)

        if not to_fix:
            print("\nWszystkie szablony są już zgodne z poprawnym obiegiem. Nic do zrobienia.")
            return 0

        print(f"\nDocelowa sekwencja: {' → '.join(CANONICAL_TYPES)}")
        if not args.yes:
            print(f"\n[DRY-RUN] {len(to_fix)} szablon(ów) zostałoby nadpisanych. "
                  f"Uruchom ponownie z --yes aby zastosować.")
            return 0

        payload = json.dumps(CANONICAL_GRAPH, ensure_ascii=False)
        for t in to_fix:
            t.version = (t.version or 1) + 1
            t.graph_json = payload
            s.add(t)
        s.commit()
        print(f"\nNaprawiono {len(to_fix)} szablon(ów). Nowe wnioski pójdą poprawnym obiegiem.")
        print("Wnioski już w toku dokończą się starą ścieżką (zamrożony snapshot).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
