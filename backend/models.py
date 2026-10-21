"""
SQLModel models for SZUP — System Zarządzania Uprawnieniami.
"""
from __future__ import annotations

import enum
import json
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    superadmin = "superadmin"
    admin      = "admin"
    hr         = "hr"
    manager    = "manager"
    it_staff   = "it_staff"
    viewer     = "viewer"


# Priority order for primary_role()
ROLE_HIERARCHY = ["superadmin", "admin", "it_staff", "manager", "hr", "viewer"]
VALID_ROLES    = {r.value for r in UserRole}


def parse_roles(roles_json: Optional[str]) -> list[str]:
    """Deserialize roles JSON string → list of role strings."""
    if not roles_json:
        return ["viewer"]
    try:
        result = json.loads(roles_json)
        return [r for r in result if r in VALID_ROLES] or ["viewer"]
    except (json.JSONDecodeError, TypeError):
        return ["viewer"]


def roles_to_json(roles: list[str]) -> str:
    """Serialize list of role strings → JSON string stored in DB."""
    valid = [r for r in roles if r in VALID_ROLES]
    return json.dumps(valid or ["viewer"])


def has_role(user: "User", *role_values: str) -> bool:
    """True if user has ANY of the given roles."""
    user_roles = parse_roles(user.roles)
    return any(r in user_roles for r in role_values)


def primary_role(user: "User") -> str:
    """Return the highest-priority role the user holds."""
    user_roles = parse_roles(user.roles)
    for r in ROLE_HIERARCHY:
        if r in user_roles:
            return r
    return "viewer"


class AuthType(str, enum.Enum):
    local = "local"
    ldap  = "ldap"


class RequestStatus(str, enum.Enum):
    pending_selection = "pending_selection"   # tryb 2-stopniowy: kierownik wydziału wybiera uprawnienia
    pending_manager   = "pending_manager"     # oczekuje na akceptację (1-stopniowo: kierownik; 2-stopniowo: wyższego rzędu)
    pending_it        = "pending_it"
    completed         = "completed"
    rejected          = "rejected"


class SecuritySeverity(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    full_name: Optional[str] = None
    email: Optional[str] = None
    password_hash: Optional[str] = None
    # roles: JSON array string, e.g. '["manager","it_staff"]'
    roles: str = Field(default='["viewer"]')
    auth_type: AuthType = Field(default=AuthType.local)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    failed_login_count: int = Field(default=0)
    locked_until: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    must_change_password: bool = Field(default=False)
    tokens_valid_from: Optional[datetime] = None

    # AD binding
    department_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    ldap_dn: Optional[str] = Field(default=None, index=True)   # znormalizowany DN
    # Stanowisko (atrybut `title` z AD) — służy do podpowiadania/wykrywania
    # kierowników komórek (np. „Kierownik", „Dyrektor", „Naczelnik").
    title: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Organizacja
# ---------------------------------------------------------------------------

class Unit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    code: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ldap_dn: Optional[str] = Field(default=None, index=True)   # znormalizowany DN z AD
    # Kierownik CAŁEJ jednostki: widzi uprawnienia WSZYSTKICH pracowników
    # jednostki i może dla nich składać wnioski (podgląd + wnioskowanie).
    # Akceptacja/realizacja pozostaje przy kierownikach komórek i obiegu.
    manager_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)


class UserUnit(SQLModel, table=True):
    """Przypisanie użytkownika (HR) do jednostek, które obsługuje.

    Pracownik kadr widzi w formularzach (nowy pracownik / ustanie stosunku
    pracy) wyłącznie jednostki tu przypisane. Admin/superadmin widzi wszystkie.
    """
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", primary_key=True)


