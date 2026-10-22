#!/usr/bin/env bash
# enable-sso.sh — włącza logowanie SSO (Kerberos) dla SZUP, korzystając z tego,
# co już skonfigurowano na serwerze dla wods-auth (moduł auth_gssapi,
# /etc/krb5.conf, keytab konta usługowego współdzielonego z wods-auth).
#
# Użycie (jako root):
#   ./deploy/enable-sso.sh                 # keytab znajdzie sam w konfiguracji Apache
#   ./deploy/enable-sso.sh /sciezka/keytab # albo podaj ręcznie (wspólny keytab)
#   ./deploy/enable-sso.sh --off           # wyłącza SSO
set -euo pipefail

SSO_CONF="/etc/apache2/szup-sso.conf"
ENV_FILE="/opt/szup/.env"
SITE_CONF="/etc/apache2/sites-available/szup.conf"
SPN_HOST="szup.intranet.wods.pl"

ok()   { echo "  [OK]  $*"; }
fail() { echo "  [BŁĄD] $*"; exit 1; }

if [ "${1:-}" = "--off" ]; then
    rm -f "$SSO_CONF"
    apachectl configtest && systemctl reload apache2
    echo "SSO wyłączone (usunięto $SSO_CONF). W aplikacji odznacz też SSO w Ustawieniach."
    exit 0
fi

echo "=== SZUP: włączanie SSO (Kerberos) ==="

# 1. Moduły Apache — instalowane przy wods-auth
MODULES=$(apachectl -M 2>&1 || true)
if grep -q "auth_gssapi_module" <<<"$MODULES"; then
    ok "moduł auth_gssapi jest włączony"
else
    fail "brak modułu auth_gssapi — wykonaj: apt install libapache2-mod-auth-gssapi && a2enmod auth_gssapi"
fi
grep -q "headers_module" <<<"$MODULES" || { a2enmod headers >/dev/null; ok "włączono moduł headers"; }

# 2. Keytab — ten sam, co dla wods-auth (wspólne konto usługowe)
KEYTAB="${1:-}"
find_keytab() {
    local found
    found=$(grep -rhoP 'GssapiCredStore\s+"?keytab:\K[^"\s]+' \
                /etc/apache2/ /var/www/ --include='*.conf' --include='.htaccess' 2>/dev/null | head -1 || true)
    [ -n "$found" ] && { echo "$found"; return; }
    found=$(grep -rhoP 'KRB5_KTNAME=["'\'']?(FILE:)?\K[^"'\''\s]+' /etc/apache2/ /etc/default/ 2>/dev/null | head -1 || true)
    [ -n "$found" ] && { echo "$found"; return; }
    [ -f /etc/krb5.keytab ] && { echo /etc/krb5.keytab; return; }
    ls /etc/apache2/*.keytab /etc/*.keytab 2>/dev/null | head -1 || true
}
[ -n "$KEYTAB" ] || KEYTAB=$(find_keytab)
[ -n "$KEYTAB" ] || fail "nie znalazłem keytab — znajdź go: grep -rn -i keytab /etc/apache2/ /var/www/ ; potem: $0 /sciezka/do/pliku.keytab"
[ -f "$KEYTAB" ] || fail "plik $KEYTAB nie istnieje"
runuser -u www-data -- test -r "$KEYTAB" || fail "www-data nie może czytać $KEYTAB (chown root:www-data; chmod 640)"
ok "keytab: $KEYTAB"
echo "        zawartość (principal i numer klucza KVNO):"
klist -k "$KEYTAB" 2>/dev/null | sed 's/^/          /' | head -12 || true

# 3. Vhost musi mieć IncludeOptional (nowa wersja deploy/szup-apache.conf)
[ -f "$SITE_CONF" ] || fail "brak $SITE_CONF — najpierw: cp deploy/szup-apache.conf $SITE_CONF"
grep -q "szup-sso.conf" "$SITE_CONF" || {
    # Vhost bywa zmieniany lokalnie (certyfikaty, aliasy) — zachowaj kopię,
    # żeby dało się przenieść te zmiany do nowej wersji.
    SITE_BACKUP="$SITE_CONF.bak-$(date +%F-%H%M%S)"
    cp -p "$SITE_CONF" "$SITE_BACKUP"
    cp deploy/szup-apache.conf "$SITE_CONF"
    ok "zaktualizowano $SITE_CONF (nowa wersja z deploy/)"
    echo "        poprzednia wersja: $SITE_BACKUP — przenieś lokalne zmiany (np. ścieżki certyfikatów):"
    echo "        diff -u $SITE_BACKUP $SITE_CONF"
}

# 4. Sekret między Apache a aplikacją
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
SECRET=$(grep -oP '^SZUP_SSO_PROXY_SECRET=\K.+' "$ENV_FILE" || true)
if [ -z "$SECRET" ]; then
    SECRET=$(openssl rand -hex 32)
    echo "SZUP_SSO_PROXY_SECRET=$SECRET" >> "$ENV_FILE"
    ok "wygenerowano sekret w $ENV_FILE"
else
    ok "sekret już jest w $ENV_FILE"
fi

# 5. Blok SSO dla Apache
cat > "$SSO_CONF" <<EOF
# Wygenerowane przez szup/deploy/enable-sso.sh — $(date '+%Y-%m-%d %H:%M')
<Location "/api/auth/sso-login">
    AuthType GSSAPI
    AuthName "WODS SSO"
    GssapiCredStore keytab:$KEYTAB
    GssapiAllowedMech krb5
    GssapiLocalName On
    GssapiSSLonly On
    Require valid-user
    RequestHeader set X-Remote-User "%{REMOTE_USER}s"
    RequestHeader set X-SSO-Proxy-Secret "$SECRET"
    ErrorDocument 401 /index.html
</Location>
EOF
chmod 640 "$SSO_CONF"
ok "zapisano $SSO_CONF"

# 6. Przeładowanie
apachectl configtest || { rm -f "$SSO_CONF"; fail "błąd konfiguracji Apache — cofnąłem $SSO_CONF"; }
systemctl reload apache2 && ok "Apache przeładowany"

echo ""
echo "WAŻNE: SZUP_SSO_PROXY_SECRET musi trafić do usługi szup — backend ODRZUCA"
echo "logowanie SSO, gdy sekret jest pusty albo niezgodny z nagłówkiem z Apache."
echo "Po zmianie zrestartuj usługę: systemctl restart szup. Jeśli szup.service"
echo "nie czyta $ENV_FILE (EnvironmentFile), dopisz sekret ręcznie:"
echo "  systemctl edit szup"
echo "  [Service]"
echo "  Environment=SZUP_SSO_PROXY_SECRET=$SECRET"
echo "  systemctl daemon-reload && systemctl restart szup"
echo ""
echo "Zostało:"
echo "  - na DC: setspn -S HTTP/$SPN_HOST <konto-wspólne-z-wods-auth>  (+ regeneracja wspólnego keytaba, patrz runbook)"
echo "  - w GPO przeglądarek dopisać: $SPN_HOST"
echo "  - w aplikacji: Ustawienia -> Active Directory / LDAP -> zaznaczyć SSO"
