"""Import list uprawnień z plików — parser + ścieżka preview/commit.

Dane testowe odwzorowują prawdziwy eksport z systemu dziedzinowego (RejOpl):
raport z nagłówkiem technicznym, tytułem, kolumną „Lp.", a przy łamaniu strony
POWTÓRZONYM nagłówkiem i stopką „Strona 1 z 2". To nie jest teoretyczny
przypadek — na tym wykłada się naiwne czytanie CSV.
"""
from __future__ import annotations

import io

import pytest

from services import perm_import

# Układ 1:1 z prawdziwym plikiem, tylko krótszy.
RAPORT_ROWS = [
    ["", "", "", ""],
    ["RejOpl 10.2601.1", "", "", "2026-07-22, 06:43"],
    ["", "", "", ""],
    ["", "", "Rejestry dokumentów rejestrów opłat", ""],
    ["", "Lp.", "Symbol", "Nazwa rejestru"],
    ["", "1.", "ADA", "N- Wydz. AIiDM ABONAMENTY - nota rozdz.60016"],
    ["", "2.", "ADK", "Wydz. AIiDM KARY rozdz. 70005"],
    ["", "", "", "Strona 1 z 2"],
    ["RejOpl 10.2601.1", "", "", "2026-07-22, 06:43"],
    ["", "", "Rejestry dokumentów rejestrów opłat", ""],
    ["", "Lp.", "Symbol", "Nazwa rejestru"],
    ["", "3.", "ALK", "Koncesje alkoholowe 75618"],
    ["", "", "* * * K o n i e c   z e s t a w i e n i a * * *", ""],
]

NAMES = [
    "ADA - N- Wydz. AIiDM ABONAMENTY - nota rozdz.60016",
    "ADK - Wydz. AIiDM KARY rozdz. 70005",
    "ALK - Koncesje alkoholowe 75618",
]


def _as_csv(rows, delim=";") -> str:
    return "\n".join(delim.join(c for c in r) for r in rows)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_csv_cp1250_report_layout():
    """Nagłówek raportu, Lp., powtórki po łamaniu strony i stopka odpadają."""
    raw = _as_csv(RAPORT_ROWS).encode("cp1250")
    layout, items, warnings = perm_import.parse(raw=raw, filename="ro-um.csv")

    assert [i.permission_name for i in items] == NAMES
    assert layout.group_suggested == "Rejestry dokumentów rejestrów opłat"
    roles = {c.header: c.role for c in layout.columns}
    assert roles["Lp."] == perm_import.ROLE_IGNORE
    assert roles["Symbol"] == perm_import.ROLE_CODE
    assert roles["Nazwa rejestru"] == perm_import.ROLE_NAME
    assert items[0].external_code == "ADA"
    assert any("nagłówka/stopki" in w for w in warnings)


def test_pasted_tsv_gives_same_result():
    """Ctrl+C z Excela to TSV — musi dać dokładnie to samo, co plik."""
    _, items, _ = perm_import.parse(pasted=_as_csv(RAPORT_ROWS, "\t"))
    assert [i.permission_name for i in items] == NAMES


def test_comma_delimiter_and_utf8():
    raw = _as_csv(RAPORT_ROWS, ",").encode("utf-8")
    _, items, _ = perm_import.parse(raw=raw, filename="x.csv")
    assert [i.permission_name for i in items] == NAMES


def test_without_code_column_uses_name_only():
    rows = [
        ["Nazwa uprawnienia", "Opis"],
        ["Odczyt kartotek", "podgląd bez edycji"],
        ["Edycja kartotek", ""],
    ]
    _, items, _ = perm_import.parse(pasted=_as_csv(rows))
    assert [i.permission_name for i in items] == ["Odczyt kartotek", "Edycja kartotek"]
    assert items[0].description == "podgląd bez edycji"
    assert items[0].external_code is None


def test_duplicates_and_empty_rows_reported():
    rows = [
        ["Symbol", "Nazwa"],
        ["ADA", "Abonamenty"],
        ["ADA", "Abonamenty"],
        ["", ""],
        ["ADK", "Kary"],
    ]
    _, items, warnings = perm_import.parse(pasted=_as_csv(rows))
    assert [i.permission_name for i in items] == ["ADA - Abonamenty", "ADK - Kary"]
    assert any("zduplikowanych" in w for w in warnings)


