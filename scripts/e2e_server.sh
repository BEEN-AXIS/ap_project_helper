#!/usr/bin/env bash
# Starts a throwaway AlgoArena server for the Playwright suite:
# in-memory database (seeded on start), fake judge, fast bots, built SPA served by the API.
set -euo pipefail
PORT="${1:-8010}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ENV=test JUDGE_BACKEND=fake BOT_TIME_SCALE=0.02 LOG_LEVEL=WARNING DATABASE_URL=memory
export FRONTEND_DIST="$ROOT/frontend/dist" PORT HOST=127.0.0.1
[ -f "$FRONTEND_DIST/index.html" ] || { echo "build the web app first: make build" >&2; exit 1; }
cd "$ROOT/server"
exec node src/index.js
