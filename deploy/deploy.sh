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
# Kopie z deploy.sh mają WŁASNY prefiks: retencja (BACKUP_KEEP) obejmuje tylko
# je, a nocne kopie z crona (szup-RRRR-MM-DD-GGMMSS.db, patrz
# docs/security/backup_and_dr.md) zostają nietknięte.
BACKUP_PREFIX="szup-predeploy-"

# Wartość zmiennej z $ENV_FILE (składnia KEY=wartość, opcjonalnie z `export`).
# Ostatnie wystąpienie wygrywa. Wartość w cudzysłowie/apostrofach bierzemy
# dosłownie (bez cudzysłowów); bez cudzysłowów obcinamy komentarz „ #…”
# i końcowe spacje.
env_file_value() {
    local key="$1" line value
    [ -r "$ENV_FILE" ] || return 0
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$ENV_FILE" | tail -n 1)" || true
    [ -n "$line" ] || return 0
    value="${line#*=}"
    value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]+//')"
    case "$value" in
        \"*) value="$(printf '%s' "$value" | sed -E 's/^"([^"]*)".*$/\1/')" ;;
        \'*) value="$(printf '%s' "$value" | sed -E "s/^'([^']*)'.*\$/\\1/")" ;;
        *)   value="$(printf '%s' "$value" | sed -E 's/(^|[[:space:]])#.*$//; s/[[:space:]]+$//')" ;;
    esac
    printf '%s\n' "$value"
}
# Wartość zmiennej ze środowiska usługi systemd (Environment= w szup.service).
service_env_value() {
    systemctl show "$SERVICE" -p Environment --value 2>/dev/null | tr ' ' '\n' \
        | sed -n "s/^$1=//p" | tail -n 1
}
# Zmienna tak, jak widzi ją usługa: najpierw $ENV_FILE (EnvironmentFile
# nadpisuje Environment= w szup.service), potem środowisko usługi.
service_setting() {
    local v
    v="$(env_file_value "$1" || true)"
    [ -n "$v" ] || v="$(service_env_value "$1" || true)"
    printf '%s\n' "$v"
}
# Ścieżka kanoniczna (dowiązania rozwiązane, nie musi istnieć); bez realpath — bez zmian.
canon_path() {
    realpath -m -- "$1" 2>/dev/null || printf '%s\n' "$1"
}

