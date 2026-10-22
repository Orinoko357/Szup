#!/usr/bin/env bash
# deploy.sh — Aktualizacja SZUP na serwerze produkcyjnym
# Uruchom jako root na serwerze Debian/Ubuntu (z dowolnego katalogu).
# Frontend zbuduj lokalnie przed skopiowaniem plików:
#   cd frontend && npm run build
set -euo pipefail

# Ścieżki względne (backend/, frontend/dist, deploy/) liczymy od katalogu repo,
# niezależnie od tego, skąd skrypt uruchomiono.
cd "$(dirname "$0")/.."

APP_DIR="/opt/szup"
WEBROOT="/var/www/szup.intranet.wods.pl"
VENV="$APP_DIR/venv"
SERVICE="szup"
ENV_FILE="$APP_DIR/.env"
HEALTH_URL="http://127.0.0.1:8003/api/health"
BACKUP_DIR="${SZUP_BACKUP_DIR:-$APP_DIR/backups}"
BACKUP_KEEP=10

# Katalog danych tak, jak widzi go usługa: SZUP_DATA_DIR z $ENV_FILE
# (EnvironmentFile nadpisuje Environment= w szup.service), potem ze środowiska
# usługi systemd, a na końcu wartość domyślna.
data_dir_from_env_file() {
    [ -r "$ENV_FILE" ] || return 0
    grep -E '^[[:space:]]*(export[[:space:]]+)?SZUP_DATA_DIR=' "$ENV_FILE" | tail -n 1 \
        | sed -E 's/^[^=]*=//; s/^["'\'']//; s/["'\'']?[[:space:]]*$//'
}
data_dir_from_service() {
    systemctl show "$SERVICE" -p Environment --value 2>/dev/null | tr ' ' '\n' \
        | sed -n 's/^SZUP_DATA_DIR=//p' | tail -n 1
}
DATA_DIR="$(data_dir_from_env_file || true)"
[ -n "$DATA_DIR" ] || DATA_DIR="$(data_dir_from_service || true)"
[ -n "$DATA_DIR" ] || DATA_DIR="$APP_DIR/data"
DB="${SZUP_DB:-$DATA_DIR/szup.db}"

echo "=== SZUP — wdrożenie ==="
echo "Baza danych: $DB"
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
        # .backup — spójna kopia „na gorąco” (usługa może działać), razem
        # z zawartością pliku -wal. Ścieżka w apostrofach — apostrof w niej
        # zepsułby polecenie, więc go odrzucamy.
        case "$BACKUP_FILE" in
            *"'"*) echo "BŁĄD: ścieżka kopii zawiera apostrof ($BACKUP_FILE)."; exit 1 ;;
        esac
        sqlite3 "$DB" ".backup '$BACKUP_FILE'" \
            || { echo "BŁĄD: kopia bazy nie powiodła się — wdrożenie przerwane."; exit 1; }
    else
        # Bez sqlite3 kopiujemy plik. Gdy baza ma niepusty plik -wal, sama kopia
        # pliku głównego byłaby niespójna — wtedy wymagamy sqlite3.
        if [ -s "$DB-wal" ]; then
            echo "BŁĄD: baza ma niezapisany dziennik $DB-wal, a brak sqlite3."
            echo "      Zainstaluj pakiet: apt install sqlite3 — wdrożenie przerwane."
            exit 1
        fi
        echo "UWAGA: brak sqlite3 — kopiuję plik (cp); zainstaluj pakiet sqlite3."
        # Bez -p: kopia ma bieżący czas modyfikacji.
        cp "$DB" "$BACKUP_FILE" \
            || { echo "BŁĄD: kopia bazy nie powiodła się — wdrożenie przerwane."; exit 1; }
    fi
    if [ ! -s "$BACKUP_FILE" ]; then
        echo "BŁĄD: kopia bazy jest pusta ($BACKUP_FILE) — wdrożenie przerwane."
        exit 1
    fi
    chmod 600 "$BACKUP_FILE"
    echo "  → $BACKUP_FILE"
    # Zostaw tylko $BACKUP_KEEP najnowszych kopii. Sortujemy po NAZWIE
    # (szup-RRRR-MM-DD-GGMMSS.db), a nie po czasie modyfikacji pliku.
    ls -1 "$BACKUP_DIR"/szup-*.db 2>/dev/null | sort -r \
        | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f --
    echo ""
