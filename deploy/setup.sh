#!/usr/bin/env bash
# setup.sh — Pierwsze uruchomienie / instalacja SZUP na serwerze Debian/Ubuntu
# Wymagania: Python 3.11+, Apache2
# Frontend buduj lokalnie (npm run build), skopiuj wraz z tym skryptem przed uruchomieniem.
set -euo pipefail

# Ścieżki względne (backend/, frontend/dist, deploy/) liczymy od katalogu repo,
# niezależnie od tego, skąd skrypt uruchomiono (tak samo jak deploy.sh).
cd "$(dirname "$0")/.."

APP_DIR="/opt/szup"
WEBROOT="/var/www/szup.intranet.wods.pl"
SERVICE="szup"

echo "=== SZUP — instalacja ==="

# Katalogi
echo "[1/5] Tworzenie katalogów..."
mkdir -p "$APP_DIR"/{backend,data,logs}
# Baza (dane osobowe, hashe haseł, audyt), klucze i logi — tylko dla roota.
chmod 700 "$APP_DIR/data" "$APP_DIR/logs"
mkdir -p "$WEBROOT"

# Kopiowanie backendu — te same filtry co w deploy.sh: bez testów, lokalnego
# venv i plików kompilacji; dane i sekrety z checkoutu (data/, .env*, *.db*,
# *.key) nie trafiają na serwer, a istniejące na serwerze są chronione (P).
# Kod należy do roota z prawami 755/644.
echo "[2/5] Kopiowanie backendu..."
rsync -a --delete --delete-excluded --chown=root:root --chmod=D755,F644 \
    --filter 'P /data/' --filter 'P .env*' --filter 'P *.db*' --filter 'P *.key' \
    --exclude '/data/' --exclude '.env*' --exclude '*.db*' --exclude '*.key' \
    --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.pytest_cache/' --exclude 'tests/' --exclude 'requirements-dev.txt' \
    backend/ "$APP_DIR/backend/"

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
rsync -a --delete --chown=root:root --chmod=D755,F644 frontend/dist/ "$WEBROOT/"

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
