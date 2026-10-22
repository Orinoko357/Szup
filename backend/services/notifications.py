"""
Szablony powiadomień e-mail SZUP — treść konfigurowalna z makrami.

Każde zdarzenie (event_key) ma domyślny temat i treść zdefiniowane tutaj.
Administrator może je nadpisać w Ustawieniach → Powiadomienia (tabela
`NotificationTemplate`). Makra w formacie `{nazwa}` są podmieniane na wartości
z kontekstu zdarzenia; nieznane `{...}` zostają bez zmian.

Obieg odbywa się w całości w aplikacji — treści nie odwołują się do
dokumentów poza nią.

Szablony oznaczone `"hidden": True` nie są już wysyłane (zastąpiło je
powiadomienie etapu `workflow_stage`); zostają w rejestrze, żeby nie gubić
treści zapisanych wcześniej w Ustawieniach.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Wspólne makra dostępne (prawie) wszędzie — do pokazania w UI.
# {request_url} — link prosto do wniosku (v3.1); {app_url} — strona główna.
_COMMON = ["{request_id}", "{worker_name}", "{dept_name}", "{unit_name}",
           "{request_url}", "{app_url}", "{date}", "{datetime}"]


# Rejestr zdarzeń: etykieta, opis, makra (do podpowiedzi w UI) oraz domyślny
# temat i treść. Kolejność = kolejność wyświetlania w Ustawieniach.
EVENTS: dict[str, dict] = {
    "selector_new_request": {
        "hidden": True,
        "label": "Nowy wniosek — wybór uprawnień (kierownik komórki)",
        "description": "(nieużywany — wysyłkę robi powiadomienie etapu „Wniosek wszedł w nowy etap”) "
                       "Trafia do kierownika, który ma wskazać uprawnienia dla pracownika.",
        "macros": _COMMON + ["{created_by}"],
        "subject": "[SZUP] Nowy wniosek #{request_id} — wybór uprawnień",
        "body": (
            "Wpłynął nowy wniosek o nadanie uprawnień dla pracownika w Twojej komórce.\n"
            "Twoja rola: wskaż uprawnienia, które mają zostać nadane.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "Wydział:     {dept_name}\n"
            "Złożył(a):   {created_by}\n\n"
            "Wybierz uprawnienia: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "manager_new_request": {
        "hidden": True,
        "label": "Nowy wniosek — do akceptacji kierownika",
        "description": "(nieużywany — wysyłkę robi powiadomienie etapu „Wniosek wszedł w nowy etap”) "
                       "Trafia do kierownika komórki, który zatwierdza wniosek.",
        "macros": _COMMON + ["{created_by}"],
        "subject": "[SZUP] Nowy wniosek #{request_id} do akceptacji",
        "body": (
            "Wpłynął nowy wniosek o nadanie uprawnień wymagający Twojej akceptacji.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "Wydział:     {dept_name}\n"
            "Złożył(a):   {created_by}\n\n"
            "Zatwierdź lub odrzuć wniosek: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "higher_manager_request": {
        "hidden": True,
        "label": "Wniosek — akceptacja kierownika wyższego rzędu",
        "description": "(nieużywany — wysyłkę robi powiadomienie etapu „Wniosek wszedł w nowy etap”) "
                       "Trafia do kierownika nadrzędnego po wyborze uprawnień przez kierownika komórki.",
        "macros": _COMMON + ["{selector_name}"],
        "subject": "[SZUP] Wniosek #{request_id} do akceptacji wyższego rzędu",
        "body": (
            "Kierownik podległej komórki wybrał uprawnienia dla pracownika i prosi o Twoją akceptację.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "Wydział:     {dept_name}\n"
            "Wybrał(a):   {selector_name}\n\n"
            "Zatwierdź lub odrzuć wniosek: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "it_request_approved": {
        "hidden": True,
        "label": "Wniosek zatwierdzony — do realizacji przez IT",
        "description": "(nieużywany — wysyłkę robi powiadomienie etapu „Wniosek wszedł w nowy etap” i zgłoszenie na helpdesk) "
                       "Trafia do pracowników IT po zatwierdzeniu wniosku.",
        "macros": _COMMON + ["{manager_name}"],
        "subject": "[SZUP] Wniosek #{request_id} zatwierdzony — do realizacji",
        "body": (
            "Wniosek o nadanie uprawnień został zatwierdzony przez kierownika.\n\n"
            "Nr wniosku:   #{request_id}\n"
            "Pracownik:    {worker_name}\n"
            "Wydział:      {dept_name}\n"
            "Zatwierdził:  {manager_name}\n\n"
            "Zrealizuj wniosek: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "helpdesk_new_request": {
        "label": "Zgłoszenie na helpdesk IT (realizacja)",
        "description": "Trafia na skrzynkę helpdesku, gdy wniosek wchodzi w krok realizacji.",
        "macros": _COMMON + ["{manager_name}", "{what}", "{applicant}"],
        "subject": "[SZUP] Nowy wniosek o {what}",
        "body": (
            "{manager_name} wystąpił z wnioskiem o {what} dla {worker_name}.\n\n"
            "{applicant_line}"
            "Nr wniosku: #{request_id}\n"
            "{request_url}\n"
        ),
    },
    "request_completed": {
        "label": "Wniosek zrealizowany (do wnioskodawcy)",
        "description": "Potwierdzenie realizacji; sekcja odmów pojawia się automatycznie, jeśli coś odmówiono.",
        "macros": _COMMON + ["{denied_block}", "{denied_suffix}"],
        "subject": "[SZUP] Wniosek #{request_id} zrealizowany{denied_suffix}",
        "body": (
            "Wniosek o nadanie uprawnień został zrealizowany przez dział IT.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "{denied_block}\n"
            "Szczegóły: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "request_rejected": {
        "label": "Wniosek odrzucony (do wnioskodawcy)",
        "description": "Informacja o odrzuceniu całego wniosku wraz z powodem.",
        "macros": _COMMON + ["{comment}"],
        "subject": "[SZUP] Wniosek #{request_id} odrzucony",
        "body": (
            "Wniosek o nadanie uprawnień został odrzucony.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "Powód:       {comment}\n\n"
            "Szczegóły: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "workflow_stage": {
        "label": "Wniosek wszedł w nowy etap (generyczne)",
        "description": "Ogólne powiadomienie o wejściu wniosku w etap wymagający działania adresata.",
        "macros": _COMMON + ["{stage_label}", "{action_hint}"],
        "subject": "[SZUP] Wniosek #{request_id} czeka na Ciebie — {stage_label}",
        "body": (
            "Wniosek o uprawnienia wszedł w nowy etap obiegu i wymaga Twojego działania.\n\n"
            "Nr wniosku:    #{request_id}\n"
            "Pracownik:     {worker_name}\n"
            "Wydział:       {dept_name}\n"
            "Etap:          {stage_label}\n\n"
            "Co należy zrobić:\n"
            "  {action_hint}\n\n"
            "Otwórz wniosek #{request_id}: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "request_taken_over": {
        "label": "Wniosek przejęty przez przełożonego (do kierownika komórki)",
        "description": "Trafia do kierownika komórki i jego zastępców (oraz do poprzednio "
                       "przejmującego), gdy przełożony przejmie wniosek z etapu kierownika komórki.",
        "macros": _COMMON + ["{taker_name}"],
        "subject": "[SZUP] Wniosek #{request_id} przejęty przez przełożonego",
        "body": (
            "{taker_name} przejął(-ęła) wniosek o uprawnienia czekający na etapie "
            "kierownika komórki.\n\n"
            "Nr wniosku:  #{request_id}\n"
            "Pracownik:   {worker_name}\n"
            "Wydział:     {dept_name}\n\n"
            "Dalsze kroki na etapie kierownika komórki wykona przełożony — "
            "Ty możesz jedynie podejrzeć wniosek.\n\n"
            "Podgląd wniosku: {request_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
    "name_change_requested": {
        "label": "Wniosek o zmianę nazwiska (helpdesk IT)",
        "description": "Trafia na skrzynkę helpdesku, gdy pracownik zgłosi zmianę nazwiska.",
        "macros": ["{full_name}", "{new_name}", "{names_url}", "{app_url}",
                   "{date}", "{datetime}"],
        "subject": "[SZUP] Nowy wniosek o zmianę nazwiska",
        "body": (
            "{full_name} zgłosił(a) zmianę nazwiska na: {new_name}.\n\n"
            "Rozpatrz wniosek w SZUP (Wnioski → Zmiany nazwisk): {names_url}\n\n"
            "-- SZUP {datetime}"
        ),
    },
}

# Podpowiedzi „co zrobić" dla generycznego powiadomienia o etapie — BEZ PDF/EZD.
STAGE_ACTIONS = {
    "select_permissions":     "Wskaż uprawnienia, które mają zostać nadane.",
    "manager_approve":        "Zatwierdź albo odrzuć wniosek.",
    "higher_manager_approve": "Zatwierdź albo odrzuć wniosek.",
    "it_execute":             "Zrealizuj wniosek technicznie w Biurze Informatyki.",
}


def _default(event_key: str) -> dict:
    return EVENTS.get(event_key, {})


def _apply_macros(text: str, ctx: dict) -> str:
    out = str(text or "")
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out


def _base_context() -> dict:
    now = datetime.now()
    # app_url pobieramy leniwie, żeby uniknąć cyklu importów przy starcie.
    try:
        from services.email_alerts import APP_URL
        app_url = APP_URL
    except Exception:
        app_url = ""
    return {
        "app_url": app_url,
        # Domyślnie strona główna — konkretny link do wniosku podają wywołania.
        "request_url": app_url,
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d %H:%M"),
    }


def load_template(event_key: str) -> tuple[str, str, bool]:
    """Zwraca (subject, body, enabled) — z bazy (jeśli zapisano) albo domyślny."""
    d = _default(event_key)
    subject, body, enabled = d.get("subject", ""), d.get("body", ""), True
    try:
        from database import engine
        from sqlmodel import Session
        from models import NotificationTemplate
        with Session(engine) as s:
            row = s.get(NotificationTemplate, event_key)
            if row:
                enabled = bool(row.enabled)
                if (row.subject or "").strip():
                    subject = row.subject
                if (row.body or "").strip():
                    body = row.body
    except Exception as exc:
        logger.warning("Nie udało się wczytać szablonu '%s': %s", event_key, exc)
    return subject, body, enabled


def render(event_key: str, ctx: Optional[dict] = None) -> tuple[str, str, bool]:
    """Wyrenderuj temat i treść powiadomienia. Zwraca (subject, body, enabled)."""
    subject, body, enabled = load_template(event_key)
    full = {**_base_context(), **(ctx or {})}
    return _apply_macros(subject, full), _apply_macros(body, full), enabled
