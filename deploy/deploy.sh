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
# Baza SQLite (SZUP_DATA_DIR z szup.service) i katalog kopii przed wdrożeniem.
DB="${SZUP_DB:-$APP_DIR/data/szup.db}"
BACKUP_DIR="${SZUP_BACKUP_DIR:-$APP_DIR/backups}"
BACKUP_KEEP=10

echo "=== SZUP — wdrożenie ==="
echo ""

# 0. Audyt bezpieczeństwa zależności (NIS2) — nie blokuje deployu, ale ostrzega.
if [ -x "./deploy/audit-deps.sh" ] && [ "${SKIP_AUDIT:-0}" != "1" ]; then
    echo "[0/3] Audyt zależności (pip-audit + npm audit)..."
    ./deploy/audit-deps.sh || echo "UWAGA: znalezione podatności — sprawdź deploy/audit-reports/"
    echo ""
fi

# Kopia bazy PRZED zmianą kodu — migracje (ALTER) idą przy restarcie usługi.
# Nieudana kopia przerywa wdrożenie (set -e + jawny exit).
if [ -f "$DB" ]; then
    echo "Kopia bazy danych..."
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/szup-$(date +%F-%H%M%S).db"
    if command -v sqlite3 >/dev/null 2>&1; then
        # .backup — spójna kopia „na gorąco” (usługa może działać)
        sqlite3 "$DB" ".backup '$BACKUP_FILE'" \
            || { echo "BŁĄD: kopia bazy nie powiodła się — wdrożenie przerwane."; exit 1; }
    else
        echo "UWAGA: brak sqlite3 — kopiuję plik (cp); zainstaluj pakiet sqlite3."
        cp -p "$DB" "$BACKUP_FILE" \
            || { echo "BŁĄD: kopia bazy nie powiodła się — wdrożenie przerwane."; exit 1; }
    fi
    if [ ! -s "$BACKUP_FILE" ]; then
        echo "BŁĄD: kopia bazy jest pusta ($BACKUP_FILE) — wdrożenie przerwane."
        exit 1
    fi
    chmod 600 "$BACKUP_FILE"
    echo "  → $BACKUP_FILE"
    # Zostaw tylko $BACKUP_KEEP najnowszych kopii.
    ls -1t "$BACKUP_DIR"/szup-*.db 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f --
    echo ""
else
    echo "Brak bazy $DB (pierwsze wdrożenie?) — pomijam kopię."
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
