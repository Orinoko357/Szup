"""
Import list uprawnień z plików wyeksportowanych z systemów dziedzinowych.

Programy w urzędzie mają uprawnienia liczone w setkach pozycji (np. rejestry
opłat w systemie finansowym). Nikt tego nie wklepie ręcznie, a podpinanie się
wprost pod cudzą bazę danych oznaczałoby trzymanie poświadczeń do obcych
systemów i uzależnienie się od ich schematu. Dlatego bierzemy to, co każdy taki
program potrafi wypluć: wydruk/eksport do pliku.

Pliki z systemów dziedzinowych NIE są czystymi CSV — to raporty:

    RejOpl 10.2601.1   2026-07-22, 06:43     <- nagłówek techniczny raportu
    Rejestry dokumentów rejestrów opłat      <- tytuł (dobry kandydat na grupę)
    Lp. | Symbol | Nazwa rejestru            <- właściwy wiersz nagłówkowy
    1.  | ADA    | N- Wydz. AIiDM ABONAMENTY...
    ...
    *** Koniec zestawienia ***               <- stopka

Stąd ten moduł: sam znajduje wiersz nagłówkowy, odrzuca obudowę raportu,
rozpoznaje role kolumn i składa nazwę uprawnienia. Jest czystą logiką (bez
FastAPI i bez bazy), żeby dało się go testować na samych danych.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Optional

# Role kolumn. „code" + „name" składają się na nazwę uprawnienia, „description"
# ląduje w opisie, „ignore" jest pomijana (typowo kolumna Lp.).
ROLE_IGNORE = "ignore"
ROLE_CODE = "code"
ROLE_NAME = "name"
ROLE_DESC = "description"
ROLES = (ROLE_IGNORE, ROLE_CODE, ROLE_NAME, ROLE_DESC)

# Separator symbolu od nazwy — format zamówiony wprost: „ADA - Nazwa rejestru".
CODE_JOIN = " - "

MAX_ROWS = 5000

# Słowa, po których poznajemy wiersz nagłówkowy i rolę kolumny.
_HEADER_WORDS = {
    "lp": ROLE_IGNORE, "l.p": ROLE_IGNORE, "nr": ROLE_IGNORE, "poz": ROLE_IGNORE,
    "symbol": ROLE_CODE, "kod": ROLE_CODE, "skrot": ROLE_CODE, "skrót": ROLE_CODE,
    "id": ROLE_CODE, "identyfikator": ROLE_CODE,
    "nazwa": ROLE_NAME, "rejestr": ROLE_NAME, "uprawnienie": ROLE_NAME,
    "modul": ROLE_NAME, "moduł": ROLE_NAME, "grupa": ROLE_NAME, "rola": ROLE_NAME,
    "opis": ROLE_DESC, "uwagi": ROLE_DESC, "komentarz": ROLE_DESC,
}

_ORDINAL_RE = re.compile(r"^\d{1,5}[.)]?$")
_WS_RE = re.compile(r"\s+")

# Wzorce dopasowywane do tekstu POZBAWIONEGO spacji — raporty potrafią
# rozstrzelić litery („* * * K o n i e c   z e s t a w i e n i a * * *").
_JUNK_RE = re.compile(
    r"^\**(koniec|razem|suma|liczbapozycji)"
    r"|^strona\d+(z|/)\d+$"
    r"|^str\.?\d+$",
    re.I,
)


def _despace(text: str) -> str:
    return _WS_RE.sub("", text)


# ---------------------------------------------------------------------------
# Struktury wyniku
# ---------------------------------------------------------------------------

@dataclass
class Column:
    index: int
    header: str
    role: str
    samples: list[str] = field(default_factory=list)


@dataclass
class ImportItem:
    permission_name: str
    description: Optional[str] = None
    external_code: Optional[str] = None


@dataclass
class Layout:
    columns: list[Column]
    data_rows: list[list[str]]
    group_suggested: Optional[str]
    warnings: list[str] = field(default_factory=list)


class ImportError_(Exception):
    """Błąd czytelny dla użytkownika (router zamienia go na HTTP 400)."""


# ---------------------------------------------------------------------------
# Wczytanie surowej tabeli
# ---------------------------------------------------------------------------

def _clean(v) -> str:
    """Komórka → tekst bez zbędnych białych znaków (także wewnętrznych)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return _WS_RE.sub(" ", str(v)).strip()