class Department(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id")
    parent_dept_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    name: str = Field(index=True)
    # Typ węzła struktury organizacyjnej:
    #   "department" — Wydział / Dział (domyślny, zgodny z istniejącymi danymi)
    #   "section"    — Referat (pod wydziałem)
    #   "standalone" — Samodzielne stanowisko (jednoosobowa komórka)
    # Enum przechowujemy jako VARCHAR żeby nie blokować przyszłych rozszerzeń.
    kind: str = Field(default="department")
    manager_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    is_active: bool = Field(default=True)
    # True → wnioski na ten wydział wymagają wyboru uprawnień przez kierownika
    # wydziału i osobnej akceptacji przez kierownika wydziału nadrzędnego (2-stopniowo).
    requires_higher_approval: bool = Field(default=False)
    # True → komórka KADROWA. Jej pracownicy mogą zgłaszać nowych pracowników
    # i ustania (rola HR z automatu, bez przydzielania roli per osoba).
    is_hr: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ldap_dn: Optional[str] = Field(default=None, index=True)   # znormalizowany DN z AD


# Dozwolone wartości pola Department.kind — walidowane w routerze.
DEPARTMENT_KINDS = ("department", "section", "standalone")


class DepartmentDeputy(SQLModel, table=True):
    """Zastępca kierownika komórki — dodatkowe osoby (obok głównego
    manager_user_id) z pełnymi uprawnieniami kierownika tej komórki:
    wybierają uprawnienia, akceptują wnioski, widzą pracowników.

    role_label to swobodny opis funkcji (np. „Zastępca", „Koordynator IT",
    „Sekretariat"). Nie zmienia uprawnień — tylko dla czytelności w UI.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    department_id: int = Field(foreign_key="department.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role_label: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Słownik systemów i uprawnień
# ---------------------------------------------------------------------------

class PermissionSystem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    is_active: bool = Field(default=True)
    # True → system „bez dodatkowych uprawnień": wystarczy sam dostęp.
    # Na poziomie bazy i tak trzymamy jedno auto-generowane SystemPermission
    # o nazwie „Dostęp" (tworzone/usuwane przez router), dzięki czemu reszta
    # flow wniosków (RequestItem.permission_id) jest bez zmian.
    access_only: bool = Field(default=False)
    # True → oprogramowanie dostępne we wszystkich jednostkach organizacyjnych.
    # False → zawężone do jednostek wpisanych w tabeli PermissionSystemUnit.
    all_units: bool = Field(default=True)
    # Pozycja na liście wniosku. NULL = bez numeru — takie programy lądują ZA
    # ponumerowanymi, alfabetycznie. Numery są unikalne (walidacja w routerze).
    display_order: Optional[int] = Field(default=None, index=True)
    # True → pozycja zaznaczona z góry na wniosku (np. poczta, portal, EZD).
    # Wnioskodawca może ją odznaczyć; pola wymagane i tak musi uzupełnić sam.
    default_checked: bool = Field(default=False)
    # Dostawca/producent ze słownika — do kogo dzwonić przy awarii.
    vendor_id: Optional[int] = Field(default=None, foreign_key="softwarevendor.id", index=True)
    # True → na wniosku można poprosić o „Uprawnienia administratora" tego
    # systemu (super uprawnienia). Domyślnie dostępne dla KAŻDEGO programu;
    # router utrzymuje dla nich syntetyczne SystemPermission.
    admin_option: bool = Field(default=True)
    # True → program z listą poduprawnień MUSI mieć wybrany zakres: na wniosku
    # jest domyślnie „zwinięty/wyszarzony", trzeba zaznaczyć sam program, a po
    # zaznaczeniu wybrać co najmniej jedno uprawnienie. Egzekwowane w UI.
    require_scope: bool = Field(default=False)
    # Pola własne (metadane) tego oprogramowania — JSON: lista obiektów
    # {"label": nazwa pola, "description": definicja/opis co wpisać, "value": wartość}.
    # Pozwala dopisać dowolne dane (nr umowy, producent, data wygaśnięcia licencji…).
    custom_fields: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SoftwareVendor(SQLModel, table=True):
    """Dostawca / producent oprogramowania — słownik.

    Status umowy serwisowej NIE jest tu trzymany jako flaga — wyliczamy go
    z dat w `VendorContract`, żeby nie mógł rozjechać się z rzeczywistością
    (patrz `_vendor_status` w routers/vendors.py).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    nip: Optional[str] = None
    address: Optional[str] = None            # ulica i numer
    postal_code: Optional[str] = None
    city: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VendorContract(SQLModel, table=True):
    """Umowa serwisowa dostawcy. Jeden dostawca może mieć ich wiele
    (kolejne lata, różne zakresy) — status liczymy z najdalszej daty końca.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    vendor_id: int = Field(foreign_key="softwarevendor.id", index=True)
    contract_number: Optional[str] = None
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    # Data końca jest wymagana — bez niej nie da się ocenić, czy umowa trwa.
    # Dzień końcowy liczy się WŁĄCZNIE (porównanie po .date()).
    valid_to: datetime
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PermissionSystemUnit(SQLModel, table=True):
    """Zakres oprogramowania per jednostka organizacyjna (M:N)."""
    system_id: int = Field(foreign_key="permissionsystem.id", primary_key=True)
    unit_id:   int = Field(foreign_key="unit.id", primary_key=True)


class SystemPermission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="permissionsystem.id")
    permission_name: str
    description: Optional[str] = None
    # Grupa uprawnień w obrębie programu, np. „Rejestry opłat". Jeden program
    # może mieć kilka grup (kilka zaimportowanych list). Puste = pozycja
    # dodana ręcznie, poza importem.
    group_name: Optional[str] = Field(default=None, index=True)
    # Kolejność GRUPY na liście (wszystkie pozycje jednej grupy mają tę samą
    # wartość). Puste = grupa bez ustawionej kolejności → ląduje alfabetycznie
    # za grupami uporządkowanymi. Ustawiane przyciskami ↑/↓ w rejestrze.
    group_order: Optional[int] = Field(default=None, index=True)
    # Podgrupa WEWNĄTRZ grupy, np. grupa „Rejestry opłat" → podgrupa „Odpady".
    # Puste = pozycja leży bezpośrednio w grupie (bez podgrupy). Hierarchia na
    # wniosku i w rejestrze: Program → Grupa → Podgrupa → Uprawnienie.
    subgroup_name: Optional[str] = Field(default=None, index=True)
    # Kolejność PODGRUPY w obrębie grupy (analogicznie do group_order).
    subgroup_order: Optional[int] = Field(default=None, index=True)
    # Symbol/kod z systemu źródłowego (np. „ADA") — klucz dopasowania przy
    # ponownym imporcie, gdy nazwa opisowa się zmieni.
    external_code: Optional[str] = None
    # Pozycja wycofana ze źródła. NIE kasujemy jej, bo `_effective_permissions`
    # rozwiązuje uprawnienia po id — skasowanie zerwałoby ewidencję osób,
    # które je posiadają. Wygaszone znikają tylko z wyboru na nowym wniosku.
    is_active: bool = Field(default=True)
    # Kontrolka doprecyzowująca uprawnienie na wniosku:
    #   none        — zwykły checkbox (tak wygląda wszystko z importu),
    #   text/textarea — wnioskodawca wpisuje treść (np. nazwy rejestrów),
    #   radio/select  — jedna wartość z listy (widoczna / zwinięta),
    #   multiselect   — dowolnie wiele wartości z listy.
    # Kontrolka jest cechą POJEDYNCZEGO uprawnienia, nie całego programu —
    # dzięki temu pozycje z importu i ręczne żyją obok siebie na jednej liście.
    input_type: str = Field(default="none")
    options: Optional[str] = None          # JSON: lista opcji dla radio/select/multiselect
    input_required: bool = Field(default=False)
    # Podpowiedź przy polu — co dokładnie wnioskujący ma wpisać/wybrać. Pokazuje
    # się po zaznaczeniu uprawnienia (np. „Podaj login AD, np. jan.kowalski").
    input_prompt: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Wnioski o uprawnienia
# ---------------------------------------------------------------------------

class AccessRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    worker_name: str
    worker_email: Optional[str] = None
    worker_phone: Optional[str] = None
    worker_position: Optional[str] = None
    # Data zatrudnienia od (nowy pracownik) / data ostatniego dnia pracy (ustanie).
    employment_from: Optional[date] = None
    work_until: Optional[date] = None
    # Dowiązanie do konta pracownika (opcjonalne — zachowujemy kompatybilność
    # z istniejącymi rekordami HR, gdzie pracownik jest tylko wpisem tekstowym).
    # Używane do agregacji uprawnień w widoku „Moja struktura".
    worker_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    unit_id: int = Field(foreign_key="unit.id")
    department_id: int = Field(foreign_key="department.id")

    # Kierunek wniosku: "grant" (nadanie uprawnień — nowy pracownik) lub
    # "revoke" (odebranie uprawnień — ustanie stosunku pracy). Ten sam obieg
    # (kierownik → IT), inne znaczenie kroku wyboru: przy revoke kierownik
    # wybiera z BIEŻĄCYCH uprawnień pracownika te do odebrania.
    kind: str = Field(default="grant", index=True)

    # Typ wniosku wybierany przy tworzeniu — determinuje szablon obiegu.
    # Opcjonalny na poziomie bazy dla łatwej migracji istniejących baz;
    # router wymusza obecność przy tworzeniu nowego wniosku.
    request_type_id: Optional[int] = Field(default=None, foreign_key="requesttype.id", index=True)

    status: RequestStatus = Field(default=RequestStatus.pending_manager, index=True)

    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_by_name: Optional[str] = None     # snapshot na wypadek usunięcia konta

    approved_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    completed_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    selector_by_id: Optional[int] = Field(default=None, foreign_key="user.id")

    # Kto z IT zajmuje się realizacją (przekazanie przez kierownika IT).
    # Oznaczenie INFORMACYJNE — nie blokuje realizacji przez innych z IT.
    assigned_to_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    manager_comment: Optional[str] = None
    it_comment: Optional[str] = None
    selector_comment: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    selected_at: Optional[datetime] = None


class RequestItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="accessrequest.id")
    system_id: int = Field(foreign_key="permissionsystem.id")
    permission_id: int = Field(foreign_key="systempermission.id")
    # Kierunek POZYCJI: "grant" (nadać) albo "revoke" (odebrać). Dzięki temu
    # jeden wniosek o zmianę (kind="change") może jednocześnie nadawać jedne
    # uprawnienia i odbierać inne — model „stanu docelowego".
    # Dla starych rekordów fallback na kierunek całego wniosku.
    kind: str = Field(default="grant", index=True)
    # Wartości pól dodatkowych zdefiniowanych przy oprogramowaniu (JSON:
    # [{"label": "...", "value": "..."}]). Wypełnia je kierownik w kroku
    # „Wybór uprawnień" — definiują poziom/zakres nadawanego dostępu.
    custom_values: Optional[str] = None
    # Ustawiane TYLKO dla pozycji dołożonych przez IT na etapie realizacji
    # (np. moduł wymaga zależnego uprawnienia). NULL = pozycja pochodzi
    # z wniosku kierownika. Bez tego pola dodatki IT byłyby w interfejsie
    # przypisane kierownikowi (heurystyka `requested_by_name`).
    added_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # Odmowa nadania KONKRETNEJ pozycji — zgłasza kierownik nadrzędny (obieg
    # 2-stopniowy) albo IT przy realizacji. Pozycja zostaje na wniośku (ślad +
    # komentarz), ale NIE wchodzi do efektywnych uprawnień pracownika.
    denied: bool = Field(default=False, index=True)
    deny_comment: Optional[str] = None
    denied_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    denied_at: Optional[datetime] = None
    # Realizacja POJEDYNCZEJ pozycji przez IT — do pracy etapowej (częściowej).
    # IT odhacza wykonane pozycje na bieżąco (zapis w bazie) PRZED zamknięciem
    # całego wniosku. Wyklucza się z `denied` (odmowa vs zrobione).
    fulfilled: bool = Field(default=False, index=True)
    fulfilled_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    fulfilled_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Ustawienia SMTP (jeden rekord)
# ---------------------------------------------------------------------------

class EmailSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    enabled: bool = Field(default=False)
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password_enc: str = Field(default="")
    from_address: str = Field(default="")
    # Domyślny odbiorca kopii (CC) powiadomień — opcjonalny.
    to_address: str = Field(default="")
    use_tls: bool = Field(default=True)
    # Prezentuj powiadomienie jako wysłane przez osobę, która wywołała zdarzenie
    # (nagłówek From = adres aktora). Koperta SMTP zostaje uwierzytelniona.
    sender_as_actor: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Szablony powiadomień — edytowalna treść (temat + treść) z makrami.
# Jeden rekord na typ zdarzenia (event_key). Brak rekordu = używany domyślny
# szablon z kodu (services/notifications.py).
# ---------------------------------------------------------------------------

class NotificationTemplate(SQLModel, table=True):
    # Klucz zdarzenia, np. "request_completed" — zgodny z rejestrem EVENTS.
    event_key: str = Field(primary_key=True)
    subject: str = Field(default="")
    body: str = Field(default="")
    enabled: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


# ---------------------------------------------------------------------------
# LDAP / AD (jeden rekord)
# ---------------------------------------------------------------------------

class AppSettings(SQLModel, table=True):
    """Ustawienia aplikacyjne (jeden rekord)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Tryb testowy: logowanie samym loginem (bez hasła). TYLKO do testów workflow!
    test_mode: bool = Field(default=False)
    # Skrzynka helpdesku IT — tam trafia zgłoszenie, gdy wniosek wchodzi
    # w krok realizacji. Puste → wartość domyślna z SZUP_HELPDESK_EMAIL.
    helpdesk_email: Optional[str] = Field(default=None)
    # Treść oświadczenia wnioskującego, podpisywanego w chwili skierowania
    # wniosku do realizacji IT. Edytowalna w Ustawieniach; zmiana NIE działa
    # wstecz — każde złożone oświadczenie zamraża własną kopię treści.
    # Puste → DEFAULT_DECLARATION_TEXT z routers/settings.py.
    declaration_text: Optional[str] = Field(default=None)
    # Harmonogram nocnej migawki uprawnień (czas LOKALNY). Edytowalny przez
    # superadmina; zmiana działa bez restartu (harmonogram czyta bazę).
    snapshot_enabled: bool = Field(default=True)
    snapshot_hour: int = Field(default=23)
    snapshot_minute: int = Field(default=50)


class LdapSettings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    enabled: bool = Field(default=False)
    host: str = Field(default="")
    port: int = Field(default=389)
    use_ssl: bool = Field(default=False)
    base_dn: str = Field(default="")
    bind_dn: str = Field(default="")
    bind_password_enc: Optional[str] = None
    user_search_base: str = Field(default="")
    user_filter: str = Field(default="(sAMAccountName={username})")
    # SSO (Kerberos/Negotiate) — logowanie poświadczeniami Windows. Obsługę
    # SPNEGO robi Apache (mod_auth_gssapi); backend dostaje gotowy login.
    # sso_enabled — pokazuje przycisk i dopuszcza /auth/sso-login.
    # sso_auto — front automatycznie próbuje SSO przy wejściu (bez klikania).
    sso_enabled: bool = Field(default=False)
    sso_auto: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Audit log (append-only)
# ---------------------------------------------------------------------------

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    user_id: Optional[int] = Field(default=None, index=True)
    username: Optional[str] = Field(default=None, index=True)
    action: str = Field(index=True)
    target_type: Optional[str] = Field(default=None)
    target_id: Optional[str] = Field(default=None)
    method: Optional[str] = Field(default=None)
    path: Optional[str] = Field(default=None)
    status_code: Optional[int] = Field(default=None)
    ip: Optional[str] = Field(default=None)
    user_agent: Optional[str] = Field(default=None)
    details: Optional[str] = Field(default=None)


class PermissionDeclaration(SQLModel, table=True):
    """Oświadczenie osoby wnioskującej, składane w chwili skierowania wniosku
    do realizacji przez IT (RODO/NIS2/KSC).

    Powiązane z wnioskiem (`request_id`) i z pracownikiem (`worker_user_id`),
    żeby dało się je zestawić z uprawnieniami danej osoby. Treść jest ZAMROŻONA
    w chwili podpisu (edycja szablonu w Ustawieniach nie działa wstecz).

    `reference_code` = login-RRRRMMDD-GGMMSS-XXXXXXXX (login wnioskodawcy, data
    i godzina systemowa zatwierdzenia wniosku, 8-znakowy losowy ciąg A–Z0–9).
    Nowa tabela nie wymaga wpisu w `simple_migrations` — `create_all` utworzy ją
    przy starcie.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="accessrequest.id", index=True)
    # Pracownik, którego dotyczą nadawane uprawnienia (klucz zestawień).
    worker_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    worker_name: str
    unit_id: Optional[int] = Field(default=None, index=True)
    department_id: Optional[int] = Field(default=None, index=True)
    # Osoba składająca oświadczenie (kier. I stopnia w 1-stopniu, kier. II
    # stopnia w 2-stopniu — ta, której akcja kieruje wniosek do IT).
    declared_by_user_id: int = Field(foreign_key="user.id", index=True)
    declared_by_login: str                 # username → segment kodu referencyjnego
    declared_by_name: str                  # wpisane „imię i nazwisko"
    declared_date: str                     # wpisana data (RRRR-MM-DD)
    approved_at: datetime                  # systemowy moment zatwierdzenia = złożenia
    reference_code: str = Field(index=True, unique=True)
    declaration_text: str                  # ZAMROŻONA kopia treści
    items_snapshot: Optional[str] = None   # JSON: [{system_name, permission_name, custom_values}]
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PermissionSnapshot(SQLModel, table=True):
    """Nocna migawka stanu upoważnień WSZYSTKICH osób (o 23:50).

    Zamrożony, niezależny od późniejszych zmian zapis „kto co miał danego dnia"
    — do audytu i odtworzenia stanu wstecz (retencja ≥ 5 lat). Dane trzymamy
    jako skompresowany JSON (`data_gz`) zamiast tysięcy wierszy dziennie:
    kilkanaście–kilkadziesiąt kB/dzień, więc 5 lat mieści się w megabajtach.

    Nowa tabela — `create_all` tworzy ją przy starcie, bez wpisu w migracjach.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    # Data lokalna migawki (RRRR-MM-DD) — jedna migawka na dzień (idempotencja).
    snapshot_date: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    # „system" (harmonogram/cron) albo username osoby, która wygenerowała ręcznie.
    generated_by: str = Field(default="system")
    person_count: int = Field(default=0)
    permission_count: int = Field(default=0)
    # SHA256 kanonicznego JSON-a — dowód niezmienności migawki.
    content_sha256: str = Field(default="")
    # gzip(JSON): {"generated_at", "rows":[{worker.., system.., permission.., kod}]}
    data_gz: bytes = Field(default=b"")


class NameChangeRequest(SQLModel, table=True):
    """Wniosek pracownika o zmianę nazwiska (np. po ślubie).

    Osobny, lekki obieg — pracownik zgłasza SAM DLA SIEBIE i trafia WPROST do
    IT (bez akceptacji kierownika i bez pozycji uprawnień). IT realizuje:
    zmienia `full_name`, a login (`username`) MOŻE, ale nie musi zmienić.

    Nowa tabela — `create_all` tworzy ją przy starcie, bez wpisu w migracjach.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    current_full_name: Optional[str] = None       # snapshot w chwili zgłoszenia
    requested_full_name: str                       # nowe imię i nazwisko
    # Świadomie BEZ pola „powód" — RODO (minimalizacja): powód zmiany nazwiska
    # (np. ślub, rozwód) to dana nadmiarowa, nieistotna dla realizacji przez IT.
    # pending → done / rejected
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    resolved_at: Optional[datetime] = None
    resolved_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    it_comment: Optional[str] = None
    # Czy IT zmieniło też login; jeśli tak — jaki był i jaki jest.
    username_changed: bool = Field(default=False)
    old_username: Optional[str] = None
    new_username: Optional[str] = None


# ---------------------------------------------------------------------------
# JWT revocation
# ---------------------------------------------------------------------------

class RevokedToken(SQLModel, table=True):
    jti: str = Field(primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    revoked_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime


# ---------------------------------------------------------------------------
# Security events
# ---------------------------------------------------------------------------

class SecurityEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    event_type: str = Field(index=True)
    severity: SecuritySeverity = Field(default=SecuritySeverity.medium, index=True)
    source: Optional[str] = Field(default=None)
    summary: str
    details: Optional[str] = Field(default=None)
    user_id: Optional[int] = Field(default=None, index=True)
    ip: Optional[str] = Field(default=None)
    resolved_at: Optional[datetime] = Field(default=None, index=True)
    resolved_by_user_id: Optional[int] = Field(default=None)
    resolution_note: Optional[str] = Field(default=None)


# ===========================================================================
# WORKFLOW ENGINE — konfigurowalne obiegi wniosków (kafelki + graf)
# ===========================================================================
# Zamiast hard-coded pending_selection → pending_manager → pending_it
# admin komponuje graf z węzłów (kafelków) w edytorze wizualnym. Każdy
# AccessRequest ma typ (RequestType) wskazujący na WorkflowTemplate,
# a przy jego utworzeniu powstaje WorkflowInstance z zamrożonym snapshotem
# szablonu (żeby zmiana szablonu nie psuła trwających instancji).
# Każdy krok kończy się WorkflowStep z podpisem łańcuchowym.

class WorkflowInstanceStatus(str, enum.Enum):
    active    = "active"
    completed = "completed"
    rejected  = "rejected"


class WorkflowStepAction(str, enum.Enum):
    approve      = "approve"       # węzeł zaakceptowany
    reject       = "reject"        # węzeł odrzucony → cała instancja rejected
    select       = "select"        # wybór uprawnień (payload = lista item_ids)
    execute      = "execute"       # IT zrealizowało
    auto_skip    = "auto_skip"     # silnik pominął (skip_if=true)
    auto_advance = "auto_advance"  # silnik automatycznie przeszedł dalej


WORKFLOW_INSTANCE_STATUSES = tuple(s.value for s in WorkflowInstanceStatus)
WORKFLOW_STEP_ACTIONS      = tuple(a.value for a in WorkflowStepAction)


# Typy węzłów rozpoznawane przez silnik. Reszta jest walidowana w routerze
# szablonów. Rozszerzenie o nowy typ = wpis tu + case w services/workflow.py.
NODE_TYPES = (
    "start",                    # zawsze pierwszy; auto-advance
    "select_permissions",       # kierownik wybiera systemy/uprawnienia
    "manager_approve",          # kierownik bezpośredni akceptuje
    "higher_manager_approve",   # kierownik wyższego rzędu; skip_if brak
    "it_execute",               # IT realizuje wniosek
    "end",                      # zawsze ostatni; auto-close
)


# Obieg papierowy z podpisem (PDF → EZD FINN) został wyłączony — decyzje
# zatwierdza się bezpośrednio w systemie. Pusty zbiór = żaden węzeł nie
# wymaga podpisu; bramka PDF/EZD w silniku pozostaje nieaktywna.
SIGNATURE_REQUIRED_NODE_TYPES = frozenset()


class WorkflowTemplate(SQLModel, table=True):
    """Szablon obiegu — graf węzłów zapisany jako JSON."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    version: int = Field(default=1)                    # zwiększane przy edycji
    # graph_json: {"nodes":[{"id","type","label","x","y","props":{}}],
    #              "edges":[{"from","to","condition":null}]}
    graph_json: str
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


class RequestType(SQLModel, table=True):
    """Rodzaj wniosku — np. „Nowy pracownik", „Zmiana uprawnień"."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    code: Optional[str] = Field(default=None, index=True)  # np. NEW_EMP
    description: Optional[str] = None
    workflow_template_id: int = Field(foreign_key="workflowtemplate.id", index=True)
    is_active: bool = Field(default=True, index=True)
    icon: Optional[str] = None   # nazwa ikony lucide (np. "user-plus")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowInstance(SQLModel, table=True):
    """Konkretna instancja obiegu podłączona do AccessRequest."""
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="accessrequest.id", index=True, unique=True)
    template_id: int = Field(foreign_key="workflowtemplate.id", index=True)
    template_version: int = Field(default=1)
    # Zamrożona kopia grafu z chwili utworzenia — żeby edycja szablonu nie
    # zmieniała trwających instancji. Silnik zawsze czyta stąd.
    template_snapshot: str
    current_node_id: Optional[str] = Field(default=None, index=True)
    status: WorkflowInstanceStatus = Field(default=WorkflowInstanceStatus.active, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = None

    # --- Stan procesu papierowego dla bieżącego węzła (resetowany na każdym advance) ---
    # Kiedy kierownik pobrał PDF wniosku do podpisu (obieg papierowy → EZD FINN)
    pending_pdf_at: Optional[datetime] = None
    # Czy kierownik potwierdził że podpisany PDF został wysłany EZD FINN do IT
    pending_ezd_confirmed: bool = Field(default=False)
    # Kto pobrał / potwierdził (audit)
    pending_pdf_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    pending_ezd_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


class WorkflowStep(SQLModel, table=True):
    """Historia — każde kliknięcie/skip w instancji, z podpisem łańcuchowym."""
    # H4 — dwa równoległe POST /workflow/action nie mogą zapisać kroku o tym
    # samym indeksie (co podwoiłoby krok / przeskoczyło węzeł): UNIQUE wymusza,
    # że drugi commit padnie z IntegrityError zamiast zdublować obieg.
    __table_args__ = (
        UniqueConstraint("instance_id", "step_index", name="uq_step_instance_index"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="workflowinstance.id", index=True)
    step_index: int = Field(default=0, index=True)  # kolejność w instancji
    node_id: str
    node_type: str = Field(index=True)
    action: WorkflowStepAction = Field(index=True)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    actor_name: Optional[str] = None                # snapshot dla trwałości audytu
    payload: Optional[str] = None                   # JSON: co zdecydowano
    comment: Optional[str] = None
    # Podpis łańcuchowy: sha256(prev_signature + step_data). Weryfikuje
    # integralność historii — nikt nie może wstawić kroku bez przełamania łańcucha.
    signature: str
    prev_signature: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
