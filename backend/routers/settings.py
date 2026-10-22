"""
Router: Ustawienia SMTP i LDAP — admin only.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from datetime import datetime

from models import (AppSettings, EmailSettings, LdapSettings, NotificationTemplate,
                    SecuritySeverity, User)
from services.auth_service import get_current_user
from services.permissions import require_admin, require_superadmin

router = APIRouter()


# Domyślna treść oświadczenia wnioskującego. Nadpisywalna w Ustawieniach
# (AppSettings.declaration_text); zmiana NIE działa wstecz — każde złożone
# oświadczenie zamraża własną kopię.
DEFAULT_DECLARATION_TEXT = """\
OŚWIADCZENIE WNIOSKUJĄCEGO O NADANIE UPRAWNIEŃ DO SYSTEMÓW TELEINFORMATYCZNYCH

Jako osoba wnioskująca o nadanie uprawnień do systemów teleinformatycznych oświadczam, że:

1. Pracownik, którego dotyczy wniosek o nadanie uprawnień posiada aktualne i stosowne \
upoważnienie do przetwarzania danych osobowych nadane przez Administratora danych,
2. Zakres wnioskowanych uprawnień w systemach teleinformatycznych jest zgodny z zakresem \
obowiązków służbowych pracownika oraz nie wykracza poza konieczny zakres dostępu niezbędny \
do realizacji powierzonych mu zadań.
3. Jestem świadomy/a, że:
   - do korzystania z systemów teleinformatycznych zawierających dane osobowe mogą być \
dopuszczone wyłącznie osoby posiadające wymagane upoważnienia i zapewniające bezpieczeństwo \
przetwarzanych danych,
   - nadanie dostępu do systemów teleinformatycznych nie może naruszać przepisów o ochronie \
danych osobowych ani wewnętrznych regulacji jednostki.
4. Zobowiązuję się niezwłocznie poinformować komórkę IT o każdej zmianie statusu pracownika \
(np. zmiana stanowiska, zakresu obowiązków, odwołanie upoważnienia, zakończenie zatrudnienia), \
mającej wpływ na zasadność lub zakres przyznanych mu uprawnień w systemach teleinformatycznych, \
w celu odpowiedniego zmodyfikowania lub cofnięcia dostępu.
5. Oświadczam, że informacje zawarte we wniosku o nadanie uprawnień oraz niniejszym \
oświadczeniu są zgodne ze stanem faktycznym."""


def effective_declaration_text(session: Session) -> str:
    """Aktualna treść oświadczenia: z ustawień, a gdy pusta — domyślna."""
    cfg = session.exec(select(AppSettings)).first()
    val = (cfg.declaration_text or "").strip() if cfg else ""
    return val or DEFAULT_DECLARATION_TEXT


@router.get("/declaration-text")
def get_declaration_text(
    _: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Aktualna treść oświadczenia — dla KAŻDEGO zalogowanego (kierownik musi
    ją zobaczyć w modalu przed podpisaniem, a nie jest adminem)."""
    return {"declaration_text": effective_declaration_text(session)}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