def _read_xlsx(raw: bytes) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError_(
            'Obsługa plików .xlsx jest niedostępna na serwerze. Zapisz plik jako '
            'CSV albo zaznacz dane w Excelu (Ctrl+A, Ctrl+C) i wklej je w oknie importu.'
        )
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [[_clean(c) for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _read_xls(raw: bytes) -> list[list[str]]:
    try:
        import xlrd
    except ImportError:
        raise ImportError_(
            'Obsługa starych plików .xls jest niedostępna na serwerze. Zapisz plik '
            'jako CSV albo zaznacz dane w Excelu (Ctrl+A, Ctrl+C) i wklej je w oknie importu.'
        )
    book = xlrd.open_workbook(file_contents=raw)
    sheet = book.sheet_by_index(0)
    return [[_clean(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def _pdf_lines(raw: bytes) -> list[list[tuple[float, float, str]]]:
    """Znaki z PDF-a pogrupowane w wiersze: [(x0, x1, znak), ...] na wiersz.

    Bierzemy pozycje POSZCZEGÓLNYCH ZNAKÓW, bo wydruk z systemu dziedzinowego
    nie ma w sobie pojęcia tabeli — kolumny są tylko efektem współrzędnych.
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTChar, LTTextContainer
    except ImportError:
        raise ImportError_(
            'Obsługa plików PDF jest niedostępna na serwerze. Wyeksportuj listę '
            'do CSV/Excela albo zaznacz ją i wklej w oknie importu.'
        )

    lines: list[list[tuple[float, float, str]]] = []
    for page in extract_pages(io.BytesIO(raw),
                              laparams=LAParams(char_margin=1.2, word_margin=0.15)):
        chars: list[tuple[float, float, float, str]] = []
        for element in page:
            if not isinstance(element, LTTextContainer):
                continue
            for text_line in element:
                for ch in text_line:
                    if not isinstance(ch, LTChar):
                        continue
                    t = ch.get_text()
                    if not t or t == "\n":
                        continue
                    chars.append((ch.y0, ch.x0, ch.x1, t))

        # Wiersze wyznaczamy zachłannie, a nie stałym kubełkiem po y: komórki
        # jednego wiersza bywają przesunięte o 1–2 pkt (inny rozmiar czcionki
        # w kolumnie Lp.), a stały podział rozrywa je w losowym miejscu.
        for y0, x0, x1, t in sorted(chars, key=lambda c: (-c[0], c[1])):
            if lines and abs(lines[-1][0][3] - y0) <= 2.5:
                lines[-1].append((x0, x1, t, y0))
            else:
                lines.append([(x0, x1, t, y0)])
    lines = [sorted(ln, key=lambda c: c[0]) for ln in lines]
    lines = [[(x0, x1, t) for x0, x1, t, _ in ln] for ln in lines]
    if not lines:
        raise ImportError_(
            "PDF nie zawiera tekstu (to prawdopodobnie skan). Potrzebny jest "
            "wydruk do pliku, a nie zeskanowana kartka."
        )
    return lines


def _split_runs(chars: list[tuple[float, float, str]]) -> list[tuple[float, str]]:
    """Znaki wiersza → ciągi rysowane jednym poleceniem wypisania tekstu.

    Nie da się tu użyć progu odległości: w wydruku FK odstęp między kolumnami
    to 3,6 pkt, a spacja wewnątrz nazwy („Projekt NCK") 2,5 pkt — próg
    pośrodku byłby loterią. Za to znaki JEDNEJ komórki generator układa
    dokładnie styk w styk (koniec poprzedniego = początek następnego), a nowa
    komórka zaczyna się od skoku współrzędnej. Ta nieciągłość jest sygnałem
    pewnym; łapie też nagłówki przycięte tak, że NACHODZĄ na sąsiednie.
    """
    out: list[tuple[float, str]] = []
    start = None
    buf: list[str] = []
    prev_x1 = None
    for x0, x1, t in chars:
        if prev_x1 is not None and abs(x0 - prev_x1) > 0.6:
            out.append((start, "".join(buf)))
            buf = []
            start = None
        if start is None:
            start = x0
        buf.append(t)
        prev_x1 = x1
    if buf:
        out.append((start, "".join(buf)))
    return [(x, _WS_RE.sub(" ", s).strip()) for x, s in out if s.strip()]


def _column_bounds(runs: list[list[tuple[float, str]]]) -> list[float]:
    """Lewe krawędzie kolumn — pozycje POWTARZAJĄCE SIĘ w wielu wierszach.

    Nie bierzemy ich z wiersza nagłówkowego, bo nagłówki bywają przycięte
    i zachodzą na siebie (w wydruku FK „ODDZIAL" nachodzi na „NAZWA").
    Za to początki komórek w wierszach danych są równe co do punktu, więc
    to one wyznaczają siatkę; jednorazowe pozycje (tytuł, data, stopka)
    odpadają przez próg powtarzalności.
    """
    starts: list[float] = []
    for row in runs:
        starts.extend(x for x, _ in row)
    starts.sort()

    clusters: list[list[float]] = []
    for x in starts:
        if clusters and x - clusters[-1][-1] <= 5.0:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    min_hits = max(2, int(len(runs) * 0.25))
    bounds = [min(c) for c in clusters if len(c) >= min_hits]
    return bounds or [min(starts)] if starts else []


def _read_pdf(raw: bytes) -> list[list[str]]:
    """PDF z wydrukiem tabeli → wiersze komórek.

    Do kolumn przypisujemy POJEDYNCZE ZNAKI, nie gotowe ciągi. Dzięki temu
    nachodzące na siebie napisy nagłówka rozchodzą się do właściwych kolumn,
    a wiersz z pustą komórką w środku nie przesuwa reszty.
    """
    lines = _pdf_lines(raw)
    runs = [_split_runs(ln) for ln in lines]
    bounds = _column_bounds(runs)
    if not bounds:
        return [[t for _, t in row] for row in runs]

    out: list[list[str]] = []
    for line in lines:
        cells = [""] * len(bounds)
        for x0, _x1, ch in line:
            col = 0
            for i, b in enumerate(bounds):
                if x0 >= b - 1.0:
                    col = i
            cells[col] += ch
        out.append([_WS_RE.sub(" ", c).strip() for c in cells])
    return out


def _decode(raw: bytes) -> str:
    """Pierwsze kodowanie, w którym plik czyta się bez błędu.

    Kolejność nieprzypadkowa: eksporty z polskiego Excela to najczęściej
    cp1250, ale nowsze narzędzia dają UTF-8 (często z BOM).
    """
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _pick_delimiter(text: str) -> str:
    """Separator wybrany po SPÓJNOŚCI liczby kolumn, nie po samej częstości.

    `csv.Sniffer` wykłada się na raportach z systemów dziedzinowych (puste
    wiersze, rozjeżdżająca się liczba kolumn w nagłówku i stopce). Tutaj
    liczymy, ile wierszy rozpada się na TĘ SAMĄ liczbę pól — prawdziwy
    separator daje stabilny podział, przypadkowy przecinek w opisie nie.
    """
    lines = [ln for ln in text.splitlines()[:40] if ln.strip()]
    if not lines:
        return ";"
    best, best_score = ";", (0, 0)
    for delim in (";", "\t", ",", "|"):
        counts = [len(ln.split(delim)) for ln in lines]
        common = max(set(counts), key=counts.count)
        if common < 2:
            continue
        score = (counts.count(common), common)
        if score > best_score:
            best, best_score = delim, score
    return best


def _read_text(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=_pick_delimiter(text))
    return [[_clean(c) for c in row] for row in reader]


def read_table(raw: Optional[bytes] = None, filename: Optional[str] = None,
               pasted: Optional[str] = None) -> list[list[str]]:
    """Plik lub wklejony tekst → tabela komórek tekstowych."""
    if pasted and pasted.strip():
        rows = _read_text(pasted)
    elif raw:
        name = (filename or "").lower()
        if name.endswith(".xlsx") or name.endswith(".xlsm"):
            rows = _read_xlsx(raw)
        elif name.endswith(".xls"):
            rows = _read_xls(raw)
        elif name.endswith(".pdf"):
            rows = _read_pdf(raw)
        # Rozszerzenie bywa mylące (u nas eksport .xls okazał się BIFF-em),
        # więc rozstrzyga sygnatura pliku.
        elif raw[:4] == b"\xd0\xcf\x11\xe0":      # OLE2 — stary .xls
            rows = _read_xls(raw)
        elif raw[:2] == b"PK":                    # ZIP — .xlsx
            rows = _read_xlsx(raw)
        elif raw[:5] == b"%PDF-":
            rows = _read_pdf(raw)
        else:
            rows = _read_text(_decode(raw))
    else:
        raise ImportError_("Nie przekazano pliku ani wklejonych danych.")

    if not any(any(c for c in r) for r in rows):
        raise ImportError_("Plik nie zawiera żadnych danych.")
    if len(rows) > MAX_ROWS:
        raise ImportError_(
            f"Plik ma {len(rows)} wierszy — limit to {MAX_ROWS}. "
            f"Podziel go na mniejsze części."
        )
    return rows


# ---------------------------------------------------------------------------
# Rozpoznanie układu
# ---------------------------------------------------------------------------

def _header_score(row: list[str]) -> int:
    filled = [c for c in row if c]
    if len(filled) < 2:
        return 0
    return sum(1 for c in filled
               if any(w in c.lower() for w in _HEADER_WORDS))


def _find_header(rows: list[list[str]]) -> int:
    """Indeks wiersza nagłówkowego; -1 gdy plik go nie ma.

    Szukamy tylko w górnej części pliku — niżej trafiłyby się już dane
    (np. rejestr o nazwie „Opłata skarbowa" zawiera słowo z listy).
    """
    best, best_score = -1, 0
    for i, row in enumerate(rows[:15]):
        score = _header_score(row)
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 2 else -1


def _guess_group(rows: list[list[str]], header_idx: int,
                 filename: Optional[str]) -> Optional[str]:
    """Propozycja nazwy grupy: tytuł raportu nad nagłówkiem, inaczej nazwa pliku."""
    candidates = []
    for row in rows[:header_idx if header_idx > 0 else 0]:
        cells = [c for c in row if c]
        if len(cells) != 1:
            continue
        text = cells[0]
        # Odsiewamy techniczne linijki: wersje, daty, same liczby.
        if re.search(r"\d{4}-\d{2}-\d{2}|\d+\.\d+\.\d+", text):
            continue
        if len(text) < 5:
            continue
        candidates.append(text)
    if candidates:
        return max(candidates, key=len)
    if filename:
        stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename.rsplit("/", 1)[-1])
        return stem.replace("_", " ").replace("-", " ").strip() or None
    return None


def _guess_roles(header: list[str], data: list[list[str]], ncols: int) -> list[str]:
    """Rola każdej kolumny — najpierw po nagłówku, potem po zawartości."""
    roles: list[Optional[str]] = [None] * ncols

    for i in range(ncols):
        h = (header[i] if i < len(header) else "").lower().strip(" .:")
        for word, role in _HEADER_WORDS.items():
            if h == word or h.startswith(word):
                roles[i] = role
                break

    def col(i):
        return [r[i] for r in data if i < len(r) and r[i]]

    # Kolumna porządkowa (Lp.) — same liczby, niezależnie od nagłówka.
    # UWAGA: nie wystarczy „same cyfry". Kody oddziałów bywają numeryczne
    # („001", „002") i wpadłyby w tę regułę, tracąc symbol uprawnienia.
    # Numeracja porządkowa nie ma zer wiodących i rośnie o jeden.
    for i in range(ncols):
        vals = col(i)
        if not vals or not all(_ORDINAL_RE.match(v) for v in vals):
            continue
        nums = [int(v.rstrip(".)")) for v in vals]
        padded = any(len(v.rstrip(".)")) > 1 and v.startswith("0") for v in vals)
        if not padded and all(b - a == 1 for a, b in zip(nums, nums[1:])):
            roles[i] = ROLE_IGNORE

    # Symbol: krótkie, jednowyrazowe, w większości unikalne wartości.
    if ROLE_CODE not in roles:
        for i in range(ncols):
            if roles[i] in (ROLE_IGNORE, ROLE_NAME, ROLE_DESC):
                continue
            vals = col(i)
            if len(vals) < 2:
                continue
            avg = sum(len(v) for v in vals) / len(vals)
            if avg <= 12 and not any(" " in v for v in vals) \
               and len(set(vals)) >= len(vals) * 0.9:
                roles[i] = ROLE_CODE
                break

    # Nazwa: najdłuższy średni tekst spośród nieprzypisanych.
    if ROLE_NAME not in roles:
        best, best_avg = -1, 0.0
        for i in range(ncols):
            if roles[i] is not None:
                continue
            vals = col(i)
            if not vals:
                continue
            avg = sum(len(v) for v in vals) / len(vals)
            if avg > best_avg:
                best, best_avg = i, avg
        if best >= 0:
            roles[best] = ROLE_NAME

    # Pierwsza pozostała kolumna z treścią to opis, reszta odpada.
    desc_taken = ROLE_DESC in roles
    for i in range(ncols):
        if roles[i] is not None:
            continue
        if not desc_taken and col(i):
            roles[i] = ROLE_DESC
            desc_taken = True
        else:
            roles[i] = ROLE_IGNORE

    return [r or ROLE_IGNORE for r in roles]


def detect_layout(rows: list[list[str]], filename: Optional[str] = None,
                  roles_override: Optional[list[str]] = None) -> Layout:
    """Surowa tabela → kolumny z rolami, wiersze danych i propozycja grupy."""
    warnings: list[str] = []

    header_idx = _find_header(rows)
    if header_idx < 0:
        warnings.append(
            "Nie rozpoznano wiersza nagłówkowego — przyjęto, że plik zawiera "
            "same dane. Sprawdź przypisanie kolumn."
        )
    header = rows[header_idx] if header_idx >= 0 else []
    body = rows[header_idx + 1:] if header_idx >= 0 else list(rows)

    # Obudowa raportu potrafi wracać W ŚRODKU danych: przy każdym łamaniu
    # strony powtarza się tytuł, wersja programu i wiersz nagłówkowy, a między
    # nimi lądują stopki „Strona 1 z 2". Odsiewamy je trzema regułami, bo
    # obcięcie samego końca pliku by nie wystarczyło.
    header_cells = [c for c in header if c]
    preamble = {_despace(c) for row in rows[:max(header_idx, 0)] for c in row if c}
    kept, dropped = [], 0
    for row in body:
        cells = [c for c in row if c]
        if not cells:
            continue
        if header_cells and cells == header_cells:          # powtórzony nagłówek
            dropped += 1
            continue
        despaced = [_despace(c) for c in cells]
        if preamble and all(c in preamble for c in despaced):  # tytuł/wersja raportu
            dropped += 1
            continue
        if len(cells) == 1 and _JUNK_RE.match(despaced[0]):    # stopka / numer strony
            dropped += 1
            continue
        kept.append(row)
    body = kept
    if dropped:
        warnings.append(f"Pominięto {dropped} wierszy nagłówka/stopki raportu.")

    ncols = max([len(r) for r in body] + [len(header)] + [0])
    if ncols == 0:
        raise ImportError_("Plik nie zawiera kolumn z danymi.")

    body = [r + [""] * (ncols - len(r)) for r in body if any(c for c in r)]
    if not body:
        raise ImportError_("Po odrzuceniu nagłówka i stopki nie zostały żadne wiersze.")

    # Kolumny puste w całości — nie ma po co pokazywać ich użytkownikowi.
    nonempty = [i for i in range(ncols) if any(r[i] for r in body)]
    if not nonempty:
        raise ImportError_("Wszystkie kolumny są puste.")

    if roles_override:
        roles_full = list(roles_override) + [ROLE_IGNORE] * (ncols - len(roles_override))
        roles = [roles_full[i] for i in range(ncols)]
    else:
        roles = _guess_roles(header, body, ncols)

    columns = [
        Column(
            index=i,
            header=(header[i] if i < len(header) else "") or f"Kolumna {i + 1}",
            role=roles[i] if i in nonempty else ROLE_IGNORE,
            samples=[r[i] for r in body[:3] if r[i]],
        )
        for i in nonempty
    ]
    if not any(c.role == ROLE_NAME for c in columns):
        warnings.append(
            "Nie wskazano kolumny z nazwą uprawnienia — wybierz ją w mapowaniu kolumn."
        )

    return Layout(
        columns=columns,
        data_rows=body,
        group_suggested=_guess_group(rows, header_idx, filename),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Złożenie pozycji
# ---------------------------------------------------------------------------

def compose(layout: Layout) -> tuple[list[ImportItem], list[str]]:
    """Wiersze danych → pozycje uprawnień. Zwraca (pozycje, ostrzeżenia)."""
    warnings = list(layout.warnings)
    idx = {role: [c.index for c in layout.columns if c.role == role]
           for role in ROLES}

    name_cols = idx[ROLE_NAME]
    code_cols = idx[ROLE_CODE]
    desc_cols = idx[ROLE_DESC]
    if not name_cols and not code_cols:
        raise ImportError_(
            "Wskaż przynajmniej kolumnę z nazwą uprawnienia albo z symbolem."
        )

    items: list[ImportItem] = []
    seen: dict[str, int] = {}
    dupes = 0
    empty = 0

    for row in layout.data_rows:
        code = " ".join(row[i] for i in code_cols if row[i]).strip()
        name = " ".join(row[i] for i in name_cols if row[i]).strip()
        desc = " ".join(row[i] for i in desc_cols if row[i]).strip() or None

        # Symbol + nazwa → „ADA - Nazwa rejestru". Sam symbol też jest
        # poprawnym uprawnieniem (niektóre systemy nie mają opisów).
        if code and name:
            full = f"{code}{CODE_JOIN}{name}"
        else:
            full = name or code
        if not full:
            empty += 1
            continue

        key = full.lower()
        if key in seen:
            dupes += 1
            continue
        seen[key] = 1
        items.append(ImportItem(permission_name=full, description=desc,
                                external_code=code or None))

    if dupes:
        warnings.append(f"Pominięto {dupes} zduplikowanych pozycji.")
    if empty:
        warnings.append(f"Pominięto {empty} wierszy bez nazwy uprawnienia.")
    if not items:
        raise ImportError_("Nie udało się odczytać żadnej pozycji uprawnień.")
    return items, warnings


def parse(raw: Optional[bytes] = None, filename: Optional[str] = None,
          pasted: Optional[str] = None,
          roles_override: Optional[list[str]] = None) -> tuple[Layout, list[ImportItem], list[str]]:
    """Skrót na całą ścieżkę: bajty/tekst → (układ, pozycje, ostrzeżenia)."""
    rows = read_table(raw=raw, filename=filename, pasted=pasted)
    layout = detect_layout(rows, filename=filename, roles_override=roles_override)
    items, warnings = compose(layout)
    return layout, items, warnings