def test_roles_override_wins_over_detection():
    """Ręczna korekta mapowania — użytkownik ma ostatnie słowo."""
    rows = [["Symbol", "Nazwa"], ["ADA", "Abonamenty"]]
    _, items, _ = perm_import.parse(
        pasted=_as_csv(rows),
        roles_override=[perm_import.ROLE_IGNORE, perm_import.ROLE_NAME])
    assert [i.permission_name for i in items] == ["Abonamenty"]


def test_xlsx_matches_csv():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in RAPORT_ROWS:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)

    _, items, _ = perm_import.parse(raw=buf.getvalue(), filename="ro-um.xlsx")
    assert [i.permission_name for i in items] == NAMES


def test_numeric_codes_are_not_mistaken_for_row_numbers():
    """„001", „002" to KODY, nie numeracja — zera wiodące je odróżniają."""
    rows = [
        ["Lp.", "ODDZIAL", "NAZWA"],
        ["1.", "001", "MiPBP"],
        ["2.", "002", "Projekt NCK"],
        ["3.", "003", "MKiDN książki"],
    ]
    _, items, _ = perm_import.parse(pasted=_as_csv(rows))
    assert [i.permission_name for i in items] == [
        "001 - MiPBP", "002 - Projekt NCK", "003 - MKiDN książki"]
    assert items[0].external_code == "001"


def test_pdf_report_layout():
    """Wydruk PDF z systemu dziedzinowego — kolumny wynikają ze współrzędnych.

    Odwzorowujemy pułapki prawdziwego wydruku FK: nagłówki kolumn stykają się
    ze sobą ciaśniej niż spacja w nazwie, a odstęp kolumn (3,6 pkt) jest
    mniejszy niż typowy próg podziału.

    Tekst bez polskich znaków — nie z powodu parsera (ten czyta „książki"
    z prawdziwego wydruku poprawnie), tylko dlatego, że wbudowana Helvetica
    reportlaba nie zakoduje diakrytyków w GENEROWANYM tu pliku. Odczyt
    cp1250/UTF-8 pokrywają testy tekstowe wyżej.
    """
    pytest.importorskip("pdfminer.high_level")
    from reportlab.pdfgen import canvas          # reportlab jest już zależnością

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 10)
    c.drawString(42, 790, "System Finansowo-Księgowy 3.2601.3")
    c.drawString(478, 790, "2026-07-22, 09:05")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(157, 755, "Oddzialy BIBLIOTEKA")
    c.setFont("Helvetica", 9)
    for x, t in ((72, "Lp."), (88, "ODDZIAL"), (130, "NAZWA")):
        c.drawString(x, 741, t)
    for n, (code, name) in enumerate(
            [("001", "MiPBP"), ("002", "Projekt NCK"), ("003", "MKiDN ksiazki")]):
        y = 726 - n * 11
        c.drawString(77, y, f"{n + 1}.")
        c.drawString(88, y, code)
        c.drawString(130, y, name)
    c.drawString(211, 660, "* * *   K o n i e c   z e s t a w i e n i a   * * *")
    c.showPage(); c.save()

    layout, items, _ = perm_import.parse(raw=buf.getvalue(), filename="fk.pdf")
    assert [i.permission_name for i in items] == [
        "001 - MiPBP", "002 - Projekt NCK", "003 - MKiDN ksiazki"]
    assert layout.group_suggested == "Oddzialy BIBLIOTEKA"
    roles = {c_.header: c_.role for c_ in layout.columns}
    assert roles["Lp."] == perm_import.ROLE_IGNORE
    assert roles["ODDZIAL"] == perm_import.ROLE_CODE
    assert roles["NAZWA"] == perm_import.ROLE_NAME


def test_pdf_detected_by_signature_not_extension():
    """Rozszerzenie bywa mylące — rozstrzyga sygnatura pliku."""
    pytest.importorskip("pdfminer.high_level")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 9)
    c.drawString(72, 741, "Symbol")
    c.drawString(160, 741, "Nazwa")
    c.drawString(72, 726, "ADA")
    c.drawString(160, 726, "Abonamenty")
    c.showPage(); c.save()

    _, items, _ = perm_import.parse(raw=buf.getvalue(), filename="lista.csv")
    assert [i.permission_name for i in items] == ["ADA - Abonamenty"]


