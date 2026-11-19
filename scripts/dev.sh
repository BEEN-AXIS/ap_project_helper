#!/usr/bin/env bash
# Runs the API (auto-reload) and the Vite dev server together; Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "run 'make setup' first" >&2; exit 1; }
cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-dir ../shared) &
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1) &
sleep 2
echo
echo "  AlgoArena  ->  http://127.0.0.1:5173   (API on :8000)"
echo "  demo logins: alice / alice-pass, bob / bob-pass, admin / admin-pass"
echo
wait
