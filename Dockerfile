# SolarVolt container (plan.md §13, task T020). One image serves the API + built UI on :8000.
# Multi-stage: build the Angular app with Node, then assemble a slim Python runtime. Both base
# images are multi-arch (arm64 + amd64) so the same Dockerfile builds for a Pi or an x86 server
# via `docker buildx build --platform linux/amd64,linux/arm64`.
# syntax=docker/dockerfile:1

# ── Stage 1: build the frontend (self-hosted assets, no CDN) ──────────────────
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
# Install deps first (cached unless the lockfile changes), then build.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # → /build/frontend/dist/solarvolt/browser

# ── Stage 2: python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SOLARVOLT_DB_PATH=/data/solarvolt.db

# Non-root service account; data dir for the SQLite DB (mount a volume here).
RUN useradd --system --create-home --uid 10001 solarvolt \
    && mkdir -p /data && chown solarvolt:solarvolt /data

WORKDIR /app/backend

# Backend deps (pymodbus/pyserial/httpx/… are pure-Python wheels — no build toolchain needed).
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# App code. The runtime resolves the repo root from these paths (main.py → parents[2];
# yaml_profile.py → parents[3]), so the on-disk layout must mirror the repo: /app/backend,
# /app/profiles, /app/frontend/dist/solarvolt/browser.
COPY backend/ /app/backend/
COPY profiles/ /app/profiles/
COPY --from=frontend /build/frontend/dist/solarvolt/browser /app/frontend/dist/solarvolt/browser

RUN chown -R solarvolt:solarvolt /app

USER solarvolt
EXPOSE 8000

# Liveness: the API's /api/health (stdlib only, so it works on the slim image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