def test_empty_file_is_rejected():
    with pytest.raises(perm_import.ImportError_):
        perm_import.parse(pasted="   \n  \n")


# ---------------------------------------------------------------------------
# API: preview → commit → reimport
# ---------------------------------------------------------------------------

def _system(api, sup, name="Program finansowy"):
    r = api.post("/systems/", token=sup, json={"name": name, "all_units": True})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _preview(api, sup, sid, text, **form):
    return api.post(f"/systems/{sid}/permissions/import/preview", token=sup,
                    data={"pasted": text, **form})


def _perms(api, sup, sid):
    return api.get(f"/systems/{sid}/permissions", token=sup).json()


def test_preview_then_commit(api):
    sup = api.setup_superadmin()
    sid = _system(api, sup)

    r = _preview(api, sup, sid, _as_csv(RAPORT_ROWS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["group_suggested"] == "Rejestry dokumentów rejestrów opłat"
    assert [i["permission_name"] for i in body["items"]] == NAMES
    assert all(i["status"] == "new" for i in body["items"])
    assert body["existing_in_group"] == 0

    r = api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": body["group_suggested"],
        "items": [{"permission_name": i["permission_name"],
                   "description": i["description"],
                   "external_code": i["external_code"]} for i in body["items"]],
    })
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 3

    perms = _perms(api, sup, sid)
    imported = [p for p in perms if p["group_name"]]
    assert len(imported) == 3
    assert all(p["group_name"] == "Rejestry dokumentów rejestrów opłat" for p in imported)
    assert all(p["is_active"] for p in imported)
    # Pozycja administratora nietknięta i NIE liczy się jako konfiguracja listy.
    assert any(p["is_admin_option"] for p in perms)
    row = next(x for x in api.get("/systems/", token=sup).json() if x["id"] == sid)
    assert row["permission_count"] == 3


def test_reimport_deactivates_missing_and_reactivates(api):
    """Wygaszanie zamiast kasowania — ewidencja osób musi przetrwać."""
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    group = "Rejestry opłat"

    def commit(rows, deactivate=True):
        body = _preview(api, sup, sid, _as_csv(rows), group_name=group).json()
        return api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
            "group_name": group,
            "items": [{"permission_name": i["permission_name"],
                       "external_code": i["external_code"]} for i in body["items"]],
            "deactivate_missing": deactivate,
        }).json()

    commit(RAPORT_ROWS)

    # W kolejnym eksporcie znika ALK.
    bez_alk = [r for r in RAPORT_ROWS if r[2] != "ALK"]
    res = commit(bez_alk)
    assert res["deactivated"] == 1
    assert res["added"] == 0

    perms = {p["external_code"]: p for p in _perms(api, sup, sid) if p["group_name"]}
    assert perms["ALK"]["is_active"] is False
    assert perms["ADA"]["is_active"] is True
    # Wygaszona pozycja WCIĄŻ istnieje — bez tego zerwałaby się ewidencja.
    assert len(perms) == 3

    # ALK wraca do eksportu → reaktywacja, nie duplikat.
    res = commit(RAPORT_ROWS)
    assert res["reactivated"] == 1
    perms = {p["external_code"]: p for p in _perms(api, sup, sid) if p["group_name"]}
    assert len(perms) == 3 and perms["ALK"]["is_active"] is True


def test_reimport_matches_by_code_when_name_changes(api):
    """Zmiana nazwy opisowej w źródle nie tworzy nowej pozycji."""
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    group = "Rejestry opłat"

    rows_v1 = [["Symbol", "Nazwa"], ["ADA", "Abonamenty"]]
    rows_v2 = [["Symbol", "Nazwa"], ["ADA", "Abonamenty i opłaty"]]

    for rows in (rows_v1, rows_v2):
        body = _preview(api, sup, sid, _as_csv(rows), group_name=group).json()
        res = api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
            "group_name": group,
            "items": [{"permission_name": i["permission_name"],
                       "external_code": i["external_code"]} for i in body["items"]],
        }).json()

    assert res["added"] == 0 and res["updated"] == 1
    imported = [p for p in _perms(api, sup, sid) if p["group_name"] == group]
    assert len(imported) == 1
    assert imported[0]["permission_name"] == "ADA - Abonamenty i opłaty"