elif [ -d "$APP_DIR/backend" ] && [ "${SZUP_NO_DB_OK:-0}" != "1" ]; then
    # Aplikacja jest już zainstalowana, a bazy nie ma pod oczekiwaną ścieżką —
    # najpewniej zła ścieżka. Nie wdrażamy bez kopii.
    echo "BŁĄD: aplikacja jest zainstalowana ($APP_DIR/backend), ale nie ma bazy $DB."
    echo "      Sprawdź SZUP_DATA_DIR w $ENV_FILE i w szup.service albo podaj SZUP_DB=/ścieżka."
    echo "      Jeśli to świadome (pusta instalacja), uruchom z SZUP_NO_DB_OK=1."
    exit 1
else
    echo "Brak bazy $DB (pierwsze wdrożenie) — pomijam kopię."
    echo ""
fi

# 1. Aktualizacja zależności Python (tylko produkcyjne — bez narzędzi testowych)
echo "[1/3] Aktualizacja zależności Python..."
"$VENV/bin/pip" install --quiet -r backend/requirements.txt

# 2. Kopiowanie backendu — bez testów, lokalnego venv i plików kompilacji.
#    --delete-excluded usuwa też te katalogi z poprzednich wdrożeń.
echo "[2/3] Kopiowanie backendu..."
rsync -a --delete --delete-excluded \
    --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.pytest_cache/' --exclude 'tests/' --exclude 'requirements-dev.txt' \
    backend/ "$APP_DIR/backend/"

# 3. Kopiowanie frontendu
echo "[3/3] Kopiowanie frontendu..."
if [ ! -d "frontend/dist" ]; then
    echo "BŁĄD: Brak katalogu frontend/dist — zbuduj frontend lokalnie: cd frontend && npm run build"
    exit 1
fi
rsync -a --delete frontend/dist/ "$WEBROOT/"

# Restart usługi i sprawdzenie, czy faktycznie odpowiada (migracje idą przy starcie).
echo "Restart usługi $SERVICE..."
systemctl restart "$SERVICE"

EXPECTED_VERSION="$(sed -n 's/^[[:space:]]*version="\([^"]*\)".*/\1/p' backend/main.py | head -n 1)"
HEALTH=""
for _ in $(seq 1 15); do
    sleep 2
    if HEALTH="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)"; then
        break
    fi
    HEALTH=""
done
if [ -z "$HEALTH" ]; then
    echo ""
    echo "BŁĄD: usługa $SERVICE nie odpowiada na $HEALTH_URL po restarcie."
    systemctl status "$SERVICE" --no-pager || true
    echo "--- ostatnie wpisy $APP_DIR/logs/app.log ---"
    tail -n 40 "$APP_DIR/logs/app.log" 2>/dev/null || true
    echo ""
    echo "Kopia bazy sprzed wdrożenia: ${BACKUP_FILE:-brak} (przywracanie: README, „Przywracanie kopii”)."
    exit 1
fi
RUNNING_VERSION="$(printf '%s' "$HEALTH" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
echo "  → usługa działa, wersja $RUNNING_VERSION"
if [ -n "$EXPECTED_VERSION" ] && [ "$RUNNING_VERSION" != "$EXPECTED_VERSION" ]; then
    echo "UWAGA: oczekiwano wersji $EXPECTED_VERSION — sprawdź, czy skopiowano właściwy kod."
fi

echo ""
echo "=== Wdrożenie zakończone ==="
echo "Logi: tail -f $APP_DIR/logs/app.log"
