#!/usr/bin/env bash
# deploy.sh — Aktualizacja SZUP na serwerze produkcyjnym
# Uruchom jako root na serwerze Debian/Ubuntu.
# Frontend zbuduj lokalnie przed skopiowaniem plików:
#   cd frontend && npm run build
set -euo pipefail

APP_DIR="/opt/szup"
WEBROOT="/var/www/szup.intranet.wods.pl"
VENV="$APP_DIR/venv"
SERVICE="szup"

echo "=== SZUP — wdrożenie ==="
echo ""

# 0. Audyt bezpieczeństwa zależności (NIS2) — nie blokuje deployu, ale ostrzega.
if [ -x "./deploy/audit-deps.sh" ] && [ "${SKIP_AUDIT:-0}" != "1" ]; then
    echo "[0/3] Audyt zależności (pip-audit + npm audit)..."
    ./deploy/audit-deps.sh || echo "UWAGA: znalezione podatności — sprawdź deploy/audit-reports/"
    echo ""
fi

# 1. Aktualizacja zależności Python
echo "[1/3] Aktualizacja zależności Python..."
"$VENV/bin/pip" install --quiet -r backend/requirements.txt

# 2. Kopiowanie backendu
echo "[2/3] Kopiowanie backendu..."
rsync -a --delete backend/ "$APP_DIR/backend/"

# 3. Kopiowanie frontendu
echo "[3/3] Kopiowanie frontendu..."
if [ ! -d "frontend/dist" ]; then
    echo "BŁĄD: Brak katalogu frontend/dist — zbuduj frontend lokalnie: cd frontend && npm run build"
    exit 1
fi
rsync -a --delete frontend/dist/ "$WEBROOT/"

# Restart usługi
echo "Restart usługi $SERVICE..."
systemctl restart "$SERVICE"
sleep 2
systemctl status "$SERVICE" --no-pager

echo ""
echo "=== Wdrożenie zakończone ==="
echo "Logi: tail -f $APP_DIR/logs/app.log"
