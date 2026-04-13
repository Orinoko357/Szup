#!/bin/bash
# start.sh — Skrypt uruchomienia/aktualizacji aplikacji SZUP
# Uruchom jako: bash start.sh [dev|prod]
set -euo pipefail

MODE="${1:-prod}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/szup"
PDF_DIR="/var/lib/szup/pdf"

echo "=== SZUP — System Zarządzania Uprawnieniami ==="
echo "Tryb: $MODE | Katalog: $APP_DIR"
echo ""

# ── 1. Sprawdź zależności
check_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "BŁĄD: $1 nie jest zainstalowany"; exit 1; }; }
check_cmd node
check_cmd npm
check_cmd psql
[ "$MODE" = "prod" ] && check_cmd pm2

echo "[1/6] Zależności systemowe: OK"

# ── 2. Zainstaluj/zaktualizuj pakiety npm
echo "[2/6] Instalowanie pakietów backend..."
cd "$APP_DIR/backend" && npm install --production

if [ "$MODE" = "dev" ]; then
  echo "[2/6] Instalowanie pakietów frontend..."
  cd "$APP_DIR/frontend" && npm install
fi

# ── 3. Zbuduj frontend (tylko prod)
if [ "$MODE" = "prod" ]; then
  echo "[3/6] Budowanie frontendu..."
  cd "$APP_DIR/frontend"
  npm install
  npm run build
  echo "       Frontend zbudowany → $APP_DIR/backend/public"
else
  echo "[3/6] Pominięto build frontendu (tryb dev)"
fi

# ── 4. Utwórz katalogi
echo "[4/6] Tworzenie katalogów..."
mkdir -p "$LOG_DIR"
mkdir -p "$PDF_DIR"
chmod 750 "$PDF_DIR"

# ── 5. Uruchom migracje bazy danych
echo "[5/6] Uruchamianie migracji bazy danych..."
cd "$APP_DIR/backend"
if [ ! -f ".env" ]; then
  echo "BŁĄD: Brak pliku .env w $APP_DIR/backend"
  echo "Skopiuj .env.example i uzupełnij zmienne środowiskowe."
  exit 1
fi
node src/migrations/run.js
echo "       Migracje: OK"

# ── 6. Uruchom/zrestartuj aplikację
cd "$APP_DIR"

if [ "$MODE" = "prod" ]; then
  echo "[6/6] Uruchamianie z PM2..."
  if pm2 list | grep -q "szup-backend"; then
    pm2 reload ecosystem.config.js --env production
    echo "       PM2: aplikacja przeładowana"
  else
    pm2 start ecosystem.config.js --env production
    echo "       PM2: aplikacja uruchomiona"
  fi
  pm2 save
  echo ""
  echo "=== Uruchamianie zakończone ==="
  echo "Status: pm2 status"
  echo "Logi:   pm2 logs szup-backend"
  echo "Stop:   pm2 stop szup-backend"
else
  echo "[6/6] Uruchamianie w trybie deweloperskim..."
  echo ""
  echo "Uruchom w osobnych terminalach:"
  echo "  Backend:  cd backend && npm run dev"
  echo "  Frontend: cd frontend && npm run dev"
fi
