#!/usr/bin/env bash
# Starts a throwaway AlgoArena server for the Playwright suite:
# fresh SQLite file, FakeRunner judge, fast bots, built SPA served by the API.
set -euo pipefail
PORT="${1:-8010}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
DB_DIR="$(mktemp -d)"
export ENV=test JUDGE_BACKEND=fake BOT_TIME_SCALE=0.02 LOG_LEVEL=WARNING
export DATABASE_URL="sqlite:///$DB_DIR/e2e.db"
export FRONTEND_DIST="$ROOT/frontend/dist"
[ -f "$FRONTEND_DIST/index.html" ] || { echo "build the web app first: make build" >&2; exit 1; }
cd "$ROOT/backend"
"$PY" -m app.seed
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
