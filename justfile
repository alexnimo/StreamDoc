# StreamDoc — task runner (just)
#
# Install just:
#   winget install Casey.Just
#   choco install just
#   cargo install just
#
# List all targets:
#   just --list

# Reason: just defaults to sh, which doesn't exist on Windows.
# Use cmd.exe on Windows (supports && for chaining), sh on Linux/macOS.
# PowerShell-specific targets (stop-api, clean) call powershell explicitly.
set windows-shell := ["cmd.exe", "/c"]
set shell := ["sh", "-cu"]

# Default target — show help
default: help

# Show available targets
help:
    @echo "StreamDoc targets (just <target>)"
    @echo ""
    @echo "  Setup"
    @echo "    just install              sync Python deps (uv sync --extra dev)"
    @echo "    just install-social-tools install social CLI backends (twitter + rdt)"
    @echo "    just verify-social-tools  verify twitter and rdt binaries are on PATH"
    @echo "    just build-ui             build React frontend into src/streamdoc/api/static"
    @echo ""
    @echo "  Run"
    @echo "    just dev          API (reload) + Vite dev server (HMR) — two processes"
    @echo "    just dev-mprocs   same as dev but via mprocs TUI (clean process management)"
    @echo "    just prod         build frontend, then single API process serving it on :5454"
    @echo ""
    @echo "  Docker (experimental)"
    @echo "    just docker-up    build + start container"
    @echo "    just docker-logs  tail container logs"
    @echo "    just docker-down  stop and remove container"
    @echo ""
    @echo "  PO Token (YouTube bot detection bypass)"
    @echo "    just pot-up       start PO Token provider container"
    @echo "    just pot-down     stop PO Token provider container"
    @echo "    just pot-logs     tail PO Token container logs"
    @echo "    just pot-status   check if PO Token provider is running"
    @echo ""
    @echo "  Quality"
    @echo "    just test         unit + integration tests (no network)"
    @echo "    just test-live    live tests (requires network + yt-dlp)"
    @echo "    just lint         ruff check"
    @echo "    just format       ruff format --check"
    @echo "    just fmt-fix      ruff format (write)"
    @echo "    just typecheck    mypy"
    @echo "    just clean        remove caches, build artifacts, node_modules"
    @echo ""
    @echo "  Updates"
    @echo "    just update       full update: git pull + deps + tools + rebuild frontend"
    @echo "    just update-check dry-run: show what's outdated without changing anything"
    @echo "    just update-git   git pull only (aborts if dirty)"
    @echo "    just update-deps  sync Python + JS deps"
    @echo "    just update-tools upgrade yt-dlp, ffmpeg-python, faster-whisper, twitter-cli, rdt-cli"
    @echo "    just sync         upgrade + sync all Python packages and uv tools"

# ── Setup ─────────────────────────────────────────────────────────────

# Sync Python dependencies (dev extras, not notebooklm-cookies which pulls rookiepy)
# and install the social CLI backends as persistent user tools.
install: install-social-tools
    uv sync --extra dev

# Install social CLI backends (twitter-cli + rdt-cli) via uv tool install.
# Installing as uv tools places the ``twitter`` and ``rdt`` shims on the
# user's PATH so they are visible to StreamDoc regardless of the active venv.
# The --upgrade flag ensures the latest commit on the default branch is fetched
# and installed on each run, rather than a cached or pinned version.
install-social-tools:
    uv tool install --upgrade git+https://github.com/public-clis/twitter-cli.git
    uv tool install --upgrade git+https://github.com/public-clis/rdt-cli.git

# Verify the social CLI backends are available.
# Use `uv tool run` so the check uses the user-installed tools (which may be
# newer than the project-locked versions) and does not require a new shell.
verify-social-tools:
    @uv tool run --from twitter-cli twitter --version
    @uv tool run --from rdt-cli rdt --version

# Install (if missing) and guide through auth for the social CLI backends,
# then verify connectivity.
setup-social:
    @uv run python scripts/setup_social.py