def test_groups_are_independent(api):
    """Import drugiej grupy nie wygasza pierwszej."""
    sup = api.setup_superadmin()
    sid = _system(api, sup)

    for group, rows in (
        ("Rejestry opłat", [["Symbol", "Nazwa"], ["ADA", "Abonamenty"]]),
        ("Rejestry dochodów", [["Symbol", "Nazwa"], ["DOC", "Dochody"]]),
    ):
        body = _preview(api, sup, sid, _as_csv(rows), group_name=group).json()
        api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
            "group_name": group,
            "items": [{"permission_name": i["permission_name"],
                       "external_code": i["external_code"]} for i in body["items"]],
        })

    perms = [p for p in _perms(api, sup, sid) if p["group_name"]]
    assert {p["group_name"] for p in perms} == {"Rejestry opłat", "Rejestry dochodów"}
    assert all(p["is_active"] for p in perms)


def test_import_coexists_with_manual_permissions(api):
    """Pozycje z importu i ręczne (z kontrolką) żyją na JEDNEJ liście."""
    sup = api.setup_superadmin()
    sid = _system(api, sup, "Program mieszany")
    api.post(f"/systems/{sid}/permissions", token=sup, json={
        "permission_name": "Poziom dostępu", "input_type": "select",
        "options": ["Odczyt", "Zapis"]})

    body = _preview(api, sup, sid, _as_csv(RAPORT_ROWS)).json()
    r = api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "Rejestry",
        "items": [{"permission_name": i["permission_name"],
                   "external_code": i["external_code"]} for i in body["items"]]})
    assert r.status_code == 200, r.text

    perms = {p["permission_name"]: p for p in _perms(api, sup, sid)}
    # ręczna pozycja z kontrolką nietknięta
    assert perms["Poziom dostępu"]["input_type"] == "select"
    assert perms["Poziom dostępu"]["group_name"] is None
    # pozycje z importu to zwykłe checkboxy w swojej grupie
    imported = perms[NAMES[0]]
    assert imported["input_type"] == "none"
    assert imported["group_name"] == "Rejestry"


def test_import_blocked_for_access_only_system(api):
    sup = api.setup_superadmin()
    sid = _system(api, sup, "Program tylko dostęp")
    api.patch(f"/systems/{sid}", token=sup, json={"access_only": True})

    r = _preview(api, sup, sid, _as_csv([["Symbol", "Nazwa"], ["A", "B"]]))
    assert r.status_code == 400


def test_admin_position_cannot_be_imported(api):
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    res = api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "G",
        "items": [{"permission_name": "Uprawnienia administratora"},
                  {"permission_name": "Odczyt"}],
    }).json()
    assert res["added"] == 1 and res["skipped"] == 1
    names = [p["permission_name"] for p in _perms(api, sup, sid)]
    assert names.count("Uprawnienia administratora") == 1


def test_group_state_toggle(api):
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "G", "items": [{"permission_name": "Odczyt"},
                                     {"permission_name": "Zapis"}]})

    res = api.post(f"/systems/{sid}/permissions/group-state", token=sup,
                   json={"group_name": "G", "is_active": False}).json()
    assert res["deactivated"] == 2
    assert all(not p["is_active"] for p in _perms(api, sup, sid) if p["group_name"] == "G")

    res = api.post(f"/systems/{sid}/permissions/group-state", token=sup,
                   json={"group_name": "G", "is_active": True}).json()
    assert res["reactivated"] == 2


def test_manual_group_creation_and_append(api):
    """Grupa zakładana ręcznie w rejestrze — ta sama ścieżka, co import.

    Okno „Nowa grupa uprawnień" nie ma pliku, więc wysyła `deactivate_missing:
    False`: dopisuje pozycje i NIE rusza tych, których akurat nie wpisano.
    """
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    group = "Rejestry księgowe"

    def commit(names):
        return api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
            "group_name": group, "deactivate_missing": False,
            "items": [{"permission_name": n} for n in names]}).json()

    assert commit(["001 Wyciągi bankowe", "002 Faktury zakupu"])["added"] == 2

    # Dopisanie trzeciej pozycji nie wygasza dwóch pierwszych.
    res = commit(["003 Polecenia księgowania"])
    assert res["added"] == 1 and res["deactivated"] == 0

    rows = [p for p in _perms(api, sup, sid) if p["group_name"] == group]
    assert len(rows) == 3
    assert all(p["is_active"] for p in rows)
    # Pozycje grupy to zwykłe checkboxy — wybór wielu wariantów daje sama grupa.
    assert all(p["input_type"] == "none" for p in rows)


