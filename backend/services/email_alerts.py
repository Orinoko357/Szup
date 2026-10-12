"""
Powiadomienia e-mail dla SZUP.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)

# Skrzynka helpdesku IT — dostaje zgłoszenie, gdy wniosek trafia do realizacji.
# Można nadpisać zmienną środowiskową bez zmiany kodu.
HELPDESK_EMAIL = os.getenv("SZUP_HELPDESK_EMAIL", "helpdesk@wodzislaw-slaski.pl")
# Adres aplikacji wstawiany w treści powiadomień.
APP_URL = os.getenv("SZUP_APP_URL", "https://szup.intranet.wods.pl")


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


def notify_manager_new_request(manager_email: str, request_id: int, worker_name: str,
                                dept_name: str, created_by: str,
                                from_name: str | None = None,
                                from_email: str | None = None) -> None:
    _send(
        to_address=manager_email,
        subject=f"[SZUP] Nowy wniosek #{request_id} do akceptacji",
        body=(
            f"Wpłynął nowy wniosek o nadanie uprawnień wymagający Twojej akceptacji.\n\n"
            f"Nr wniosku:  #{request_id}\n"
            f"Pracownik:   {worker_name}\n"
            f"Wydział:     {dept_name}\n"
            f"Złożył(a):   {created_by}\n\n"
            f"Zaloguj się do systemu SZUP, aby zatwierdzić lub odrzucić wniosek.\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
        from_name=from_name, from_email=from_email,
    )


def notify_selector_new_request(manager_email: str, request_id: int, worker_name: str,
                                 dept_name: str, created_by: str,
                                 from_name: str | None = None,
                                 from_email: str | None = None) -> None:
    _send(
        to_address=manager_email,
        subject=f"[SZUP] Nowy wniosek #{request_id} — wybór uprawnień",
        body=(
            f"Wpłynął nowy wniosek o nadanie uprawnień dla nowego pracownika w Twoim wydziale.\n"
            f"Twoja rola: wskaż uprawnienia, które mają zostać nadane. Zatwierdzenia dokona\n"
            f"kierownik wydziału nadrzędnego.\n\n"
            f"Nr wniosku:  #{request_id}\n"
            f"Pracownik:   {worker_name}\n"
            f"Wydział:     {dept_name}\n"
            f"Złożył(a):   {created_by}\n\n"
            f"Zaloguj się do systemu SZUP, aby wybrać uprawnienia.\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
        from_name=from_name, from_email=from_email,
    )


def notify_higher_manager_request(manager_email: str, request_id: int, worker_name: str,
                                   dept_name: str, selector_name: str) -> None:
    _send(
        to_address=manager_email,
        subject=f"[SZUP] Wniosek #{request_id} do akceptacji wyższego rzędu",
        body=(
            f"Kierownik podległego wydziału wybrał uprawnienia dla nowego pracownika i prosi\n"
            f"o Twoją akceptację.\n\n"
            f"Nr wniosku:  #{request_id}\n"
            f"Pracownik:   {worker_name}\n"
            f"Wydział:     {dept_name}\n"
            f"Wybrał(a):   {selector_name}\n\n"
            f"Zaloguj się do systemu SZUP, aby zatwierdzić lub odrzucić wniosek.\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
    )


def notify_it_request_approved(it_emails: list[str], request_id: int, worker_name: str,
                                 dept_name: str, manager_name: str,
                                 from_name: str | None = None,
                                 from_email: str | None = None) -> None:
    for email in it_emails:
        _send(
            to_address=email,
            subject=f"[SZUP] Wniosek #{request_id} zatwierdzony — do realizacji",
            body=(
                f"Wniosek o nadanie uprawnień został zatwierdzony przez kierownika.\n\n"
                f"Nr wniosku:   #{request_id}\n"
                f"Pracownik:    {worker_name}\n"
                f"Wydział:      {dept_name}\n"
                f"Zatwierdził:  {manager_name}\n\n"
                f"Zaloguj się do systemu SZUP, aby zrealizować wniosek.\n\n"
                f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            ),
            from_name=from_name, from_email=from_email,
        )


def notify_helpdesk_new_request(request_id: int, worker_name: str,
                                manager_name: str, kind: str = "grant",
                                to_address: str | None = None,
                                from_name: str | None = None,
                                from_email: str | None = None) -> None:
    """Zgłoszenie na helpdesk IT — wniosek wszedł w krok realizacji.

    Treść zgodna z ustaleniami: kto wystąpił, dla kogo i link do systemu.
    Wariant tekstu zależy od rodzaju wniosku, żeby przy ustaniu stosunku pracy
    nie wysyłać „wniosku o nadanie uprawnień".
    """
    what = {
        "revoke": "odebranie uprawnień",
        "change": "zmianę uprawnień",
    }.get(kind, "nadanie uprawnień")
    subject = {
        "revoke": "Nowy wniosek o odebranie uprawnień",
        "change": "Nowy wniosek o zmianę uprawnień",
    }.get(kind, "Nowy wniosek o nadanie uprawnień")

    # Adres wnioskodawcy wpisany WPROST w treść — widoczny na helpdesku nawet
    # jeśli serwer SMTP przepisze nagłówek „Od" na konto uwierzytelnione.
    applicant_line = ""
    if from_email:
        who = f"{from_name} <{from_email}>" if from_name else from_email
        applicant_line = f"Wnioskodawca: {who}\n"

    _send(
        to_address=to_address or resolve_helpdesk_email(),
        subject=subject,
        body=(
            f"{manager_name} wystąpił z wnioskiem o {what} "
            f"dla {worker_name}\n\n"
            f"{applicant_line}"
            f"{APP_URL}\n"
        ),
        from_name=from_name, from_email=from_email,
    )


def notify_request_completed(requester_email: str, request_id: int, worker_name: str,
                             from_name: str | None = None,
                             from_email: str | None = None) -> None:
    _send(
        to_address=requester_email,
        subject=f"[SZUP] Wniosek #{request_id} zrealizowany",
        body=(
            f"Wniosek o nadanie uprawnień został zrealizowany przez dział IT.\n\n"
            f"Nr wniosku:  #{request_id}\n"
            f"Pracownik:   {worker_name}\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
        from_name=from_name, from_email=from_email,
    )


def notify_request_rejected(requester_email: str, request_id: int,
                              worker_name: str, comment: str) -> None:
    _send(
        to_address=requester_email,
        subject=f"[SZUP] Wniosek #{request_id} odrzucony",
        body=(
            f"Wniosek o nadanie uprawnień został odrzucony.\n\n"
            f"Nr wniosku:  #{request_id}\n"
            f"Pracownik:   {worker_name}\n"
            f"Powód:       {comment or '(brak komentarza)'}\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
    )


def notify_workflow_stage(to_address: str, request_id: int, worker_name: str,
                          dept_name: str, stage_label: str, node_type: str,
                          from_name: str | None = None,
                          from_email: str | None = None) -> None:
    """Generyczne powiadomienie: wniosek wszedł w nowy etap obiegu i wymaga
    działania adresata. Używane przez silnik workflow (advance).
    """
    action_hint = {
        "select_permissions":     "Wybierz uprawnienia, pobierz PDF do podpisu i prześlij EZD FINN.",
        "manager_approve":        "Zaakceptuj wniosek: pobierz PDF, podpisz, prześlij EZD FINN.",
        "higher_manager_approve": "Zaakceptuj wniosek: pobierz PDF, podpisz, prześlij EZD FINN.",
        "it_execute":             "Zrealizuj wniosek technicznie w Biurze Informatyki.",
    }.get(node_type, "Wniosek wymaga Twojego działania.")
    _send(
        to_address=to_address,
        subject=f"[SZUP] Wniosek #{request_id} czeka na Ciebie — {stage_label}",
        body=(
            f"Wniosek o uprawnienia wszedł w nowy etap obiegu i wymaga Twojego działania.\n\n"
            f"Nr wniosku:    #{request_id}\n"
            f"Pracownik:     {worker_name}\n"
            f"Wydział:       {dept_name}\n"
            f"Etap:          {stage_label}\n\n"
            f"Co należy zrobić:\n"
            f"  {action_hint}\n\n"
            f"Zaloguj się do SZUP → Do akceptacji → otwórz wniosek #{request_id}.\n\n"
            f"-- SZUP {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
        from_name=from_name, from_email=from_email,
    )
