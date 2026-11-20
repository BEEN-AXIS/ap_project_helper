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

# No job control: everything stays in the terminal's foreground group, so Ctrl-C
# reaches this script. Background children ignore SIGINT, so the trap stops them
# (and their children: the uvicorn worker, Vite under npm) by PID.
API_PID=""
WEB_PID=""
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill -TERM "$pid" 2>/dev/null || true
}
stop_all() {
  trap - EXIT INT TERM
  for pid in $WEB_PID $API_PID; do kill_tree "$pid"; done
  for _ in 1 2 3 4 5 6; do
    alive=""
    for pid in $WEB_PID $API_PID; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [ -z "$alive" ] && return
    sleep 0.5
  done
  for pid in $WEB_PID $API_PID; do kill -KILL "$pid" 2>/dev/null || true; done
}
trap 'echo; echo "Stopping AlgoArena..."; stop_all; echo "Stopped."; exit 0' INT TERM
trap stop_all EXIT

# stdin from /dev/null: the servers never read the terminal.
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