DATA_DIR="$(service_setting SZUP_DATA_DIR)"
[ -n "$DATA_DIR" ] || DATA_DIR="$APP_DIR/data"
# Ścieżkę względną usługa liczy od WorkingDirectory (= $APP_DIR/backend) —
# tak samo jak względny SZUP_DB_URL niżej. Liczona od katalogu repo nie
# wpadłaby w kontrolę „dane w backend/” i dawała mylące „nie ma bazy”.
case "$DATA_DIR" in
    /*) ;;
    *)  DATA_DIR="$APP_DIR/backend/$DATA_DIR" ;;
esac

# rsync --delete do $APP_DIR/backend skasowałby katalog danych, gdyby leżał
# w jego wnętrzu — wtedy nie wdrażamy wcale.
DATA_DIR_CANON="$(canon_path "$DATA_DIR")"
BACKEND_CANON="$(canon_path "$APP_DIR/backend")"
case "$DATA_DIR_CANON/" in
    "$BACKEND_CANON"/*)
        echo "BŁĄD: katalog danych ($DATA_DIR_CANON) leży wewnątrz $BACKEND_CANON."
        echo "      Synchronizacja kodu (rsync --delete) mogłaby go usunąć — wdrożenie przerwane."
        echo "      Przenieś dane poza katalog backendu i popraw SZUP_DATA_DIR."
        exit 1 ;;
esac

# Baza: SZUP_DB (jawnie przy uruchomieniu) → SZUP_DB_URL usługi, o ile wskazuje
# plik SQLite → $DATA_DIR/szup.db. Ścieżkę względną w URL usługa liczy od
# WorkingDirectory (= $APP_DIR/backend).
DB_URL="$(service_setting SZUP_DB_URL)"
if [ -n "${SZUP_DB:-}" ]; then
    DB="$SZUP_DB"
elif [ -n "$DB_URL" ]; then
    case "$DB_URL" in
        sqlite:///*)
            DB="${DB_URL#sqlite:///}"
            DB="${DB%%\?*}"
            case "$DB" in
                /*) ;;
                *)  DB="$APP_DIR/backend/$DB" ;;
            esac ;;
        *)
            echo "UWAGA: SZUP_DB_URL wskazuje bazę inną niż plik SQLite — deploy.sh nie zrobi jej kopii."
            if [ "${SZUP_NO_DB_OK:-0}" != "1" ]; then
                echo "BŁĄD: zrób kopię bazy samodzielnie i uruchom ponownie z SZUP_NO_DB_OK=1."
                exit 1
            fi
            DB="" ;;
    esac
else
    DB="$DATA_DIR/szup.db"
fi
if [ -n "$DB" ]; then
    case "$(canon_path "$DB")" in
        "$BACKEND_CANON"/*)
            echo "UWAGA: baza ($DB) leży w katalogu backendu. Pliki *.db* są chronione"
            echo "       przed rsync --delete, ale przenieś bazę do katalogu danych."
            ;;
    esac
fi

# curl jest potrzebny tylko do sprawdzenia usługi po restarcie. Bez niego
# nie zgłaszamy fałszywej awarii — pomijamy sprawdzenie z ostrzeżeniem.
HAVE_CURL=1
if ! command -v curl >/dev/null 2>&1; then
    HAVE_CURL=0
    echo "UWAGA: brak curl — po restarcie pominę sprawdzenie $HEALTH_URL (apt install curl)."
fi

echo "=== SZUP — wdrożenie ==="
echo "Katalog danych: $DATA_DIR"
echo "Baza danych: ${DB:-(poza SQLite — bez kopii)}"
echo ""

# 0. Audyt bezpieczeństwa zależności (NIS2) — nie blokuje deployu, ale ostrzega.
if [ -x "./deploy/audit-deps.sh" ] && [ "${SKIP_AUDIT:-0}" != "1" ]; then
    echo "[0/3] Audyt zależności (pip-audit + npm audit)..."
    ./deploy/audit-deps.sh || echo "UWAGA: znalezione podatności — sprawdź deploy/audit-reports/"
    echo ""
fi

# Kopia bazy PRZED zmianą kodu — migracje (ALTER) idą przy restarcie usługi.
# Nieudana kopia przerywa wdrożenie (set -e + jawny exit).
if [ -n "$DB" ] && [ -f "$DB" ]; then
    echo "Kopia bazy danych..."
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/${BACKUP_PREFIX}$(date +%F-%H%M%S).db"
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
    # Zostaw tylko $BACKUP_KEEP najnowszych kopii PRZEDWDROŻENIOWYCH (prefiks
    # $BACKUP_PREFIX — kopii z crona nie ruszamy). Sortujemy po NAZWIE
    # (…-RRRR-MM-DD-GGMMSS.db), a nie po czasie modyfikacji pliku.
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*.db" -printf '%f\n' \
        | sort -r | tail -n +$((BACKUP_KEEP + 1)) \
        | while IFS= read -r old_backup; do rm -f -- "$BACKUP_DIR/$old_backup"; done
    echo ""
elif [ -z "$DB" ]; then
    echo "Baza poza SQLite — pomijam kopię (SZUP_NO_DB_OK=1)."
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

# Prawa do danych i logów: tylko root (instalacje sprzed UMask=0077 w szup.service
# mają pliki 0644 — czytelne dla każdego konta lokalnego, np. www-data).
for d in "$DATA_DIR" "$APP_DIR/logs"; do
    if [ -d "$d" ]; then chmod -R go-rwx "$d"; fi
done
UNIT_FILE="$(systemctl show "$SERVICE" -p FragmentPath --value 2>/dev/null || true)"
if [ -n "$UNIT_FILE" ] && [ -r "$UNIT_FILE" ] && ! grep -q '^UMask=' "$UNIT_FILE"; then
    echo "UWAGA: $UNIT_FILE nie ma UMask=0077 — skopiuj deploy/szup.service"
    echo "       do /etc/systemd/system/ i wykonaj: systemctl daemon-reload"
fi

# 1. Aktualizacja zależności Python (tylko produkcyjne — bez narzędzi testowych)
#    `pip install -r` podnosi każdy pakiet, którego zainstalowana wersja nie
#    spełnia zakresu z requirements.txt (np. nowej dolnej granicy po poprawce
#    bezpieczeństwa), a pozostałych nie rusza. --upgrade-strategy only-if-needed
#    zapisuje to jawnie także dla zależności pośrednich.
echo "[1/3] Aktualizacja zależności Python..."
"$VENV/bin/pip" install --quiet --upgrade-strategy only-if-needed -r backend/requirements.txt
"$VENV/bin/pip" check >/dev/null \
    || echo "UWAGA: pip check zgłasza niespójne zależności w $VENV — sprawdź: $VENV/bin/pip check"

# 2. Kopiowanie backendu — bez testów, lokalnego venv i plików kompilacji.
#    --delete-excluded usuwa też te katalogi z poprzednich wdrożeń.
#    Dane i sekrety (data/, .env*, *.db*, *.key) są wykluczone ORAZ chronione
#    (P = protect): nigdy nie trafiają tu z checkoutu (np. lokalna baza
#    deweloperska) i nigdy nie są kasowane po stronie serwera przez --delete.
#    Kod należy do roota (--chown) z prawami 755/644: konto, do którego należy
#    checkout, nie może potem podmienić kodu uruchamianego przez usługę.
echo "[2/3] Kopiowanie backendu..."
rsync -a --delete --delete-excluded --chown=root:root --chmod=D755,F644 \
    --filter 'P /data/' --filter 'P .env*' --filter 'P *.db*' --filter 'P *.key' \
    --exclude '/data/' --exclude '.env*' --exclude '*.db*' --exclude '*.key' \
    --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.pytest_cache/' --exclude 'tests/' --exclude 'requirements-dev.txt' \
    backend/ "$APP_DIR/backend/"

# 3. Kopiowanie frontendu
echo "[3/3] Kopiowanie frontendu..."
if [ ! -d "frontend/dist" ]; then
    echo "BŁĄD: Brak katalogu frontend/dist — zbuduj frontend lokalnie: cd frontend && npm run build"
    exit 1
fi
rsync -a --delete --chown=root:root --chmod=D755,F644 frontend/dist/ "$WEBROOT/"

# Restart usługi i sprawdzenie, czy faktycznie odpowiada (migracje idą przy starcie).
# Nieudany restart nie kończy skryptu od razu (set -e) — niżej sprawdzenie
# usługi i komunikat ze ścieżką kopii bazy.
echo "Restart usługi $SERVICE..."
RESTART_OK=1
systemctl restart "$SERVICE" || RESTART_OK=0
[ "$RESTART_OK" = "1" ] || echo "UWAGA: systemctl restart $SERVICE zakończył się błędem."

if [ "$HAVE_CURL" != "1" ]; then
    echo "UWAGA: brak curl — pomijam sprawdzenie usługi. Sprawdź ręcznie:"
    echo "       systemctl status $SERVICE; tail -n 40 $APP_DIR/logs/app.log"
    if [ "$RESTART_OK" != "1" ]; then
        echo "Kopia bazy sprzed wdrożenia: ${BACKUP_FILE:-brak} (przywracanie: README, sekcja Przywracanie kopii)."
        exit 1
    fi
else
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
        echo "Kopia bazy sprzed wdrożenia: ${BACKUP_FILE:-brak} (przywracanie: README, sekcja Przywracanie kopii)."
        exit 1
    fi
    RUNNING_VERSION="$(printf '%s' "$HEALTH" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    echo "  → usługa działa, wersja $RUNNING_VERSION"
    if [ -n "$EXPECTED_VERSION" ] && [ "$RUNNING_VERSION" != "$EXPECTED_VERSION" ]; then
        echo "UWAGA: oczekiwano wersji $EXPECTED_VERSION — sprawdź, czy skopiowano właściwy kod."
    fi
fi
echo ""
echo "=== Wdrożenie zakończone ==="
echo "Logi: tail -f $APP_DIR/logs/app.log"