def test_group_rename(api):
    """Nazwa grupy jest wpisywana ręcznie, więc musi dać się poprawić."""
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "FK rejestry ksiegowe MUZEUM",
        "items": [{"permission_name": "001 Wyciągi bankowe", "external_code": "001"},
                  {"permission_name": "002 Faktury zakupu", "external_code": "002"}]})

    r = api.post(f"/systems/{sid}/permissions/group-rename", token=sup, json={
        "group_name": "FK rejestry ksiegowe MUZEUM",
        "new_name": "FK rejestry księgowe MUZEUM"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2

    groups = {p["group_name"] for p in _perms(api, sup, sid) if p["group_name"]}
    assert groups == {"FK rejestry księgowe MUZEUM"}

    # Ponowny import pod nową nazwą trafia w te same pozycje (klucz = symbol).
    res = api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "FK rejestry księgowe MUZEUM",
        "items": [{"permission_name": "001 Wyciągi bankowe", "external_code": "001"},
                  {"permission_name": "002 Faktury zakupu", "external_code": "002"}]}).json()
    assert res["added"] == 0 and res["updated"] == 2


def test_group_rename_rejects_existing_name(api):
    """Scalanie grup mogłoby zdublować uprawnienia — odmawiamy wprost."""
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    for g in ("Grupa A", "Grupa B"):
        api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
            "group_name": g, "items": [{"permission_name": f"Odczyt {g}"}]})

    r = api.post(f"/systems/{sid}/permissions/group-rename", token=sup,
                 json={"group_name": "Grupa A", "new_name": "Grupa B"})
    assert r.status_code == 400
    assert "już istnieje" in r.text


def test_group_delete_keeps_permissions_used_in_requests(api):
    """Usunięcie grupy nie może zerwać ewidencji już nadanych uprawnień."""
    sup = api.setup_superadmin()
    unit = api.mk_unit(sup, "U", "U")
    kid = api.mk_user(sup, "kier", ["manager"], "Kier")
    api.mk_user(sup, "it", ["it_staff"], "IT")
    api.mk_user(sup, "hr", ["hr"], "HR", unit_ids=[unit])
    dep = api.mk_department(sup, unit, kid, name="K")

    sid = _system(api, sup)
    api.post(f"/systems/{sid}/permissions/import/commit", token=sup, json={
        "group_name": "G",
        "items": [{"permission_name": "Odczyt"}, {"permission_name": "Zapis"}]})
    perms = {p["permission_name"]: p["id"]
             for p in _perms(api, sup, sid) if p["group_name"] == "G"}

    # Wniosek używający jednej z pozycji — wystarczy samo jego złożenie,
    # bo RequestItem powstaje razem z wnioskiem.
    r = api.post("/requests/", token=api.login("hr"), json={
        "worker_name": "Pracownik",
        "unit_id": unit, "department_id": dep,
        "request_type_id": api.request_type(sup),
        "items": [{"system_id": sid, "permission_id": perms["Odczyt"], "kind": "grant"}],
    })
    assert r.status_code in (200, 201), r.text

    res = api.post(f"/systems/{sid}/permissions/group-delete", token=sup,
                   json={"group_name": "G"}).json()
    assert res["deactivated"] == 1 and res["skipped"] == 1

    left = {p["permission_name"]: p for p in _perms(api, sup, sid) if p["group_name"] == "G"}
    assert set(left) == {"Odczyt"}          # użyte — zachowane…
    assert left["Odczyt"]["is_active"] is False   # …ale wygaszone


def test_import_requires_it_staff(api):
    sup = api.setup_superadmin()
    sid = _system(api, sup)
    uid = api.mk_user(sup, "kier", ["manager"], "Kier")
    tok = api.login("kier")

    r = api.post(f"/systems/{sid}/permissions/import/commit", token=tok, json={
        "group_name": "G", "items": [{"permission_name": "Odczyt"}]})
    assert r.status_code == 403
