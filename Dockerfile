# AlgoArena API + built web app in one image.
#   docker compose up --build      (see docker-compose.yml)

# ---- web app ----
FROM node:22-slim AS web
WORKDIR /src
COPY shared ./shared
COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && (npm ci || npm install)
COPY frontend ./frontend
RUN cd frontend && npm run build

# ---- api ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# The Docker CLI lets the API start sibling judge containers through the
# mounted socket. Read the Docker socket warning in the README first.
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY shared ./shared
COPY backend ./backend
COPY --from=web /src/frontend/dist ./frontend/dist
WORKDIR /app/backend
ENV FRONTEND_DIST=/app/frontend/dist SHARED_DIR=/app/shared
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD curl -fsS http://127.0.0.1:8000/api/healthz || exit 1
CMD ["sh", "-c", "python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
