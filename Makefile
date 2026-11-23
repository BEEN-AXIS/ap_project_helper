# AlgoArena: run `make help` for the list.
#   First run:  make setup && make dev   ->  http://127.0.0.1:5173
#   Needs Node.js 20+ and PostgreSQL (or DATABASE_URL=memory for a throwaway database).
SHELL   := /bin/bash
NPM     ?= npm
# Prisma's CLI reads DATABASE_URL from the environment: export the repo's .env first.
LOADENV := set -a; [ ! -f ../.env ] || . ../.env; set +a;

.DEFAULT_GOAL := help
.PHONY: help setup dev demo seed seed-check test test-server test-judge test-frontend types types-check \
        build typecheck lint e2e judge-image load migrate migration audit docker clean

help: ## List the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

server/node_modules/.installed: server/package.json
	cd server && $(NPM) install && npx prisma generate
	@touch $@

frontend/node_modules/.installed: frontend/package.json
	cd frontend && $(NPM) install
	@touch $@

setup: server/node_modules/.installed frontend/node_modules/.installed ## Install packages, migrate and seed the database
	@[ -f .env ] || cp .env.example .env
	cd server && $(LOADENV) \
	  if [ "$${DATABASE_URL#memory}" = "$$DATABASE_URL" ]; then npx prisma migrate deploy && node scripts/seed.js; \
	  else echo "DATABASE_URL=memory: nothing to migrate; the server seeds on start"; fi

dev: ## API on :8000 (auto-reload) + Vite on :5173
	@bash scripts/dev.sh

demo: build ## Five-minute demo: ENV=test, fake judge, fast bots, in-memory database, one origin on :8000
	@PORT=$$(node server/scripts/ports.js $${DEMO_PORT:-8000} "demo server") || exit 1; \
	echo "Demo mode on http://127.0.0.1:$$PORT  (fake judge: put '# VERDICT: AC' in your code; bots solve in seconds)"; \
	cd server && export ENV=test JUDGE_BACKEND=fake BOT_TIME_SCALE=0.02 DATABASE_URL=memory PORT=$$PORT && exec node src/index.js

seed: ## Validate skins, load problems, demo users and bots (idempotent)
	cd server && $(LOADENV) node scripts/seed.js

seed-check: ## Run every reference solution through the judge
	cd server && node scripts/seed-check.js

test: test-server test-judge test-frontend types-check ## All unit, engine, API and judge tests

test-server: ## node:test (rules, engine, protocol, API over HTTP and WebSockets, migrations)
	cd server && $(NPM) test

test-judge: ## The judge with real python3 and g++, and the sandbox escape suite
	cd server && $(NPM) run test:judge

test-frontend: ## Vitest (reducer golden match, director timings, skin validator)
	cd frontend && $(NPM) test

types: ## Regenerate frontend/src/net/protocol.generated.ts from server/src/realtime/protocol.js
	cd server && node scripts/make-types.js

types-check: ## Fail if the generated TypeScript types are stale
	cd server && node scripts/make-types.js --check

build: frontend/node_modules/.installed ## Build the web app into frontend/dist
	cd frontend && $(NPM) run build

typecheck: ## Strict TypeScript check of the web app
	cd frontend && $(NPM) run typecheck

lint: ## ESLint and tsc for the web app; node --check for the server
	cd server && find src scripts -name '*.js' -print0 | xargs -0 -n1 node --check
	cd frontend && $(NPM) run lint && $(NPM) run typecheck

e2e: build ## Playwright: two browser contexts play a ranked match
	cd e2e && $(NPM) install && npx playwright install chromium && npx playwright test

judge-image: ## Build the Docker judge image (algoarena-judge:latest)
	docker build -t algoarena-judge:latest -f server/src/judge/harness/Dockerfile.judge server/src/judge/harness

load: ## 50 simultaneous bot-vs-bot matches in one process
	cd server && node scripts/load-test.js 50

migrate: ## Apply the Prisma migrations to DATABASE_URL
	cd server && $(LOADENV) npx prisma migrate deploy

migration: ## New Prisma migration from schema changes: make migration m=add_column_x
	cd server && $(LOADENV) npx prisma migrate dev --name "$(m)"

audit: ## Dependency audit (release checklist)
	cd server && $(NPM) audit --omit=dev
	cd frontend && $(NPM) audit --omit=dev

docker: ## docker compose up --build
	docker compose up --build

clean: ## Remove build output (keeps node_modules)
	rm -rf frontend/dist e2e/test-results e2e/playwright-report