class EmailSettingsSchema(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: Optional[str] = None
    from_address: str = ""
    to_address: str = ""
    use_tls: bool = True
    sender_as_actor: bool = True


class EmailSettingsRead(BaseModel):
    id: Optional[int]
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    from_address: str
    to_address: str
    use_tls: bool
    sender_as_actor: bool
    has_password: bool


def _email_read(cfg: EmailSettings) -> "EmailSettingsRead":
    # `to_address`/`sender_as_actor` doszły migracją, na istniejących bazach
    # w starym wierszu mogą być NULL — koalescujemy, inaczej walidacja
    # (pola nie-nullowalne) wywala GET /email i formularz jest pusty.
    return EmailSettingsRead(
        id=cfg.id, enabled=cfg.enabled, smtp_host=cfg.smtp_host,
        smtp_port=cfg.smtp_port, smtp_user=cfg.smtp_user,
        from_address=cfg.from_address, to_address=(cfg.to_address or ""),
        use_tls=cfg.use_tls,
        sender_as_actor=(True if cfg.sender_as_actor is None else cfg.sender_as_actor),
        has_password=bool(cfg.smtp_password_enc),
    )


@router.get("/email", response_model=EmailSettingsRead)
def get_email(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    cfg = session.exec(select(EmailSettings)).first()
    if not cfg:
        cfg = EmailSettings()
        session.add(cfg); session.commit(); session.refresh(cfg)
    return _email_read(cfg)


@router.put("/email", response_model=EmailSettingsRead)
def update_email(
    data: EmailSettingsSchema,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.crypto import encrypt
    cfg = session.exec(select(EmailSettings)).first()
    if not cfg:
        cfg = EmailSettings()

    cfg.enabled      = data.enabled
    cfg.smtp_host    = data.smtp_host
    cfg.smtp_port    = data.smtp_port
    cfg.smtp_user    = data.smtp_user
    cfg.from_address = data.from_address
    cfg.to_address   = data.to_address
    cfg.use_tls      = data.use_tls
    cfg.sender_as_actor = data.sender_as_actor
    if data.smtp_password is not None:
        cfg.smtp_password_enc = encrypt(data.smtp_password) if data.smtp_password else ""

    session.add(cfg); session.commit(); session.refresh(cfg)
    return _email_read(cfg)


@router.post("/email/test")
def test_email(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.email_alerts import _send
    cfg = session.exec(select(EmailSettings)).first()
    if not cfg or not cfg.from_address:
        return {"ok": False, "error": "Brak adresu nadawcy (From) — uzupełnij i zapisz ustawienia."}
    # Wyślij na wskazany adres CC (żeby było gdzie sprawdzić dostarczenie),
    # a gdy nieustawiony — na adres nadawcy. `raise_errors=True`, żeby test
    # pokazał PRAWDZIWY błąd SMTP zamiast po cichu zwracać „ok".
    target = (cfg.to_address or "").strip() or cfg.from_address
    try:
        _send(target, "[SZUP] Test połączenia SMTP",
              "Wiadomość testowa z systemu SZUP. Jeśli ją widzisz — konfiguracja SMTP działa.",
              raise_errors=True)
        return {"ok": True, "sent_to": target}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# LDAP
# ---------------------------------------------------------------------------

class LdapSettingsSchema(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 389
    use_ssl: bool = False
    base_dn: str = ""
    bind_dn: str = ""
    bind_password: Optional[str] = None
    user_search_base: str = ""
    user_filter: str = "(sAMAccountName={username})"
    sso_enabled: bool = False
    sso_auto: bool = False


class LdapSettingsRead(BaseModel):
    id: Optional[int]
    enabled: bool
    host: str
    port: int
    use_ssl: bool
    base_dn: str
    bind_dn: str
    user_search_base: str
    user_filter: str
    has_password: bool
    sso_enabled: bool = False
    sso_auto: bool = False


def _ldap_read(cfg: LdapSettings) -> "LdapSettingsRead":
    return LdapSettingsRead(
        id=cfg.id, enabled=cfg.enabled, host=cfg.host, port=cfg.port,
        use_ssl=cfg.use_ssl, base_dn=cfg.base_dn, bind_dn=cfg.bind_dn,
        user_search_base=cfg.user_search_base, user_filter=cfg.user_filter,
        has_password=bool(cfg.bind_password_enc),
        sso_enabled=bool(getattr(cfg, "sso_enabled", False)),
        sso_auto=bool(getattr(cfg, "sso_auto", False)),
    )


# ---------------------------------------------------------------------------
# Szablony powiadomień e-mail (treść konfigurowalna z makrami)
# ---------------------------------------------------------------------------

class NotificationTemplateIn(BaseModel):
    subject: str = ""
    body: str = ""
    enabled: bool = True


class NotificationTemplateOut(BaseModel):
    event_key: str
    label: str
    description: str
    macros: list[str]
    subject: str
    body: str
    enabled: bool
    is_custom: bool          # czy nadpisany (różny od domyślnego)
    default_subject: str
    default_body: str


def _tpl_out(key: str, d: dict, row: Optional[NotificationTemplate]) -> NotificationTemplateOut:
    return NotificationTemplateOut(
        event_key=key,
        label=d.get("label", key),
        description=d.get("description", ""),
        macros=d.get("macros", []),
        subject=(row.subject if (row and (row.subject or "").strip()) else d.get("subject", "")),
        body=(row.body if (row and (row.body or "").strip()) else d.get("body", "")),
        enabled=(bool(row.enabled) if row else True),
        is_custom=bool(row),
        default_subject=d.get("subject", ""),
        default_body=d.get("body", ""),
    )


@router.get("/notifications", response_model=list[NotificationTemplateOut])
def list_notification_templates(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.notifications import EVENTS
    rows = {r.event_key: r for r in session.exec(select(NotificationTemplate)).all()}
    return [_tpl_out(key, d, rows.get(key)) for key, d in EVENTS.items()]


@router.put("/notifications/{event_key}", response_model=NotificationTemplateOut)
def save_notification_template(
    event_key: str,
    data: NotificationTemplateIn,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.notifications import EVENTS
    d = EVENTS.get(event_key)
    if not d:
        raise HTTPException(404, "Nieznane zdarzenie powiadomienia.")
    row = session.get(NotificationTemplate, event_key) or NotificationTemplate(event_key=event_key)
    row.subject = (data.subject or "").strip()
    row.body = data.body or ""
    row.enabled = bool(data.enabled)
    row.updated_at = datetime.utcnow()
    row.updated_by_user_id = current_user.id
    session.add(row); session.commit(); session.refresh(row)
    return _tpl_out(event_key, d, row)


@router.delete("/notifications/{event_key}", response_model=NotificationTemplateOut)
def reset_notification_template(
    event_key: str,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Przywróć domyślną treść (usuń nadpisanie)."""
    from services.notifications import EVENTS
    d = EVENTS.get(event_key)
    if not d:
        raise HTTPException(404, "Nieznane zdarzenie powiadomienia.")
    row = session.get(NotificationTemplate, event_key)
    if row:
        session.delete(row); session.commit()
    return _tpl_out(event_key, d, None)


@router.post("/notifications/{event_key}/test")
def test_notification_template(
    event_key: str,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Wyślij podgląd powiadomienia (na przykładowych danych) na adres
    zalogowanego administratora, żeby ocenić wygląd treści."""
    from services.notifications import EVENTS, render
    if event_key not in EVENTS:
        raise HTTPException(404, "Nieznane zdarzenie powiadomienia.")
    to = (current_user.email or "").strip()
    if not to:
        raise HTTPException(400, "Twoje konto nie ma adresu e-mail — ustaw go, aby wysłać test.")
    sample = {
        "request_id": 123, "worker_name": "Jan Testowy",
        "dept_name": "INF", "unit_name": "UM",
        "created_by": "Kadry", "selector_name": "Kierownik INF",
        "manager_name": "Naczelnik", "comment": "(przykładowy powód)",
        "what": "nadanie uprawnień", "applicant": "kierownik@wods.pl",
        "applicant_line": "Wnioskodawca: kierownik@wods.pl\n",
        "stage_label": "Akceptacja kierownika", "action_hint": "Zatwierdź albo odrzuć wniosek.",
        "denied_block": "", "denied_suffix": "",
    }
    subject, body, _enabled = render(event_key, sample)
    from services.email_alerts import _send
    try:
        _send(to, f"[TEST] {subject}", body, raise_errors=True)
    except Exception as exc:
        raise HTTPException(400, f"Nie udało się wysłać testu: {exc}")
    return {"ok": True, "sent_to": to}


@router.get("/ldap", response_model=LdapSettingsRead)
def get_ldap(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    cfg = session.exec(select(LdapSettings)).first()
    if not cfg:
        cfg = LdapSettings()
        session.add(cfg); session.commit(); session.refresh(cfg)
    return _ldap_read(cfg)


@router.put("/ldap", response_model=LdapSettingsRead)
def update_ldap(
    data: LdapSettingsSchema,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.crypto import encrypt
    cfg = session.exec(select(LdapSettings)).first()
    if not cfg:
        cfg = LdapSettings()

    cfg.enabled          = data.enabled
    cfg.host             = data.host
    cfg.port             = data.port
    cfg.use_ssl          = data.use_ssl
    cfg.base_dn          = data.base_dn
    cfg.bind_dn          = data.bind_dn
    cfg.user_search_base = data.user_search_base
    cfg.user_filter      = data.user_filter
    cfg.sso_enabled      = data.sso_enabled
    cfg.sso_auto         = data.sso_auto
    if data.bind_password is not None:
        cfg.bind_password_enc = encrypt(data.bind_password) if data.bind_password else None

    session.add(cfg); session.commit(); session.refresh(cfg)
    return _ldap_read(cfg)


def _effective_helpdesk(cfg: Optional[AppSettings]) -> str:
    """Adres helpdesku faktycznie używany: z ustawień, a gdy pusty — domyślny."""
    from services.email_alerts import HELPDESK_EMAIL
    val = (cfg.helpdesk_email or "").strip() if cfg else ""
    return val or HELPDESK_EMAIL


class AppSettingsSchema(BaseModel):
    test_mode: bool = False
    helpdesk_email: Optional[str] = None
    # Puste/pominięte → nie zmieniaj treści oświadczenia (albo zostaw domyślną).
    declaration_text: Optional[str] = None
    # Harmonogram nocnej migawki (pominięte → bez zmian).
    snapshot_enabled: Optional[bool] = None
    snapshot_hour: Optional[int] = None
    snapshot_minute: Optional[int] = None


class AppSettingsRead(BaseModel):
    id: Optional[int]
    test_mode: bool
    helpdesk_email: Optional[str] = None
    # Adres używany faktycznie, gdy pole wyżej jest puste (domyślny z konfiguracji).
    helpdesk_email_effective: Optional[str] = None
    # Treść oświadczenia — własna z ustawień albo domyślna, gdy pole puste.
    declaration_text: str = ""
    declaration_is_default: bool = True
    # Harmonogram migawek.
    snapshot_enabled: bool = True
    snapshot_hour: int = 23
    snapshot_minute: int = 50
    # Twardy wyłącznik środowiskowy (env) — gdy True, harmonogram nie działa
    # niezależnie od ustawień; front pokazuje wtedy ostrzeżenie.
    snapshot_env_disabled: bool = False


def _app_read(cfg: AppSettings, session: Session) -> "AppSettingsRead":
    import os
    own = (cfg.declaration_text or "").strip()
    return AppSettingsRead(
        id=cfg.id, test_mode=bool(cfg.test_mode),
        helpdesk_email=cfg.helpdesk_email,
        helpdesk_email_effective=_effective_helpdesk(cfg),
        declaration_text=own or DEFAULT_DECLARATION_TEXT,
        declaration_is_default=not own,
        snapshot_enabled=bool(cfg.snapshot_enabled) if cfg.snapshot_enabled is not None else True,
        snapshot_hour=cfg.snapshot_hour if cfg.snapshot_hour is not None else 23,
        snapshot_minute=cfg.snapshot_minute if cfg.snapshot_minute is not None else 50,
        snapshot_env_disabled=(os.getenv("SZUP_SNAPSHOTS", "1") == "0"),
    )


@router.get("/app", response_model=AppSettingsRead)
def get_app_settings(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    cfg = session.exec(select(AppSettings)).first()
    if not cfg:
        cfg = AppSettings()
        session.add(cfg); session.commit(); session.refresh(cfg)
    return _app_read(cfg, session)


@router.put("/app", response_model=AppSettingsRead)
def update_app_settings(
    data: AppSettingsSchema,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from services.security_events import emit as emit_security_event

    cfg = session.exec(select(AppSettings)).first()
    if not cfg:
        cfg = AppSettings()

    prev = bool(cfg.test_mode)
    cfg.test_mode = bool(data.test_mode)
    # Puste pole = wróć do adresu domyślnego (z konfiguracji wdrożenia).
    cfg.helpdesk_email = (data.helpdesk_email or "").strip() or None
    if data.declaration_text is not None:
        # Puste = wróć do treści domyślnej. Zmiana NIE działa wstecz —
        # już złożone oświadczenia mają własną, zamrożoną kopię.
        cfg.declaration_text = (data.declaration_text or "").strip() or None
    # Harmonogram migawek — zapisz i wybudź wątek, żeby zadziałało bez restartu.
    snapshot_changed = False
    if data.snapshot_enabled is not None:
        cfg.snapshot_enabled = bool(data.snapshot_enabled); snapshot_changed = True
    if data.snapshot_hour is not None:
        cfg.snapshot_hour = min(23, max(0, int(data.snapshot_hour))); snapshot_changed = True
    if data.snapshot_minute is not None:
        cfg.snapshot_minute = min(59, max(0, int(data.snapshot_minute))); snapshot_changed = True
    session.add(cfg); session.commit(); session.refresh(cfg)

    if snapshot_changed:
        try:
            from services import scheduler
            scheduler.reconfigure()
        except Exception:
            pass

    if prev != cfg.test_mode:
        # Włączenie/wyłączenie trybu testowego ZAWSZE leci jako security event — kluczowa operacja.
        emit_security_event(
            session,
            event_type="settings.test_mode",
            source="settings",
            severity=SecuritySeverity.critical if cfg.test_mode else SecuritySeverity.high,
            summary=(
                f"Tryb testowy {'WŁĄCZONY' if cfg.test_mode else 'wyłączony'} "
                f"przez {current_user.username}"
            ),
            details={"enabled": cfg.test_mode},
            user_id=current_user.id,
        )

    return _app_read(cfg, session)


@router.post("/ldap/test")
def test_ldap(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    from ldap3 import Server, Connection, ALL
    from services.crypto import decrypt

    cfg = session.exec(select(LdapSettings)).first()
    if not cfg or not cfg.host:
        return {"ok": False, "error": "Brak konfiguracji LDAP"}
    try:
        bind_password = decrypt(cfg.bind_password_enc) if cfg.bind_password_enc else ""
        server = Server(cfg.host, port=cfg.port, use_ssl=cfg.use_ssl, get_info=ALL)
        with Connection(server, user=cfg.bind_dn, password=bind_password, auto_bind=True):
            return {"ok": True, "message": f"Połączono z {cfg.host}:{cfg.port}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Reset do ustawień fabrycznych — WYŁĄCZNIE superadmin
# ---------------------------------------------------------------------------

class FactoryResetRequest(BaseModel):
    password: str                    # potwierdzenie hasłem wykonującego
    confirm: str                     # musi być dokładnie "RESET"
    wipe_requests: bool = True       # wnioski + pozycje + instancje obiegu
    wipe_structure: bool = True      # jednostki, wydziały, zastępcy, przypisania HR
    wipe_users: bool = True          # wszyscy użytkownicy PRÓCZ wykonującego
    wipe_software: bool = False      # rejestr oprogramowania (systemy + uprawnienia)
    wipe_audit: bool = False         # audit log + zdarzenia bezpieczeństwa


class FactoryResetResult(BaseModel):
    deleted: dict[str, int]
    details: list[str]


@router.post("/factory-reset", response_model=FactoryResetResult)
def factory_reset(
    data: FactoryResetRequest,
    request: Request,
    current_user: User = Depends(require_superadmin),
    session: Session = Depends(get_session),
):
    """Przywraca system do stanu „fabrycznego".

    Operacja NIEODWRACALNA — dostępna wyłącznie dla superadmina i wymagająca
    potwierdzenia hasłem oraz frazą „RESET". Konto wykonującego jest ZAWSZE
    zachowywane (inaczej nikt nie mógłby się zalogować po resecie).
    Domyślne szablony obiegu i typy wniosków odtworzy `init_db()` przy starcie.
    """
    from sqlalchemy import text
    from models import AuthType
    from services.auth_service import verify_password
    from services.audit import record_event, request_meta
    from services.security_events import emit as emit_security_event

    if data.confirm.strip() != "RESET":
        raise HTTPException(400, 'Potwierdź operację wpisując dokładnie: RESET')

    # Weryfikacja tożsamości wykonującego — hasłem lokalnym albo przez AD.
    ok = False
    if current_user.auth_type == AuthType.ldap:
        from services.ldap_service import authenticate_ldap
        cfg = session.exec(select(LdapSettings)).first()
        if cfg and cfg.enabled:
            try:
                ok = bool(authenticate_ldap(cfg, current_user.username, data.password))
            except Exception:
                ok = False
    else:
        ok = bool(current_user.password_hash) and verify_password(
            data.password, current_user.password_hash)
    if not ok:
        raise HTTPException(403, "Nieprawidłowe hasło — reset przerwany")

    meta = request_meta(request)
    deleted: dict[str, int] = {}
    details: list[str] = []

    def _count(table: str) -> int:
        try:
            row = session.exec(text(f'SELECT COUNT(*) FROM "{table}"')).first()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def _wipe(table: str, where: str = "") -> None:
        sql = f'DELETE FROM "{table}"' + (f" WHERE {where}" if where else "")
        before = _count(table)
        try:
            session.exec(text(sql))
            after = _count(table)
            n = max(0, before - after)
            if n:
                deleted[table] = deleted.get(table, 0) + n
                details.append(f"{table}: usunięto {n}")
        except Exception as exc:
            details.append(f"⚠ {table}: {exc}")

    # Rozwiąż powiązania krzyżowe TYLKO dla tego, co faktycznie kasujemy.
    # KRYTYCZNE: te UPDATE-y muszą być bramkowane flagami wipe_*. Odpalane
    # bezwarunkowo (dawny błąd) odpinały całą strukturę — kierowników, hierarchię
    # wydziałów i przypisania pracowników do komórek — nawet przy samym
    # czyszczeniu wniosków (gdy struktura miała zostać nietknięta).
    cid = int(current_user.id)
    cross_updates: list[str] = []
    if data.wipe_users:
        # Kasujemy użytkowników (prócz wykonującego) — zdejmij referencje DO nich
        # z rekordów, które przetrwają. Managerstwa wykonującego nie ruszamy.
        cross_updates.append(
            f'UPDATE "department" SET manager_user_id = NULL WHERE manager_user_id <> {cid}')
        cross_updates.append(
            f'UPDATE "accessrequest" SET assigned_to_user_id = NULL WHERE assigned_to_user_id <> {cid}')
    if data.wipe_structure:
        # Kasujemy wydziały/jednostki — zdejmij referencje DO nich.
        cross_updates.append('UPDATE "department" SET parent_dept_id = NULL')
        cross_updates.append('UPDATE "user" SET department_id = NULL')
    for stmt in cross_updates:
        try:
            session.exec(text(stmt))
        except Exception:
            pass

    # 1) Wnioski i obieg (dzieci → rodzice).
    if data.wipe_requests:
        _wipe("namechangerequest")
        _wipe("permissionsnapshot")
        _wipe("permissiondeclaration")
        _wipe("workflowstep")
        _wipe("workflowinstance")
        _wipe("requestitem")
        _wipe("accessrequest")

    # 2) Rejestr oprogramowania.
    if data.wipe_software:
        # RequestItem wskazuje na systemy/uprawnienia — wymagamy czystki wniosków.
        if not data.wipe_requests:
            raise HTTPException(400,
                "Czyszczenie rejestru oprogramowania wymaga też wyczyszczenia wniosków.")
        _wipe("systempermission")
        _wipe("permissionsystemunit")
        _wipe("permissionsystem")
        # Słownik dostawców — umowy przed dostawcami (FK).
        _wipe("vendorcontract")
        _wipe("softwarevendor")

    # 3) Użytkownicy — PRÓCZ wykonującego (i bez naruszania wniosków, które
    #    mogły zostać, gdy wipe_requests=False).
    if data.wipe_users:
        if not data.wipe_requests:
            raise HTTPException(400,
                "Czyszczenie użytkowników wymaga też wyczyszczenia wniosków "
                "(wnioski wskazują na autorów i pracowników).")
        _wipe("userunit", f"user_id <> {int(current_user.id)}")
        _wipe("departmentdeputy", f"user_id <> {int(current_user.id)}")
        _wipe("revokedtoken")
        _wipe("user", f"id <> {int(current_user.id)}")

    # 4) Struktura organizacyjna.
    if data.wipe_structure:
        _wipe("departmentdeputy")
        _wipe("userunit")
        _wipe("department")
        _wipe("unit")

    # 5) Audyt / zdarzenia bezpieczeństwa (append-only triggery trzeba zdjąć;
    #    init_db() odtworzy je przy następnym starcie backendu).
    if data.wipe_audit:
        for trg in ("auditlog_no_update", "auditlog_no_delete"):
            try:
                session.exec(text(f'DROP TRIGGER IF EXISTS "{trg}"'))
            except Exception:
                pass
        _wipe("auditlog")
        _wipe("securityevent")

    session.commit()

    # Odtwórz triggery audytu od razu, żeby nie czekać na restart.
    if data.wipe_audit:
        try:
            from database import _install_auditlog_triggers
            _install_auditlog_triggers()
        except Exception:
            pass

    # Ślad operacji (po czystce, żeby nie został skasowany).
    try:
        record_event(session, action="settings.factory_reset",
                     user_id=current_user.id, username=current_user.username,
                     ip=meta["ip"], user_agent=meta["user_agent"],
                     details={"deleted": deleted})
        emit_security_event(
            session, event_type="settings.factory_reset", source="settings",
            severity=SecuritySeverity.critical,
            summary=f"PRZYWRÓCENIE USTAWIEŃ FABRYCZNYCH przez {current_user.username}",
            details={"deleted": deleted}, user_id=current_user.id, ip=meta["ip"],
        )
    except Exception:
        pass

    if not details:
        details.append("Brak danych do usunięcia — system był już pusty.")
    return FactoryResetResult(deleted=deleted, details=details)


# ---------------------------------------------------------------------------
# v3.1 — Lista kontrolna konfiguracji + sygnały jakości danych (pulpit admina)
# ---------------------------------------------------------------------------

@router.get("/health")
def config_health(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Czy system jest gotowy do pracy i co wymaga uporządkowania.

    checks — elementy konfiguracji (ok / brak), issues — liczniki problemów
    w danych. `link` to trasa frontendu, pod którą admin to naprawi.
    """
    import json as _json
    from datetime import timedelta
    from models import (Unit, Department, RequestType, WorkflowTemplate,
                        WorkflowInstance, WorkflowInstanceStatus, SecurityEvent,
                        parse_roles)
    from sqlalchemy import func
    from models import WorkflowStep
    from services.permissions import effective_manager_dept
    from services.email_alerts import HELPDESK_EMAIL

    ldap = session.exec(select(LdapSettings)).first()
    email = session.exec(select(EmailSettings)).first()
    app = session.exec(select(AppSettings)).first()
    units = session.exec(select(Unit)).all()
    depts = session.exec(select(Department)).all()
    active_unit_ids = {u.id for u in units if u.is_active}
    inactive_user_ids = set(session.exec(
        select(User.id).where(User.is_active == False)  # noqa: E712
    ).all())

    active_depts = [d for d in depts if d.is_active and d.unit_id in active_unit_ids]
    # Komórka bez kierownika jest problemem tylko wtedy, gdy NIKT wyżej za nią
    # nie odpowiada — inaczej obieg przejmuje najbliższy kierownik wyżej.
    # Bez BEZPOŚREDNIEGO kierownika (to pokazuje filtr /units?filter=no_manager).
    no_direct_manager = [d for d in active_depts
                         if getattr(d, "kind", "department") != "standalone" and not d.manager_user_id]
    no_manager = [d for d in no_direct_manager if effective_manager_dept(session, d) is None]
    inactive_mgr = [d for d in active_depts
                    if d.manager_user_id and d.manager_user_id in inactive_user_ids]

    templates = {t.id: t for t in session.exec(select(WorkflowTemplate)).all()}
    active_tpl = [t for t in templates.values() if t.is_active]

    def _has_it_step(t) -> bool:
        try:
            return any(n.get("type") == "it_execute"
                       for n in (_json.loads(t.graph_json) or {}).get("nodes", []))
        except Exception:
            return False

    req_types_ok = [rt for rt in session.exec(select(RequestType)).all()
                    if rt.is_active and templates.get(rt.workflow_template_id)
                    and templates[rt.workflow_template_id].is_active]

    helpdesk = (app.helpdesk_email or "").strip() if app else ""

    checks = [
        {"key": "ldap", "label": "AD/LDAP skonfigurowane",
         "ok": bool(ldap and ldap.enabled and (ldap.host or "").strip()),
         "detail": (ldap.host if ldap and ldap.host else "Brak serwera lub logowanie AD wyłączone"),
         "link": "/settings"},
        {"key": "structure", "label": "Struktura zaimportowana",
         "ok": bool(units) and bool(depts),
         "detail": f"Jednostek: {len(units)}, komórek: {len(depts)}",
         "link": "/units"},
        {"key": "managers", "label": "Kierownicy przypisani",
         "ok": not no_manager,
         "detail": ("Każda komórka ma kierownika (własnego lub wyżej w strukturze)" if not no_manager
                    else f"Komórek bez żadnego kierownika w strukturze: {len(no_manager)}"),
         "link": "/units?filter=no_manager"},
        {"key": "request_types", "label": "Typy wniosków",
         "ok": bool(req_types_ok),
         "detail": f"Aktywnych z aktywnym szablonem: {len(req_types_ok)}",
         "link": "/request-types"},
        {"key": "it_step", "label": "Szablon obiegu z krokiem IT",
         "ok": any(_has_it_step(t) for t in active_tpl),
         "detail": f"Aktywnych szablonów: {len(active_tpl)}",
         "link": "/workflow-templates"},
        {"key": "email", "label": "Powiadomienia e-mail",
         "ok": bool(email and email.enabled and (email.smtp_host or "").strip()),
         "detail": (email.smtp_host if email and email.smtp_host else "Brak serwera SMTP lub wyłączone"),
         "link": "/settings"},
        {"key": "helpdesk", "label": "Adres helpdesku IT",
         "ok": bool(helpdesk or HELPDESK_EMAIL),
         "detail": (f"{helpdesk} (ustawiony)" if helpdesk
                    else f"{HELPDESK_EMAIL} (domyślny z konfiguracji)"),
         "link": "/settings"},
    ]

    # Użytkownicy bez komórki — pomijamy nieaktywnych i konta czysto administracyjne.
    admin_only = {"admin", "superadmin"}
    no_dept = [roles for roles in session.exec(
        select(User.roles).where(User.is_active == True)  # noqa: E712
        .where(User.department_id == None)  # noqa: E711
    ).all() if not set(parse_roles(roles)) <= admin_only]

    # Wnioski czekające > 7 dni na bieżącym kroku — jedno zapytanie:
    # ostatni krok (max created_at) dla każdej aktywnej instancji obiegu.
    limit = datetime.utcnow() - timedelta(days=7)
    stale = 0
    for _iid, inst_created, last_step in session.exec(
        select(WorkflowInstance.id, WorkflowInstance.created_at, func.max(WorkflowStep.created_at))
        .join(WorkflowStep, WorkflowStep.instance_id == WorkflowInstance.id, isouter=True)
        .where(WorkflowInstance.status == WorkflowInstanceStatus.active)
        .group_by(WorkflowInstance.id)
    ).all():
        since = last_step or inst_created
        if since and since < limit:
            stale += 1

    open_sec = session.exec(
        select(func.count()).select_from(SecurityEvent)
        .where(SecurityEvent.resolved_at == None)  # noqa: E711
    ).one()

    issues = [
        {"key": "dept_no_manager", "label": "Komórki bez kierownika", "count": len(no_direct_manager),
         "link": "/units?filter=no_manager"},
        {"key": "users_no_dept", "label": "Użytkownicy bez komórki", "count": len(no_dept), "link": "/users"},
        {"key": "stale_requests", "label": "Wnioski czekające ponad 7 dni", "count": stale,
         # Admin nie ma dostępu do /requests (obsługują kierownicy i IT) — bez linku.
         "link": None},
        {"key": "inactive_managers", "label": "Nieaktywni kierownicy na stanowisku", "count": len(inactive_mgr), "link": "/units"},
        {"key": "security_open", "label": "Otwarte zdarzenia bezpieczeństwa", "count": open_sec, "link": "/security"},
    ]
    return {"checks": checks, "issues": issues}
