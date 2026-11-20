# AlgoArena: run `make help` for the list.
#   First run:  make setup && make dev   ->  http://127.0.0.1:5173
SHELL   := /bin/bash
PYTHON  ?= python3
VENV    := backend/.venv
# Quoted so the repo works from folders with spaces in their path.
PY      := "$(CURDIR)/$(VENV)/bin/python"
NPM     ?= npm

.DEFAULT_GOAL := help
.PHONY: help setup dev demo seed seed-check test test-backend test-frontend types types-check \
        build typecheck lint e2e judge-image load migrate migration audit docker clean

help: ## List the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV)/.installed: backend/requirements.txt backend/requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements-dev.txt
	@touch $@

frontend/node_modules/.installed: frontend/package.json
	cd frontend && $(NPM) install
	@touch $@

setup: $(VENV)/.installed frontend/node_modules/.installed ## Create the venv, install packages, seed the database
	@[ -f .env ] || cp .env.example .env
	cd backend && $(PY) -m app.seed

dev: ## API on :8000 (auto-reload) + Vite on :5173
	@bash scripts/dev.sh

demo: build ## Five-minute demo: ENV=test, fake judge, fast bots, one origin on :8000
	@PORT=$$($(PY) scripts/ports.py $${DEMO_PORT:-8000} "demo server") || exit 1; \
	echo "Demo mode on http://127.0.0.1:$$PORT  (fake judge: put '# VERDICT: AC' in your code; bots solve in seconds)"; \
	cd backend && export ENV=test JUDGE_BACKEND=fake BOT_TIME_SCALE=0.02 DATABASE_URL=sqlite:///demo.db && \
	  $(PY) -m app.seed && exec $(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $$PORT

seed: ## Validate skins, load problems, demo users and bots (idempotent)
	cd backend && $(PY) -m app.seed

seed-check: ## Run every reference solution through the judge
	cd backend && $(PY) -m app.seed_check

test: test-backend test-frontend types-check ## All unit, engine, API and judge tests

test-backend: ## pytest (rules, engine, API, judge, sandbox escape suite)
	cd backend && $(PY) -m pytest

test-frontend: ## Vitest (reducer golden match, director timings, skin validator)
	cd frontend && $(NPM) test

types: ## Regenerate frontend/src/net/protocol.generated.ts from the Pydantic models
	$(PY) scripts/make_types.py

types-check: ## Fail if the generated TypeScript types are stale
	$(PY) scripts/make_types.py --check

build: frontend/node_modules/.installed ## Build the web app into frontend/dist
	cd frontend && $(NPM) run build

typecheck: ## Strict TypeScript check of the web app
	cd frontend && $(NPM) run typecheck

lint: ## Ruff, mypy (strict on domain/), ESLint, tsc
	cd backend && $(PY) -m ruff check app tests && $(PY) -m mypy app/domain
	cd frontend && $(NPM) run lint && $(NPM) run typecheck

e2e: build ## Playwright: two browser contexts play a ranked match
	cd e2e && $(NPM) install && npx playwright install chromium && PYTHON=$(PY) npx playwright test

judge-image: ## Build the Docker judge image (algoarena-judge:latest)
	docker build -t algoarena-judge:latest -f backend/app/judge/Dockerfile.judge backend/app/judge

load: ## 50 simultaneous bot-vs-bot matches in one process
	$(PY) scripts/load_test.py 50

migrate: ## Apply Alembic migrations (the server also does this on start)
	cd backend && $(PY) -m alembic upgrade head

migration: ## New Alembic migration from model changes: make migration m="add column x"
	cd backend && $(PY) -m alembic revision --autogenerate -m "$(m)"

audit: ## Dependency audit (release checklist)
	$(PY) -m pip_audit -r backend/requirements.txt
	cd frontend && $(NPM) audit --omit=dev

docker: ## docker compose up --build
	docker compose up --build

clean: ## Remove build output and local databases (keeps the venv and node_modules)
	rm -rf frontend/dist backend/algoarena.db* backend/demo.db* e2e/test-results e2e/playwright-report
