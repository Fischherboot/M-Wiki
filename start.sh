#!/usr/bin/env bash
# Start-Script für M-WIKI – Lokales Testen.
# Production: systemd nutzen (siehe mwiki.service).

set -eu

cd "$(dirname "$0")"

PORT="${PORT:-3503}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"

if [ -d "venv" ]; then
    # shellcheck source=/dev/null
    source venv/bin/activate
fi

if ! python -c "import fastapi" 2>/dev/null; then
    echo "[M-WIKI] FastAPI nicht gefunden. Lege venv an und installiere requirements:"
    echo "          python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

if [ ! -f "daten.json" ]; then
    echo "[M-WIKI] daten.json fehlt — wird beim ersten Start mit Defaults erzeugt."
fi

# WICHTIG: Mit SQLite WAL-Mode darf man theoretisch mehrere Worker fahren,
# aber bei In-Process Caching (kein Redis) hat jeder Worker eigene State.
# Default = 1 Worker.
echo "[M-WIKI] Start auf ${HOST}:${PORT} (workers=${WORKERS})"
exec uvicorn main:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
