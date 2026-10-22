#!/usr/bin/env bash
# setup.sh — Pierwsze uruchomienie / instalacja SZUP na serwerze Debian/Ubuntu
# Wymagania: Python 3.11+, Apache2
# Frontend buduj lokalnie (npm run build), skopiuj wraz z tym skryptem przed uruchomieniem.
set -euo pipefail

APP_DIR="/opt/szup"
WEBROOT="/var/www/szup.intranet.wods.pl"
SERVICE="szup"

echo "=== SZUP — instalacja ==="

# Katalogi
echo "[1/5] Tworzenie katalogów..."
mkdir -p "$APP_DIR"/{backend,data,logs}
mkdir -p "$WEBROOT"

# Kopiowanie backendu
echo "[2/5] Kopiowanie backendu..."
rsync -a --delete backend/ "$APP_DIR/backend/"

# Python virtualenv
echo "[3/5] Tworzenie virtualenv Python..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# Kopiowanie frontendu (dist zbudowany lokalnie)
echo "[4/5] Kopiowanie frontendu..."
if [ ! -d "frontend/dist" ]; then
    echo "BŁĄD: Brak katalogu frontend/dist — zbuduj frontend lokalnie: cd frontend && npm run build"
    exit 1
fi
rsync -a --delete frontend/dist/ "$WEBROOT/"

# Systemd
echo "[5/5] Instalacja usługi systemd..."
cp deploy/szup.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

echo ""
echo "=== Instalacja zakończona ==="
echo ""
echo "Dalsze kroki:"
echo "  1. Skonfiguruj /opt/szup/.env (SZUP_SECRET_KEY, opcjonalnie SZUP_CORS_ORIGINS)"
echo "     Klucz JWT generuje się sam przy pierwszym starcie: /opt/szup/data/jwt_secret.key (0600)"
echo "  2. Zainstaluj konfigurację Apache:"
echo "     cp deploy/szup-apache.conf /etc/apache2/sites-available/szup.conf"
echo "     a2enmod proxy proxy_http rewrite headers ssl"
echo "     a2ensite szup"
echo "     systemctl reload apache2"
echo "  3. Sprawdź status: systemctl status $SERVICE"
echo "  4. Logi: tail -f $APP_DIR/logs/app.log"