# Build the React frontend into src/streamdoc/api/static (served by FastAPI in prod).
build-ui:
    cd frontend && npm install && npm run build

# ── Run ───────────────────────────────────────────────────────────────

# Local development: API with reload + Vite dev server (hot reload).
# API on :5454, UI on :5173 (proxies /api to :5454).
# Uses scripts/dev.py for cross-platform clean process management.
# Ctrl-C kills both processes cleanly (no orphans on Windows).
dev:
    uv run python scripts/dev.py

# Same as `just dev` but using mprocs for a TUI with both processes visible.
# Install mprocs: `cargo install mprocs` or `npm install -g mprocs`.
# Ctrl-C kills both processes cleanly.
dev-mprocs:
    mprocs --config mprocs.yaml

# Production-style local run: build frontend once, serve from FastAPI.
# Single process on :5454 — open http://localhost:5454
prod: build-ui
    uv run streamdoc-api

# Kill any orphaned uvicorn/streamdoc-api processes (Windows dev cleanup).
# Also kills leftover multiprocessing.spawn children that keep a handle on
# .venv\Scripts\streamdoc-api.exe open, so uv sync can replace the executable.
stop-api:
    -powershell -File scripts/stop_api.ps1

# ── Docker (experimental — not tested in production) ──────────────────

docker-up:
    docker compose up -d --build

docker-logs:
    docker compose logs -f

docker-down:
    docker compose down

# ── PO Token provider ─────────────────────────────────────────────────

# Start the PO Token provider container manually.
# The app also auto-starts this on startup if Docker is available and
# bypass_mode=po_token. Use this command for manual control or when
# pot_auto_start is disabled.
pot-up:
    docker run -d --name streamdoc-pot --restart unless-stopped -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider:latest

# Stop and remove the PO Token provider container.
pot-down:
    -docker stop streamdoc-pot
    -docker rm streamdoc-pot

# Tail the PO Token provider container logs.
pot-logs:
    docker logs -f streamdoc-pot

# Check if the PO Token provider is running and reachable.
pot-status:
    @uv run python -c "from streamdoc.core.pot_provider import get_pot_provider_status; import json; print(json.dumps(get_pot_provider_status(), indent=2))"

# ── Quality ───────────────────────────────────────────────────────────

test:
    uv run pytest tests -m "not live" -q

test-live:
    uv run pytest tests -m live -v

lint:
    uv run ruff check src tests

format:
    uv run ruff format --check src tests

fmt-fix:
    uv run ruff format src tests

typecheck:
    uv run mypy src

clean:
    -powershell -Command "Get-ChildItem -Path . -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force"
    -powershell -Command "Remove-Item -Recurse -Force .mypy_cache, .pytest_cache, .ruff_cache -ErrorAction SilentlyContinue"
    -powershell -Command "Remove-Item -Recurse -Force frontend/node_modules, frontend/dist, src/streamdoc/api/static -ErrorAction SilentlyContinue"

# ── Updates ───────────────────────────────────────────────────────────

# Full update: git pull + Python deps + JS deps + runtime tools + rebuild frontend.
# Run this after being away from the project or when downloads start failing.
update:
    uv run python scripts/update.py

# Dry-run: show what's outdated without changing anything.
update-check:
    uv run python scripts/update.py --check

# Git pull only (aborts if working tree has uncommitted changes).
update-git:
    uv run python scripts/update.py --skip-deps --skip-tools --skip-frontend

# Sync Python + JS dependencies (no git, no tool upgrade, no rebuild).
update-deps:
    uv run python scripts/update.py --skip-git --skip-tools --skip-frontend

# Upgrade runtime tools only: yt-dlp, ffmpeg-python, faster-whisper.
update-tools:
    uv run python scripts/update.py --skip-git --skip-deps --skip-frontend

# Upgrade lockfile to the latest compatible versions, sync Python deps,
# and upgrade uv-installed tools. Stops the local API first to avoid a
# locked streamdoc-api.exe during uv sync.
sync: stop-api
    uv lock --upgrade
    uv sync --extra dev
    uv tool upgrade
