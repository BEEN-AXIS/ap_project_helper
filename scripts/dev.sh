#!/usr/bin/env bash
# Runs the API (auto-reload) and the Vite dev server together.
# - picks free ports (8000 and 5173 unless taken; set API_PORT / WEB_PORT to choose)
# - starts the web app only once the API answers its health check
# - if either side stops, the other is stopped too; Ctrl-C stops both
# Written for the bash 3.2 that ships with macOS.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "run 'make setup' first" >&2; exit 1; }

API_PORT="$("$PY" "$ROOT/scripts/ports.py" "${API_PORT:-8000}" API)" || exit 1
WEB_PORT="$("$PY" "$ROOT/scripts/ports.py" "${WEB_PORT:-5173}" "web app")" || exit 1

# Job control gives each child its own process group, so stopping them never
# signals make or this shell (the old version took make down with it).
set -m
API_PID=""
WEB_PID=""
stop_all() {
  trap - EXIT INT TERM
  for pid in $WEB_PID $API_PID; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  wait 2>/dev/null
}
trap 'echo; echo "Stopping AlgoArena..."; stop_all; exit 0' INT TERM
trap stop_all EXIT

# stdin from /dev/null: a background process reading the terminal would be suspended.
(cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload --reload-dir app --reload-dir ../shared) </dev/null &
API_PID=$!

printf "Waiting for the API on :%s " "$API_PORT"
up=""
for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo
    echo "  ! The API did not start; its error is printed above." >&2
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:$API_PORT/api/healthz" 2>/dev/null | grep -q '"problems"'; then
    up=1
    break
  fi
  printf "."
  sleep 0.5
done
echo
[ -n "$up" ] || { echo "  ! The API did not answer within 30 seconds; its error is printed above." >&2; exit 1; }

(cd "$ROOT/frontend" && ALGOARENA_API_PORT="$API_PORT" exec npm run dev -- --host 127.0.0.1 --port "$WEB_PORT" --strictPort) </dev/null &
WEB_PID=$!
sleep 2

echo
echo "  AlgoArena  ->  http://127.0.0.1:$WEB_PORT   (API on :$API_PORT)"
echo "  demo logins: alice / alice-pass, bob / bob-pass, admin / admin-pass"
echo "  Ctrl-C stops both."
echo

while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 1; done
if kill -0 "$API_PID" 2>/dev/null; then echo "  ! The web app stopped; stopping the API too." >&2; else echo "  ! The API stopped; stopping the web app too." >&2; fi
exit 1
