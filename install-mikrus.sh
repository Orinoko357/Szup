#!/bin/bash
# ============================================================
#  SZUP — Instalator dla Mikrus (port 20189)
#  Uruchom jako root: bash install-mikrus.sh
# ============================================================
set -euo pipefail

APP_DIR="/opt/szup"
APP_PORT=40273
DB_NAME="szup_db"
DB_USER="szup_user"
PDF_DIR="/opt/szup-pdf"
LOG_DIR="/opt/szup-logs"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
die()  { echo -e "${RED}[BŁĄD]${NC} $1"; exit 1; }

echo "======================================================"
echo "  SZUP — Instalator (port $APP_PORT)"
echo "======================================================"
echo ""

# ── 0. Sprawdź czy port jest wolny
if ss -tlnp 2>/dev/null | grep -q ":$APP_PORT " || netstat -tlnp 2>/dev/null | grep -q ":$APP_PORT "; then
  die "Port $APP_PORT jest już zajęty! Sprawdź: ss -tlnp | grep $APP_PORT"
fi
ok "Port $APP_PORT wolny"

# ── 1. Node.js 20
if ! command -v node &>/dev/null || [[ "$(node -e 'process.stdout.write(process.version.split(".")[0].slice(1))')" -lt 18 ]]; then
  warn "Instaluję Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
ok "Node.js $(node --version)"

# ── 2. PM2
if ! command -v pm2 &>/dev/null; then
  warn "Instaluję PM2..."
  npm install -g pm2
fi
ok "PM2 $(pm2 --version)"

# ── 3. PostgreSQL
if ! command -v psql &>/dev/null; then
  warn "Instaluję PostgreSQL..."
  apt-get install -y postgresql postgresql-contrib
fi
if ! systemctl is-active --quiet postgresql; then
  systemctl start postgresql
  systemctl enable postgresql
fi
ok "PostgreSQL aktywny"

# ── 4. Baza danych
DB_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
if sudo -u postgres psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw "$DB_NAME"; then
  warn "Baza $DB_NAME już istnieje — pomijam tworzenie"
  # Odczytaj hasło z .env jeśli istnieje
  if [[ -f "$APP_DIR/backend/.env" ]]; then
    DB_PASS=$(grep DATABASE_URL "$APP_DIR/backend/.env" 2>/dev/null | sed 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/' || echo "$DB_PASS")
  fi
else
  sudo -u postgres psql <<SQL
CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';
CREATE DATABASE $DB_NAME OWNER $DB_USER;
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
SQL
  ok "Baza danych $DB_NAME utworzona"
fi

# ── 5. Klonuj/aktualizuj repozytorium
if [[ -d "$APP_DIR/.git" ]]; then
  warn "Katalog $APP_DIR istnieje — aktualizuję (git pull)..."
  cd "$APP_DIR"
  git pull origin claude/build-permissions-system-ZpzBN 2>/dev/null || git pull 2>/dev/null || warn "git pull nie powiódł się, używam istniejącego kodu"
else
  warn "Klonuję repozytorium..."
  # Jeśli brak git repo — skopiuj z lokalnego (tar)
  if [[ -d "/root/szup-src" ]]; then
    cp -r /root/szup-src "$APP_DIR"
  else
    die "Brak repozytorium! Skopiuj kod do $APP_DIR lub ustaw git remote."
  fi
fi
ok "Kod aplikacji gotowy w $APP_DIR"

# ── 6. Katalogi
mkdir -p "$PDF_DIR" "$LOG_DIR"
ok "Katalogi: $PDF_DIR, $LOG_DIR"

# ── 7. Generuj klucze i .env
if [[ -f "$APP_DIR/backend/.env" ]]; then
  warn ".env już istnieje — nie nadpisuję"
else
  JWT_SECRET=$(node -e "process.stdout.write(require('crypto').randomBytes(64).toString('hex'))")
  JWT_REFRESH=$(node -e "process.stdout.write(require('crypto').randomBytes(64).toString('hex'))")
  LDAP_KEY=$(node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))")
  SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

  cat > "$APP_DIR/backend/.env" <<ENV
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}
JWT_SECRET=${JWT_SECRET}
JWT_REFRESH_SECRET=${JWT_REFRESH}
LDAP_ENCRYPTION_KEY=${LDAP_KEY}
PDF_STORAGE_PATH=${PDF_DIR}
LOG_PATH=${LOG_DIR}
PORT=${APP_PORT}
ALLOWED_ORIGIN=http://${SERVER_IP}:${APP_PORT}
NODE_ENV=production
SCHEDULER_ENABLED=true
ENV
  ok ".env wygenerowany"
fi

# ── 8. npm install — backend
cd "$APP_DIR/backend"
npm install --production
ok "Backend: npm install"

# ── 9. npm install + build — frontend
cd "$APP_DIR/frontend"
npm install
npm run build
ok "Frontend: zbudowany → backend/public/"

# ── 10. Migracje
cd "$APP_DIR/backend"
node src/migrations/run.js
ok "Migracje bazy danych"

# ── 11. PM2 — start lub reload
cd "$APP_DIR"
if pm2 list 2>/dev/null | grep -q "szup-backend"; then
  pm2 reload ecosystem.config.js --env production
  ok "PM2: szup-backend przeładowany"
else
  # Popraw port w ecosystem.config.js
  sed -i "s/PORT: 3001/PORT: $APP_PORT/" ecosystem.config.js 2>/dev/null || true
  pm2 start ecosystem.config.js --env production
  ok "PM2: szup-backend uruchomiony"
fi
pm2 save

# ── 12. Autostart
pm2 startup systemd -u root --hp /root 2>/dev/null | tail -1 | bash 2>/dev/null || \
  warn "Autostart PM2: uruchom ręcznie 'pm2 startup' i wklej wyświetloną komendę"

# ── 13. Sprawdź
sleep 2
if curl -sf http://localhost:$APP_PORT/api/health &>/dev/null; then
  SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo ""
  echo "======================================================"
  ok "SZUP działa!"
  echo -e "  Adres:  ${GREEN}http://${SERVER_IP}:${APP_PORT}${NC}"
  echo "======================================================"
  echo ""
  echo "Następny krok — utwórz konto SUPERADMIN:"
  echo "  cd $APP_DIR/backend && node scripts/init-superadmin.js"
else
  warn "Aplikacja nie odpowiada na porcie $APP_PORT. Sprawdź logi:"
  echo "  pm2 logs szup-backend --lines 30"
fi
