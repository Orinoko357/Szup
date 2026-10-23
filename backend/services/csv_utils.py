"""
Pomocnicze funkcje eksportu CSV.

Neutralizacja formuł (CSV/formula injection): arkusz kalkulacyjny (Excel,
LibreOffice) interpretuje komórkę zaczynającą się od `=`, `+`, `-`, `@`, TAB
lub CR jako formułę — także gdy przed tym znakiem stoją spacje. Taką wartość
poprzedzamy apostrofem, dzięki czemu arkusz pokaże ją jako zwykły tekst.
"""
from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> Any:
    """Zwraca wartość bezpieczną do zapisu w komórce CSV.

    Wartości niebędące napisami (liczby, None, daty) zwracane są bez zmian.
    Napis zaczynający się — bezpośrednio lub po początkowych białych znakach —
    od znaku formuły dostaje prefiks `'`.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    stripped = value.lstrip(" \n\v\f")
    if stripped and stripped != value and stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_safe_row(row) -> list:
    """`csv_safe` zastosowane do każdej komórki wiersza."""
    return [csv_safe(v) for v in row]
