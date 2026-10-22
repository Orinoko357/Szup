"""
LDAP / Active Directory authentication + odczyt struktury OU.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def service_bind_user(settings) -> str:
    """Nazwa do simple bind konta usługowego. AD przyjmuje pełny DN, UPN
    (svc@domena.local) albo DOMENA\\svc; gołe 'svc' kończy się invalidCredentials
    — dopisujemy domenę wyliczoną z Base DN (DC=wods,DC=local → @wods.local)."""
    user = (settings.bind_dn or "").strip()
    if not user or "=" in user or "@" in user or "\\" in user:
        return user
    dcs = re.findall(r"(?i)\bDC=([^,]+)", settings.base_dn or "")
    return f"{user}@{'.'.join(d.strip() for d in dcs)}" if dcs else user


def normalize_login(username: str) -> str:
    """'DOMENA\\jan.kowalski' / 'jan.kowalski@domena.local' / ' Jan.Kowalski ' → 'jan.kowalski'.
    Małe litery — żeby jedno konto AD nie tworzyło kilku kont w aplikacji."""
    u = (username or "").strip()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return u.strip().lower()


# Dozwolone znaki loginu PO normalizacji (bez realmu: „@” i „\\” już obcięte).
# Ten sam wzorzec dla logowania AD, SSO i importu — „jan@domena” nie może
# przejść jako osobny login i utworzyć drugiego konta.
_LOGIN_RE = re.compile(r"[\w\-. ]+")


def is_valid_login(username: str) -> bool:
    return bool(username) and bool(_LOGIN_RE.fullmatch(username))


def find_user_by_login(session, login: str):
    """Wyszukanie istniejącego konta po loginie BEZ względu na wielkość liter
    (np. stare konto „Jan.Kowalski” i logowanie „jan.kowalski”) — żeby nie
    powstawały duplikaty. Przy kilku dopasowaniach preferujemy dokładne."""
    from sqlalchemy import func
    from sqlmodel import select
    from models import User
    if not login:
        return None
    rows = session.exec(
        select(User).where(func.lower(User.username) == login.lower()).order_by(User.id)
    ).all()
    if not rows:
        return None
    for u in rows:
        if u.username == login:
            return u
    return rows[0]


def ad_domain(settings) -> str:
    """Domena DNS wyliczona z Base DN (DC=wods,DC=local → 'wods.local'); '' gdy brak."""
    dcs = re.findall(r"(?i)\bDC=([^,]+)", getattr(settings, "base_dn", "") or "")
    return ".".join(d.strip() for d in dcs).lower()


def login_realm_ok(settings, raw: str) -> bool:
    """Czy realm/domena w surowym loginie (np. z X-Remote-User) zgadza się z
    domeną skonfigurowaną w LDAP. Login bez realmu → OK (Apache z
    GssapiLocalName sam obcina realm domyślny). Gdy w ustawieniach nie ma
    domeny (pusty Base DN) — nie mamy z czym porównać, przepuszczamy.

    Akceptujemy: 'jan@WODS.LOCAL' (pełna domena) oraz 'WODS\\jan' / 'WODS.LOCAL\\jan'
    (pierwszy człon domeny jako nazwa NetBIOS albo pełna domena)."""
    domain = ad_domain(settings)
    u = (raw or "").strip()
    if not domain:
        return True
    if "\\" in u:
        realm = u.split("\\", 1)[0].strip().lower()
        return realm in (domain, domain.split(".")[0])
    if "@" in u:
        realm = u.split("@", 1)[1].strip().lower()
        return realm == domain
    return True


def lookup_user(settings, username: str) -> tuple[str, dict]:
    """Wyszukanie konta w AD kontem usługowym (bez hasła użytkownika) — dla SSO,
    gdzie tożsamość potwierdził już Kerberos w Apache. Zwraca (status, dane):
    "ok" + {display_name}, "not_found", "disabled", albo "error" + {message}."""
    if not is_valid_login(username or ""):
        return "not_found", {}
    from ldap3 import Server, Connection, SUBTREE
    from ldap3.utils.conv import escape_filter_chars
    from services.crypto import decrypt

    bind_password = decrypt(settings.bind_password_enc) if settings.bind_password_enc else ""
    search_base = settings.user_search_base or settings.base_dn
    search_filter = settings.user_filter.format(username=escape_filter_chars(username))
    server = Server(settings.host, port=settings.port, use_ssl=settings.use_ssl)
    try:
        with Connection(server, user=service_bind_user(settings), password=bind_password,
                        auto_bind=True) as conn:
            conn.search(search_base, search_filter, search_scope=SUBTREE,
                        attributes=["displayName", "userAccountControl"])
            if not conn.entries:
                return "not_found", {}
            e = conn.entries[0]
            uac = int(e.userAccountControl.value or 0) if "userAccountControl" in e else 0
            if uac & 2:                       # ACCOUNTDISABLE
                return "disabled", {}
            name = str(e.displayName.value) if "displayName" in e and e.displayName.value else None
            return "ok", {"display_name": name}
    except Exception as exc:  # noqa: BLE001
        logger.error("LDAP lookup for SSO failed: %s", exc)
        return "error", {"message": str(exc)}


def normalize_dn(dn: str) -> str:
    """Znormalizowany DN do porównań (lowercase, trim wokół przecinków)."""
    if not dn:
        return ""
    return ",".join(p.strip().lower() for p in dn.split(","))


def parent_dn(dn: str) -> str:
    """Zwraca rodzicowski DN (wszystko po pierwszym przecinku)."""
    parts = dn.split(",", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def fetch_ou_structure(settings, search_base: str) -> list[dict]:
    """
    Pobiera pełną (dowolnie zagnieżdżoną) strukturę OU z AD/LDAP.
      Poziom 1 (bezpośrednio pod search_base) → jednostki organizacyjne
      Głębsze poziomy                          → wydziały (drzewo)

    Zwraca listę słowników:
      [{ dn, name, departments: [{ dn, name, children: [...] }] }]
    """
    from ldap3 import Server, Connection, ALL, SUBTREE
    from services.crypto import decrypt

    bind_password = decrypt(settings.bind_password_enc) if settings.bind_password_enc else ""
    server = Server(settings.host, port=settings.port, use_ssl=settings.use_ssl, get_info=ALL)

    def _ou_name(entry) -> str:
        try:
            v = entry.ou.value
            return str(v) if v else entry.entry_dn.split(",")[0].split("=")[-1]
        except Exception:
            return entry.entry_dn.split(",")[0].split("=")[-1]

    def _ou_desc(entry) -> str | None:
        try:
            v = getattr(entry, "description", None)
            v = v.value if v is not None else None
            if isinstance(v, (list, tuple)):
                v = v[0] if v else None
            v = (str(v).strip() if v is not None else "")
            return v or None
        except Exception:
            return None

    base_norm = normalize_dn(search_base)

    with Connection(server, user=settings.bind_dn, password=bind_password, auto_bind=True) as conn:
        conn.search(search_base, "(objectClass=organizationalUnit)",
                    search_scope=SUBTREE, attributes=["ou", "description"])
        entries = [(e.entry_dn, _ou_name(e), _ou_desc(e)) for e in conn.entries]

    # Index wszystkich OU wg znormalizowanego DN
    by_dn: dict[str, dict] = {}
    for dn, name, desc in entries:
        if normalize_dn(dn) == base_norm:
            continue  # sam search_base — nie włączamy go
        by_dn[normalize_dn(dn)] = {"dn": dn, "name": name, "description": desc, "children": []}

    # Zbuduj drzewo po parent-DN
    roots: list[dict] = []
    for dn, _name, _desc in entries:
        norm_dn = normalize_dn(dn)
        if norm_dn == base_norm or norm_dn not in by_dn:
            continue
        node = by_dn[norm_dn]
        parent_norm = normalize_dn(parent_dn(dn))
        if parent_norm == base_norm:
            roots.append(node)
        elif parent_norm in by_dn:
            by_dn[parent_norm]["children"].append(node)
        else:
            # rodzic poza zakresem — traktuj jako korzeń (nie powinno wystąpić przy SUBTREE)
            roots.append(node)

    def _sort(nodes: list[dict]) -> None:
        nodes.sort(key=lambda n: n["name"].lower())
        for n in nodes:
            _sort(n["children"])
    _sort(roots)

    # Poziom 1 = jednostki; ich children = wydziały (drzewo)
    return [
        {"dn": r["dn"], "name": r["name"], "description": r.get("description"),
         "departments": r["children"]}
        for r in roots
    ]


def fetch_ldap_users(settings, search_base: str) -> list[dict]:
    """
    Pobiera użytkowników z AD pod `search_base` (rekurencyjnie).

    Zwraca listę słowników z kluczami:
        dn, parent_dn, username, full_name, email, is_enabled_in_ad
    """
    from ldap3 import Server, Connection, ALL, SUBTREE
    from services.crypto import decrypt

    bind_password = decrypt(settings.bind_password_enc) if settings.bind_password_enc else ""
    server = Server(settings.host, port=settings.port, use_ssl=settings.use_ssl, get_info=ALL)

    # AD: ACCOUNTDISABLE = 0x2 w userAccountControl
    ACCOUNTDISABLE = 0x2

    def _str(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return str(value) if value is not None else None

    out: list[dict] = []
    with Connection(server, user=settings.bind_dn, password=bind_password, auto_bind=True) as conn:
        conn.search(
            search_base,
            "(&(objectCategory=person)(objectClass=user))",
            search_scope=SUBTREE,
            attributes=["sAMAccountName", "displayName", "cn", "mail", "userAccountControl", "title"],
        )
        for e in conn.entries:
            dn = e.entry_dn
            username = _str(getattr(e, "sAMAccountName", None) and e.sAMAccountName.value)
            if not username:
                continue
            full_name = (
                _str(getattr(e, "displayName", None) and e.displayName.value)
                or _str(getattr(e, "cn", None) and e.cn.value)
                or username
            )
            email = _str(getattr(e, "mail", None) and e.mail.value)
            title = _str(getattr(e, "title", None) and e.title.value)
            uac_raw = getattr(e, "userAccountControl", None)
            uac = int(uac_raw.value) if uac_raw and uac_raw.value is not None else 0
            is_enabled = not bool(uac & ACCOUNTDISABLE)
            out.append({
                "dn": dn,
                "parent_dn": parent_dn(dn),
                "username": username,
                "full_name": full_name,
                "email": email,
                "title": title,
                "is_enabled_in_ad": is_enabled,
            })

    out.sort(key=lambda u: (u["full_name"] or "").lower())
    return out


def authenticate_ldap(settings, username: str, password: str) -> bool:
    # Login musi być już znormalizowany (normalize_login) — bez realmu i „@”.
    if not is_valid_login(username or ""):
        logger.warning("LDAP: rejected username with unsafe characters: %r", username)
        return False
    try:
        from ldap3 import Server, Connection, ALL, SUBTREE
        from ldap3.utils.conv import escape_filter_chars
        from services.crypto import decrypt

        bind_password = decrypt(settings.bind_password_enc) if settings.bind_password_enc else ""
        search_base   = settings.user_search_base or settings.base_dn
        search_filter = settings.user_filter.format(username=escape_filter_chars(username))

        server = Server(settings.host, port=settings.port, use_ssl=settings.use_ssl, get_info=ALL)

        with Connection(server, user=settings.bind_dn, password=bind_password, auto_bind=True) as conn:
            conn.search(search_base, search_filter, search_scope=SUBTREE, attributes=["distinguishedName"])
            if not conn.entries:
                logger.info("LDAP: user %r not found", username)
                return False
            user_dn = conn.entries[0].entry_dn

        with Connection(server, user=user_dn, password=password, auto_bind=True):
            logger.info("LDAP: user %r authenticated", username)
            return True

    except Exception as exc:
        logger.warning("LDAP error for %r: %s", username, exc)
        return False
