#!/usr/bin/env bash
# audit-deps.sh — Skan zależności pod kątem CVE (NIS2 Art. 21 ust. 2 lit. d)
# Uruchom lokalnie przed deploymentem lub w CI.
#
# Kody wyjścia:
#   0 — brak podatności
#   1 — znalezione podatności (patrz raport)
#   2 — błąd uruchomienia narzędzi
set -uo pipefail

REPORT_DIR="${REPORT_DIR:-./deploy/audit-reports}"
mkdir -p "$REPORT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

PY_REPORT="$REPORT_DIR/pip-audit-$STAMP.json"
NPM_REPORT="$REPORT_DIR/npm-audit-$STAMP.json"

EXIT=0

echo "=== [1/2] pip-audit (backend) ==="
if ! command -v pip-audit >/dev/null 2>&1; then
    echo "Instaluję pip-audit..."
    python3 -m pip install --quiet --user pip-audit || { echo "Nie udało się zainstalować pip-audit"; exit 2; }
fi

if pip-audit -r backend/requirements.txt --format json --output "$PY_REPORT"; then
    echo "pip-audit OK — raport: $PY_REPORT"
else
    rc=$?
    echo "pip-audit: znalezione podatności (rc=$rc) — raport: $PY_REPORT"
    pip-audit -r backend/requirements.txt || true
    EXIT=1
fi

echo ""
echo "=== [2/2] npm audit (frontend) ==="
if [ ! -d "frontend/node_modules" ]; then
    echo "Brak frontend/node_modules — uruchamiam npm ci..."
    (cd frontend && npm ci --silent) || { echo "npm ci nie powiodło się"; exit 2; }
fi

(cd frontend && npm audit --omit=dev --json) > "$NPM_REPORT" || EXIT=1
if [ "$EXIT" -ne 0 ]; then
    echo "npm audit: znalezione podatności — raport: $NPM_REPORT"
    (cd frontend && npm audit --omit=dev) || true
else
    echo "npm audit OK — raport: $NPM_REPORT"
fi

echo ""
if [ "$EXIT" -eq 0 ]; then
    echo "=== Audyt zależności zakończony: OK ==="
else
    echo "=== Audyt zależności: UWAGA — znalezione podatności ==="
    echo "Przejrzyj raporty w: $REPORT_DIR"
fi

exit $EXIT
