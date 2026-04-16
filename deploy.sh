#!/bin/bash
# SZUP — Production Deploy Script
# Usage: ./deploy.sh
# Run as root on the production server.
set -euo pipefail

BRANCH="claude/build-permissions-system-ZpzBN"
REPO_URL="http://127.0.0.1:49445/git/Orinoko357/Szup"  # adjust if needed
APP_DIR="/opt/szup"
WWW_DIR="/var/www/szup.intranet.wods.pl"
BACKEND_DIR="$APP_DIR/backend-py"
FRONTEND_DIR="$APP_DIR/frontend"
LOG_DIR="/var/log/szup"
DATA_DIR="$BACKEND_DIR/data"
NGINX_CONF="/etc/nginx/sites-available/szup.intranet.wods.pl"
NGINX_ENABLED="/etc/nginx/sites-enabled/szup.intranet.wods.pl"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
info "Sprawdzanie wymagań..."
command -v git    >/dev/null 2>&1 || error "git nie jest zainstalowany."
command -v python3 >/dev/null 2>&1 || error "python3 nie jest zainstalowany."
command -v pip3   >/dev/null 2>&1 || error "pip3 nie jest zainstalowany."
command -v node   >/dev/null 2>&1 || error "node nie jest zainstalowany."
command -v npm    >/dev/null 2>&1 || error "npm nie jest zainstalowany."
command -v nginx  >/dev/null 2>&1 || error "nginx nie jest zainstalowany."
command -v pm2    >/dev/null 2>&1 || error "pm2 nie jest zainstalowany. Uruchom: npm install -g pm2"

# ── 2. Katalogi ───────────────────────────────────────────────────────────────
info "Tworzenie katalogów..."
mkdir -p "$LOG_DIR" "$DATA_DIR"

# ── 3. Kod źródłowy ───────────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    info "Aktualizacja repozytorium..."
    cd "$APP_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    info "Klonowanie repozytorium..."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 4. Plik .env ──────────────────────────────────────────────────────────────
if [ ! -f "$BACKEND_DIR/.env" ]; then
    info "Tworzenie .env z szablonu..."
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"

    # Generuj losowe sekrety JWT
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(64))")
    JWT_REFRESH=$(python3 -c "import secrets; print(secrets.token_hex(64))")

    sed -i "s|ZMIEN_NA_LOSOWY_CIAG_MIN_64_ZNAKI|$JWT_SECRET|" "$BACKEND_DIR/.env"
    sed -i "s|ZMIEN_NA_INNY_LOSOWY_CIAG_MIN_64_ZNAKI|$JWT_REFRESH|" "$BACKEND_DIR/.env"

    warning "WAŻNE: Zmień hasło admina w pliku $BACKEND_DIR/.env"
    warning "  INIT_SUPERADMIN_PASSWORD=..."
    echo ""
    read -p "Podaj hasło dla konta admin (enter = zostaw domyślne): " ADMIN_PASS
    if [ -n "$ADMIN_PASS" ]; then
        sed -i "s|ZMIEN_HASLO_PRZED_URUCHOMIENIEM|$ADMIN_PASS|" "$BACKEND_DIR/.env"
    fi
else
    info ".env już istnieje — pomijam."
fi

# ── 5. Python — zależności ────────────────────────────────────────────────────
info "Instalacja zależności Python..."
pip3 install -q -r "$BACKEND_DIR/requirements.txt"

# ── 6. Frontend — build ───────────────────────────────────────────────────────
info "Budowanie frontendu..."
cd "$FRONTEND_DIR"
npm install --silent
npm run build

# Dowiązanie symboliczne do /var/www
info "Konfiguracja /var/www..."
mkdir -p "$(dirname "$WWW_DIR")"
ln -sfn "$FRONTEND_DIR/dist" "$WWW_DIR"
info "Dowiązanie: $WWW_DIR -> $FRONTEND_DIR/dist"

# ── 7. Nginx ──────────────────────────────────────────────────────────────────
info "Konfiguracja nginx..."
cp "$APP_DIR/nginx.conf" "$NGINX_CONF"
ln -sfn "$NGINX_CONF" "$NGINX_ENABLED" 2>/dev/null || true

# Usuń domyślną konfigurację nginx jeśli istnieje
[ -f /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default && info "Usunięto domyślny site nginx."

nginx -t || error "Błąd konfiguracji nginx!"
systemctl reload nginx
info "Nginx przeładowany."

# ── 8. PM2 — backend ─────────────────────────────────────────────────────────
info "Konfiguracja PM2..."
cd "$APP_DIR"

pm2 describe szup-backend >/dev/null 2>&1 && pm2 delete szup-backend || true
pm2 start ecosystem.config.js
pm2 save
pm2 startup 2>/dev/null | tail -1 | bash 2>/dev/null || true

# ── 9. Status ─────────────────────────────────────────────────────────────────
echo ""
info "========================================"
info "SZUP zainstalowany pomyślnie!"
info "========================================"
echo ""
pm2 status szup-backend
echo ""
info "URL: http://szup.intranet.wods.pl"
info "Logi: pm2 logs szup-backend"
echo ""

# Poczekaj chwilę i sprawdź health
sleep 3
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:40273/api/health 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
    info "Backend działa poprawnie (HTTP $HTTP_STATUS)"
else
    warning "Backend może nie działać (HTTP $HTTP_STATUS). Sprawdź: pm2 logs szup-backend"
fi
