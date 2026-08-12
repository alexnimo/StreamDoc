# syntax=docker/dockerfile:1.7
#
# StreamDoc Dockerfile — EXPERIMENTAL
#
# WARNING: This Docker setup has not been tested in production. It is provided
# as a starting point for containerized deployments. The NotebookLM browser
# login flow requires a host-side `notebooklm login` + volume mount (see
# docs/integrations-auth.md and README.md "NotebookLM login" section).
#
# See docker-compose.yml for the recommended volume mounts.

# ── Stage 1: build the React frontend ─────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Vite builds into ../src/streamdoc/api/static (see vite.config.ts outDir)
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="streamdoc" \
      org.opencontainers.image.title="StreamDoc" \
      org.opencontainers.image.description="YouTube → PDF pipeline with NotebookLM integration (experimental Docker)"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMDOC_ENV=container \
    STREAMDOC_API_HOST=0.0.0.0 \
    STREAMDOC_API_PORT=5454

# System deps: ffmpeg for media/frame extraction, git for yt-dlp updates,
# curl + ca-certificates for downloads. libsndfile1 helps faster-whisper audio decode.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

# Install Playwright Chromium so NotebookLM (headless, storage_state mode) works.
# Reason: notebooklm-py drives a browser even when reading a stored session.
# Skip by setting STREAMDOC_NOTEBOOKLM_ENABLED=false if you don't need it.
RUN pip install playwright \
    && playwright install chromium --with-deps \
    && rm -rf /var/lib/apt/lists/*

# Application source + shipped sample prompts (read-only in the image)
COPY src ./src
COPY assets ./assets
COPY tests ./tests

# Built frontend from Stage 1 -> served by FastAPI in production mode.
# Reason: vite.config.ts sets outDir to ../src/streamdoc/api/static, which from
# WORKDIR /ui resolves to /src/streamdoc/api/static in the frontend stage.
COPY --from=frontend /src/streamdoc/api/static ./src/streamdoc/api/static

# Runtime dirs (writable by non-root user). data/ and config/ are volumes.
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/data/State /app/data/Media /app/data/Outputs \
                /app/data/Models /app/data/integrations/notebooklm /app/data/cookies \
                /app/config/integrations/notebooklm /app/config/prompts/notebooklm \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5454

# Reason: streamdoc-api entrypoint reads STREAMDOC_API_HOST/PORT env vars.
# Reload is auto-disabled when STREAMDOC_ENV=container (see api/app.py:run).
CMD ["streamdoc-api"]
