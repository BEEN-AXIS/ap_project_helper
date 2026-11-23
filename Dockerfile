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
FROM node:22-slim
# The Docker CLI lets the API start sibling judge containers through the
# mounted socket. Read the Docker socket warning in the README first.
# OpenSSL is for Prisma's query engine.
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io curl openssl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/package.json server/package-lock.json* ./server/
RUN cd server && (npm ci --omit=dev || npm install --omit=dev) && npm install --no-save prisma
COPY shared ./shared
COPY server ./server
RUN cd server && npx prisma generate
COPY --from=web /src/frontend/dist ./frontend/dist
WORKDIR /app/server
ENV NODE_ENV=production FRONTEND_DIST=/app/frontend/dist SHARED_DIR=/app/shared HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD curl -fsS http://127.0.0.1:8000/api/healthz || exit 1
CMD ["sh", "-c", "npx prisma migrate deploy && node scripts/seed.js && exec node src/index.js"]
