#!/bin/bash
# ============================================================
#  SZUP v2 — Instalator (Python/FastAPI + SQLite)
#  Uruchom jako root: bash install-mikrus.sh
# ============================================================
set -euo pipefail

APP_DIR="/opt/szup"
APP_PORT=40273
PDF_DIR="/opt/szup-pdf"
LOG_DIR="/opt/szup-logs"
DATA_DIR="/opt/szup/data"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
die()  { echo -e "${RED}[BŁĄD]${NC} $1"; exit 1; }

echo "======================================================"
echo "  SZUP v2 — Instalator (port $APP_PORT)"
echo "======================================================"
echo ""

# ── 0. Sprawdź port
if ss -tlnp 2>/dev/null | grep -q ":$APP_PORT " || netstat -tlnp 2>/dev/null | grep -q ":$APP_PORT "; then
  die "Port $APP_PORT jest już zajęty! Sprawdź: ss -tlnp | grep $APP_PORT"
fi
ok "Port $APP_PORT wolny"

# ── 1. Python 3.11+
if ! command -v python3 &>/dev/null || python3 -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
  warn "Instaluję Python 3.11..."
  apt-get update -qq
  apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
fi
PYTHON=$(command -v python3.11 || command -v python3)
ok "Python $($PYTHON --version)"

# ── 2. Node.js 20 (dla frontendu)
if ! command -v node &>/dev/null || [[ "$(node -e 'process.stdout.write(process.version.split(".")[0].slice(1))')" -lt 18 ]]; then
  warn "Instaluję Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
ok "Node.js $(node --version)"

# ── 3. PM2
if ! command -v pm2 &>/dev/null; then
  warn "Instaluję PM2..."
  npm install -g pm2
fi
ok "PM2 $(pm2 --version)"

# ── 4. Klonuj/aktualizuj repo
if [[ -d "$APP_DIR/.git" ]]; then
  warn "Aktualizuję repo (git pull)..."
  cd "$APP_DIR"
  git pull origin claude/build-permissions-system-ZpzBN 2>/dev/null || git pull 2>/dev/null || warn "git pull nie powiódł się"
else
  warn "Klonuję repozytorium..."
  if [[ -d "/root/szup-src" ]]; then
    cp -r /root/szup-src "$APP_DIR"
  else
    die "Brak repozytorium! Skopiuj kod do $APP_DIR lub ustaw git remote."
  fi
fi
ok "Kod gotowy w $APP_DIR"

# ── 5. Katalogi
mkdir -p "$PDF_DIR" "$LOG_DIR" "$DATA_DIR"
ok "Katalogi: $PDF_DIR, $LOG_DIR, $DATA_DIR"

# ── 6. Generuj .env
if [[ -f "$APP_DIR/backend-py/.env" ]]; then
  warn ".env już istnieje — nie nadpisuję"
else
  JWT_SECRET=$($PYTHON -c "import secrets; print(secrets.token_hex(64))")
  JWT_REFRESH=$($PYTHON -c "import secrets; print(secrets.token_hex(64))")
  LDAP_KEY=$($PYTHON -c "import secrets; print(secrets.token_hex(32))")
  SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

  cat > "$APP_DIR/backend-py/.env" <<ENV
DATABASE_URL=sqlite:///${DATA_DIR}/szup.db
JWT_SECRET=${JWT_SECRET}
JWT_REFRESH_SECRET=${JWT_REFRESH}
LDAP_ENCRYPTION_KEY=${LDAP_KEY}
PDF_STORAGE_PATH=${PDF_DIR}
LOG_PATH=${LOG_DIR}
PORT=${APP_PORT}
ALLOWED_ORIGIN=http://${SERVER_IP}:${APP_PORT}
SCHEDULER_ENABLED=true
ENV
  ok ".env wygenerowany"
fi

# ── 7. Python venv + dependencies
cd "$APP_DIR/backend-py"
if [[ ! -d "venv" ]]; then
  $PYTHON -m venv venv
fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
ok "Backend Python: zależności zainstalowane"

# ── 8. Inicjalizacja bazy danych
python scripts/init_db.py
ok "Baza danych zainicjalizowana"

# ── 9. npm install + build frontendu
cd "$APP_DIR/frontend"
npm install
npm run build
ok "Frontend: zbudowany → backend-py/public/"

# ── 10. Utwórz konto SUPERADMIN
SADMIN_USER="admin"
SADMIN_PASS="Admin@Szup2025!!"
cd "$APP_DIR/backend-py"
source venv/bin/activate
python scripts/init_superadmin.py "$SADMIN_USER" "$SADMIN_PASS" 2>/dev/null || warn "Konto admin już istnieje"
ok "Konto superadmin: $SADMIN_USER"

# ── 11. PM2 — start lub reload
cd "$APP_DIR"
# Zaktualizuj ścieżkę uvicorn do venv
UVICORN_PATH="$APP_DIR/backend-py/venv/bin/uvicorn"
sed -i "s|uvicorn|$UVICORN_PATH|" ecosystem.config.js 2>/dev/null || true

if pm2 list 2>/dev/null | grep -q "szup-backend"; then
  pm2 reload ecosystem.config.js
  ok "PM2: szup-backend przeładowany"
else
  pm2 start ecosystem.config.js
  ok "PM2: szup-backend uruchomiony"
fi
pm2 save

# ── 12. Autostart
pm2 startup systemd -u root --hp /root 2>/dev/null | tail -1 | bash 2>/dev/null || \
  warn "Autostart PM2: uruchom ręcznie 'pm2 startup' i wklej wyświetloną komendę"

# ── 13. Test
sleep 3
if curl -sf http://localhost:$APP_PORT/api/health &>/dev/null; then
  SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo ""
  echo "======================================================"
  ok "SZUP działa!"
  echo -e "  Adres:  ${GREEN}http://${SERVER_IP}:${APP_PORT}${NC}"
  echo -e "  Login:  ${GREEN}$SADMIN_USER${NC} / $SADMIN_PASS"
  echo "======================================================"
else
  warn "Aplikacja nie odpowiada. Sprawdź logi:"
  echo "  pm2 logs szup-backend --lines 30"
fi
