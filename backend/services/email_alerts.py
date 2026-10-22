"""
Powiadomienia e-mail dla SZUP.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)

# Skrzynka helpdesku IT — dostaje zgłoszenie, gdy wniosek trafia do realizacji.
# Można nadpisać zmienną środowiskową bez zmiany kodu.
HELPDESK_EMAIL = os.getenv("SZUP_HELPDESK_EMAIL", "helpdesk@wodzislaw-slaski.pl")
# Adres aplikacji wstawiany w treści powiadomień.
APP_URL = os.getenv("SZUP_APP_URL", "https://szup.intranet.wods.pl")


def request_url(request_id: int, tab: str = "handle") -> str:
    """Link prosto do wniosku w aplikacji (v3.1) — /requests?tab=…&open=<id>."""
    return f"{APP_URL.rstrip('/')}/requests?tab={tab}&open={request_id}"


def names_queue_url() -> str:
    """Kolejka IT wniosków o zmianę nazwiska — /requests?tab=names."""
    return f"{APP_URL.rstrip('/')}/requests?tab=names"


def requester_url(request_id: int, requester_is_manager: bool | None,
                  requester_is_hr: bool | None = None) -> str:
    """Link dla wnioskodawcy: kierownik → „Moje wnioski”, kadry → Kartoteka,
    pozostali (np. superadmin bez tych ról) → strona główna — /hr wymaga roli HR."""
    if requester_is_manager:
        return request_url(request_id, "mine")
    if requester_is_hr is False:
        return APP_URL.rstrip('/')
    return f"{APP_URL.rstrip('/')}/hr"


def _get_settings():
    from database import engine
    from sqlmodel import Session, select
    from models import EmailSettings
    with Session(engine) as s:
        return s.exec(select(EmailSettings)).first()


def resolve_helpdesk_email() -> str:
    """Adres helpdesku: z Ustawień aplikacji, a gdy nieustawiony — domyślny."""
    try:
        from database import engine
        from sqlmodel import Session, select
        from models import AppSettings
        with Session(engine) as s:
            cfg = s.exec(select(AppSettings)).first()
            val = (cfg.helpdesk_email or "").strip() if cfg else ""
            if val:
                return val
    except Exception as exc:
        logger.warning("Nie udało się odczytać adresu helpdesku z ustawień: %s", exc)
    return HELPDESK_EMAIL


def _send(to_address: str, subject: str, body: str, *,
          from_name: str | None = None, from_email: str | None = None,
          raise_errors: bool = False) -> None:
    """Wyślij e-mail. Domyślnie best-effort (błędy tylko logowane) — powiadomienia
    obiegu nie mogą wywrócić żądania. Przy `raise_errors=True` (test SMTP) wyjątek
    jest przekazywany dalej, żeby użytkownik zobaczył prawdziwą przyczynę.

    `from_name`/`from_email` — jeśli w ustawieniach włączony `sender_as_actor`,
    wiadomość PREZENTUJE się jako wysłana przez osobę, która wywołała zdarzenie
    (np. wnioskodawcę). Koperta SMTP (MAIL FROM) pozostaje uwierzytelnionym
    adresem `from_address` — dzięki temu, że oba adresy są w tej samej domenie,
    SPF/DMARC są zgodne i poczta nie trafia do spamu. Odpowiedź (Reply-To) idzie
    do aktora, żeby adresat mógł odpisać wprost do niego.
    """
    try:
        from services.crypto import decrypt
        cfg = _get_settings()
        if not cfg or not cfg.enabled or not cfg.smtp_host:
            if raise_errors:
                raise RuntimeError(
                    "Powiadomienia e-mail są wyłączone lub brak adresu serwera SMTP.")
            return

        password = decrypt(cfg.smtp_password_enc) if cfg.smtp_password_enc else ""
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject

        # Nadawca prezentowany w nagłówku From.
        actor_email = (from_email or "").strip()
        use_actor = bool(getattr(cfg, "sender_as_actor", True)) and bool(actor_email)
        if use_actor:
            msg["From"] = formataddr((from_name or "", actor_email))
            if actor_email.lower() != (cfg.from_address or "").lower():
                # Adresat odpisuje wprost do osoby, która wywołała zdarzenie.
                msg["Reply-To"] = formataddr((from_name or "", actor_email))
        else:
            msg["From"] = cfg.from_address
        msg["To"] = to_address
        # Koperta SMTP zawsze z uwierzytelnionego adresu (SPF/relay).
        envelope_from = cfg.from_address

        # Domyślny odbiorca CC z ustawień (jeśli różny od głównego adresata).
        cc = (getattr(cfg, "to_address", "") or "").strip()
        recipients = [to_address]
        if cc and cc != to_address:
            msg["Cc"] = cc
            recipients.append(cc)

        # Login i hasło SMTP nigdy nie idą otwartym tekstem: uwierzytelnienie
        # tylko po STARTTLS. Bez TLS wysyłamy wyłącznie przez relay bez logowania.
        if cfg.smtp_user and not cfg.use_tls:
            logger.error(
                "Odmowa wysyłki e-mail '%s': logowanie SMTP bez TLS ujawniłoby hasło. "
                "Włącz STARTTLS w Ustawieniach → E-mail albo usuń login (relay bez "
                "uwierzytelnienia).", subject)
            if raise_errors:
                raise RuntimeError(
                    "Logowanie do serwera SMTP wymaga szyfrowania — włącz STARTTLS "
                    "albo usuń login, jeśli serwer przyjmuje pocztę bez uwierzytelnienia.")
            return

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
            if cfg.use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, password)
            smtp.send_message(msg, from_addr=envelope_from, to_addrs=recipients)
        logger.info("E-mail wysłany: %s → %s", subject, ", ".join(recipients))
    except Exception as exc:
        logger.warning("Błąd wysyłania e-mail '%s': %s", subject, exc)
        if raise_errors:
            raise


def _send_event(event_key: str, to_address: str, ctx: dict, *,
                from_name: str | None = None, from_email: str | None = None,
                raise_errors: bool = False) -> None:
    """Wyrenderuj szablon zdarzenia i wyślij. Gdy szablon wyłączony — nie wysyła."""
    from services.notifications import render
    subject, body, enabled = render(event_key, ctx)
    if not enabled:
        logger.info("Powiadomienie '%s' wyłączone w ustawieniach — pominięto.", event_key)
        return
    _send(to_address, subject, body,
          from_name=from_name, from_email=from_email, raise_errors=raise_errors)


# Szablony `manager_new_request`, `selector_new_request`, `higher_manager_request`
# i `it_request_approved` obsługiwała wyłącznie dawna ścieżka tworzenia wniosku
# bez typu (usunięta). Definicje zostają w services.notifications.EVENTS
# (oznaczone `hidden`), ale nic ich już nie wysyła — obieg używa
# `workflow_stage` i `helpdesk_new_request`.


def notify_name_change_requested(full_name: str, new_name: str,
                                 from_name: str | None = None,
                                 from_email: str | None = None) -> None:
    """Nowy wniosek o zmianę nazwiska → skrzynka helpdesku z linkiem do kolejki IT."""
    _send_event("name_change_requested", resolve_helpdesk_email(), {
        "full_name": full_name, "new_name": new_name,
        "names_url": names_queue_url(), "request_url": names_queue_url(),
    }, from_name=from_name, from_email=from_email)


def notify_helpdesk_new_request(request_id: int, worker_name: str,
                                manager_name: str, kind: str = "grant",
                                to_address: str | None = None,
                                from_name: str | None = None,
                                from_email: str | None = None) -> None:
    """Zgłoszenie na helpdesk IT — wniosek wszedł w krok realizacji.

    Wariant tekstu zależy od rodzaju wniosku (`{what}`), żeby przy ustaniu
    stosunku pracy nie wysyłać „wniosku o nadanie uprawnień". Adres wnioskodawcy
    (`{applicant_line}`) trafia wprost w treść — widoczny na helpdesku nawet gdy
    serwer SMTP przepisze nagłówek „Od".
    """
    what = {
        "revoke": "odebranie uprawnień",
        "change": "zmianę uprawnień",
    }.get(kind, "nadanie uprawnień")

    applicant = ""
    applicant_line = ""
    if from_email:
        applicant = f"{from_name} <{from_email}>" if from_name else from_email
        applicant_line = f"Wnioskodawca: {applicant}\n"

    _send_event("helpdesk_new_request", to_address or resolve_helpdesk_email(), {
        "request_id": request_id, "worker_name": worker_name,
        "manager_name": manager_name, "what": what,
        "applicant": applicant, "applicant_line": applicant_line,
        "request_url": request_url(request_id, "it"),
    }, from_name=from_name, from_email=from_email)


def notify_request_completed(requester_email: str, request_id: int, worker_name: str,
                             from_name: str | None = None,
                             from_email: str | None = None,
                             denied_lines: list[str] | None = None,
                             requester_is_manager: bool | None = None,
                             requester_is_hr: bool | None = None) -> None:
    # Sekcja z pozycjami, których NIE nadano (odmowa IT / kierownika nadrzędnego).
    denied_block = ""
    denied_suffix = ""
    if denied_lines:
        bullet = "\n".join(f"  • {line}" for line in denied_lines)
        denied_block = ("\nUWAGA — następujące pozycje NIE zostały nadane (odmowa):\n"
                        f"{bullet}\n")
        denied_suffix = " (część pozycji odmówiono)"
    _send_event("request_completed", requester_email, {
        "request_id": request_id, "worker_name": worker_name,
        "denied_block": denied_block, "denied_suffix": denied_suffix,
        "request_url": requester_url(request_id, requester_is_manager, requester_is_hr),
    }, from_name=from_name, from_email=from_email)


def notify_request_rejected(requester_email: str, request_id: int,
                              worker_name: str, comment: str,
                              requester_is_manager: bool | None = None,
                             requester_is_hr: bool | None = None) -> None:
    _send_event("request_rejected", requester_email, {
        "request_id": request_id, "worker_name": worker_name,
        "comment": comment or "(brak komentarza)",
        "request_url": requester_url(request_id, requester_is_manager, requester_is_hr),
    })


def notify_workflow_stage(to_address: str, request_id: int, worker_name: str,
                          dept_name: str, stage_label: str, node_type: str,
                          from_name: str | None = None,
                          from_email: str | None = None) -> None:
    """Generyczne powiadomienie: wniosek wszedł w nowy etap obiegu i wymaga
    działania adresata. Używane przez silnik workflow (advance)."""
    from services.notifications import STAGE_ACTIONS
    action_hint = STAGE_ACTIONS.get(node_type, "Wniosek wymaga Twojego działania.")
    _send_event("workflow_stage", to_address, {
        "request_id": request_id, "worker_name": worker_name,
        "dept_name": dept_name, "stage_label": stage_label,
        "action_hint": action_hint,
        "request_url": request_url(request_id, "it" if node_type == "it_execute" else "handle"),
    }, from_name=from_name, from_email=from_email)


def notify_request_taken_over(to_address: str, request_id: int, worker_name: str,
                              dept_name: str, taker_name: str,
                              from_name: str | None = None,
                              from_email: str | None = None) -> None:
    """Przełożony przejął wniosek czekający u kierownika komórki — informacja
    dla kierownika (i zastępców), że krok kierowniczy wykona przejmujący."""
    _send_event("request_taken_over", to_address, {
        "request_id": request_id, "worker_name": worker_name,
        "dept_name": dept_name or "", "taker_name": taker_name,
        "request_url": request_url(request_id),
    }, from_name=from_name, from_email=from_email)
