# StreamDoc

<p align="center">
  <strong>Local-first YouTube → PDF presentation pipeline, with optional NotebookLM AI generation.</strong>
</p>

---

StreamDoc automates the extraction, processing, and documentation of YouTube channel content. It downloads videos, extracts transcripts, captures key frames with perceptual deduplication, builds structured Markdown/PDF outputs, and can optionally push those reports to [NotebookLM](https://notebooklm.google.com) for AI-generated slide decks, podcasts, infographics, and reports.

A polished React web dashboard lets you manage presets, watch live job progress over SSE, browse generated reports, and control NotebookLM — all from the browser.

## Table of contents

- [Features](#features)
- [LLM-free by default](#llm-free-by-default)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Running the stack](#running-the-stack)
  - [A. Local development (hot reload)](#a-local-development-hot-reload)
  - [B. Local production (single process)](#b-local-production-single-process)
  - [C. Docker (experimental)](#c-docker-experimental)
- [NotebookLM login & browser auth](#notebooklm-login--browser-auth)
- [Social platform setup](#social-platform-setup)
- [Configuration](#configuration)
- [Prompt templates](#prompt-templates)
- [CLI reference](#cli-reference)
- [Updating](#updating)
- [Testing](#testing)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Tech stack](#tech-stack)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## Features

- **Channel Processing** — Resolve channels by URL, `@handle`, or bare channel ID
- **Transcript Extraction** — Official YouTube API first, faster-whisper fallback second (with configurable timeout to prevent job hangs)
- **Frame Capture** — ffmpeg extraction with a configurable multi-stage perceptual dedup pipeline (motion → phash → SSIM → histogram → variance)
- **Output Generation** — Markdown + PDF via reportlab
- **NotebookLM Integration** — Auth, notebook CRUD, content generation, retention policies
- **Scheduled Runs** — APScheduler with cron/interval triggers, driven by each preset's `schedule` field (single source of truth, shared between the Presets and Scheduler pages)
- **Configurable** — Every path and option via `STREAMDOC_` environment variables
- **Bypass Modes** — `po_token` (default, auto-starts a Docker container), `cookies_from_browser`, `cookie`, or `default` for yt-dlp authentication
- **Plugin Auto-Update** — Version checking and auto-update for yt-dlp, ffmpeg, and whisper with UI indicators and update logs
- **Web GUI** — React + Vite + Tailwind + shadcn/ui dashboard with light/dark mode and SSE job progress
- **Retention Policies** — Automatic cleanup of media, reports, and NotebookLM notebooks per-preset; runs after each job AND on a configurable schedule (default: every 60 min)
- **Social Sentiment** — Multi-platform social media collection (Reddit, X/Twitter, Stocktwits) with dedup, image download, structured reports, and destination dispatch (agy, NotebookLM)
- **Antigravity (agy) Skills** — Optional second generation backend that runs agentic skills (e.g. `web-video-presentation`) via the agy CLI, with auto-provisioned vendored skills and here.now publishing
- **Telegram Notifications** — Optional post-success Telegram notifications via bot token
- **Smart NotebookLM Bundling** — Adaptive bin-packing upload strategy (`individual` / `combined` / `smart`) that respects the 50-file × 200MB NotebookLM free-tier limits
- **PO Token Bot-Detection Bypass** — Auto-managed bgutil POT provider container with self-healing fallback chain and per-download bypass-mode logging
- **Scheduled Deduplication** — `skip_processed` flag + `media_status` tracking means already-processed videos are never re-downloaded; permanent errors (members-only, private, deleted) are classified once and skipped on all future runs — no wasted bandwidth or API calls
- **Safe Fallback Chain** — When the primary bypass mode fails (bot detection, rate limiting, HTTP 403, cookie DB lock), the pipeline retries with the configured fallback chain. The default fallback is no-auth (safe) — `cookies_from_browser` is opt-in only and never used automatically, since reading from your active browser profile risks getting your YouTube account banned
- **Session Keepalive** — Background task rotates NotebookLM cookies every 30 min so the Google session persists for up to 2 years (same as a real Chrome browser)

## LLM-free by default

StreamDoc is designed so that **the core pipeline runs without any LLM and spends zero tokens**. The LLM is only invoked when you explicitly opt in to an AI generation backend. This keeps operating costs at zero for the majority of use cases.

**Always LLM-free (no tokens spent):**
- Channel resolution and video listing (yt-dlp + RSS)
- Media download (yt-dlp with PO Token / cookie bypass)
- Transcript extraction (YouTube official API → faster-whisper local fallback)
- Frame extraction and multi-stage perceptual deduplication (ffmpeg + imagehash + SSIM + histogram + variance — all local CPU)
- Markdown + PDF report generation (reportlab)
- Scheduled runs, retention cleanup, and dedup tracking
- Social sentiment collection (Reddit / X / Stocktwits public APIs)
- Telegram notifications

**Opt-in LLM backends (tokens spent only when you configure them):**
- **NotebookLM** — uploads reports to Google NotebookLM for AI-generated slide decks, podcasts, infographics, and reports. Disabled by setting `STREAMDOC_NOTEBOOKLM_ENABLED=false`.
- **Antigravity (agy)** — runs agentic skills (e.g. `web-video-presentation`) via the agy CLI. Disabled by default (`STREAMDOC_AGY_ENABLED=false`).

This means a default deployment can run scheduled YouTube monitoring jobs indefinitely with **zero API cost** — transcripts, frames, and reports are all produced locally. The LLM backends are only there for when you want to transform the raw reports into polished presentations.

## Prerequisites

| Tool | Why | Required? | Install |
|------|-----|-----------|---------|
| [uv](https://docs.astral.sh/uv/) | Python env + dependency management | Yes | `winget install astral-sh.uv` / `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [ffmpeg](https://ffmpeg.org/) | Media download + frame extraction | Yes | `winget install Gyan.FFmpeg` / `brew install ffmpeg` |
| [Node.js](https://nodejs.org/) 20+ | Build/run the React frontend | Dev & local prod | `winget install OpenJS.NodeJS` / `brew install node` |
| [just](https://github.com/casey/just) | Task runner (replaces Make) | Recommended | `winget install Casey.Just` / `cargo install just` |
| [mprocs](https://github.com/pvolok/mprocs) | Clean multi-process dev TUI | Optional (dev only) | `cargo install mprocs` / `npm install -g mprocs` |
| A Google account | NotebookLM integration | Only for NotebookLM | — |

> **Windows note:** `uv`, `ffmpeg`, `Node`, and `just` should all be on your `PATH`. On Windows, `uv` is the only supported way to run the Python side.

## Quick start

```bash
# 1. Clone & install Python deps
git clone <your-repo-url> StreamDoc && cd StreamDoc
uv sync --extra dev

# 2. Configure
cp .env.example .env
#   edit .env — at minimum set STREAMDOC_YOUTUBE_API_KEY if you have one.
#   The default bypass mode is po_token (auto-starts a Docker container
#   for PO Token generation). If Docker is not installed, the app falls
#   back to no-auth (default) mode automatically.
#   Alternative modes: cookies_from_browser / cookie / default
#   WARNING: cookies_from_browser reads from your ACTIVE browser profile
#   and can get your YouTube account banned. Only use it if you understand
#   the risk and ideally with a dedicated browser profile.
#
#   IMPORTANT — JavaScript runtime requirement (yt-dlp 2026.07+):
#   yt-dlp requires an external JS runtime (Node.js v22+, Deno, or Bun)
#   plus the yt-dlp-ejs package (installed automatically via pyproject.toml)
#   to solve YouTube's n-challenge. Without it, downloads fail with
#   "Sign in to confirm you're not a bot" or "Requested format is not available".
#   The default is STREAMDOC_YT_DLP_JS_RUNTIMES=node (uses Node.js if installed).
#   Install Node.js from https://nodejs.org or set STREAMDOC_YT_DLP_JS_RUNTIMES=deno
#   if you prefer Deno.

# 3. Run a preset from the CLI
uv run streamdoc fetch my-preset
```

To use the web GUI, see [Running the stack](#running-the-stack) below.

## Running the stack

There are three ways to run StreamDoc. Pick the one that fits your workflow.

### A. Local development (hot reload)

Two processes: the FastAPI API (with reload) and the Vite dev server (HMR). The Vite dev server proxies `/api` calls to the API.

**Option 1 — `just dev` (recommended):**

Uses a Python launcher (`scripts/dev.py`) that starts both processes, streams their output with `[API]`/`[WEB]` prefixes, and kills both cleanly on Ctrl-C. Works identically on Windows, macOS, and Linux.

```bash
just dev
# API  -> http://localhost:5454  (Swagger at /docs)
# UI   -> http://localhost:5173  (open this one)
```

**Option 2 — `just dev-mprocs` (TUI with split logs):**

mprocs gives you a TUI showing both processes' logs side by side. Requires installing mprocs (`cargo install mprocs` or `npm install -g mprocs`).

```bash
just dev-mprocs
# API  -> http://localhost:5454
# UI   -> http://localhost:5173
```

**Option 3 — manual (two terminals):**

```bash
# Terminal 1 — API
uv run uvicorn streamdoc.api.app:create_app --factory --reload \
  --reload-dir src/streamdoc --port 5454

# Terminal 2 — UI
cd frontend && npm install && npm run dev
```

### B. Local production (single process)

Builds the React app once into `src/streamdoc/api/static`, then FastAPI serves **both** the API and the frontend from a single process on a single port. This is the simplest local setup and the closest to what Docker does.

```bash
just prod
# open http://localhost:5454
```

Or step by step:

```bash
cd frontend && npm install && npm run build && cd ..
uv run streamdoc-api
```

### C. Docker (experimental)

> **WARNING:** The Docker setup has **not been tested in production**. It is provided as a starting point. The main limitation is NotebookLM auth — see [NotebookLM login](#notebooklm-login--browser-auth) below.

Docker builds the frontend for you and runs everything in one container. `data/`, `config/`, and `assets/` are bind-mounted so your presets, prompts, outputs, and NotebookLM session persist on the host.

```bash
cp .env.example .env          # edit values
just docker-up                # builds image + starts container
open http://localhost:5454
just docker-logs              # tail logs
just docker-down              # stop
```

**NotebookLM auth in Docker:** run `notebooklm login` on the **host** once, then the container reads the session from the mounted `./data` volume. When the session expires, re-run `notebooklm login` on the host and restart the container:

```bash
notebooklm login              # on host — refreshes the session
just docker-down && just docker-up   # container picks up the new session
```

> The Docker image installs Playwright + Chromium so NotebookLM works in headless `storage_state` mode. If you don't use NotebookLM, set `STREAMDOC_NOTEBOOKLM_ENABLED=false` in `.env`.

## NotebookLM login & browser auth

NotebookLM requires a Google session. Because interactive browser login is awkward inside containers, StreamDoc uses a **host-login, mount-the-session** flow:

```bash
# 1. On your HOST, install notebooklm-py and log in (opens a real browser)
uv pip install notebooklm-py
notebooklm login
#   or:  notebooklm login --browser-cookies chrome

# 2. This writes data/integrations/notebooklm/storage_state.json
#    For Docker, that path is mounted via the ./data volume automatically.

# 3. Check status from StreamDoc
uv run streamdoc notebooklm auth status
```

**Session expiry:** Google's main session cookies (SID, HSID, SAPISID) last ~2 years. StreamDoc runs a background keepalive (every 30 min by default) that refreshes the rotation tokens. If the session is fully invalidated (password change, 2FA re-auth, etc.), you must re-run `notebooklm login` on the host and restart the app/container.

**CDP auto-refresh (headless, no persistent profile needed):** If the dedicated `browser_profile` goes stale across restarts, you can point StreamDoc at an already-running, signed-in Chrome via the Chrome DevTools Protocol. Start Chrome with remote debugging and set `STREAMDOC_NOTEBOOKLM_CDP_URL`:

```bash
# Start your normal Chrome with a debugging port
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# In another terminal / your .env
export STREAMDOC_NOTEBOOKLM_CDP_URL=http://localhost:9222
uv run streamdoc api   # or your start command
```

With this set, StreamDoc's headless re-auth attaches to your live Chrome to re-mint NotebookLM cookies automatically instead of relying on a dedicated profile.

The session file contains sensitive Google cookies — it is gitignored and never committed. See [`docs/integrations-auth.md`](docs/integrations-auth.md) for the full auth design and the secret/credential boundary.

## Social platform setup

StreamDoc's social presets can collect posts from **X (Twitter)**, **Reddit**, and **Stocktwits**.

- **X** requires the `twitter` CLI and an authenticated browser session.
- **Reddit** requires the `rdt` CLI and an authenticated browser session.
- **Stocktwits** works without authentication.

Run the interactive setup helper:

```bash
just setup-social
```

Or open **Settings > Social** in the StreamDoc UI to authorize, test connectivity, and view status. Full details are in [`docs/SOCIAL_SETUP.md`](docs/SOCIAL_SETUP.md).

## Configuration

All settings use the `STREAMDOC_` env prefix. Copy `.env.example` to `.env` and adjust. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMDOC_DB_PATH` | `data/State/streamdoc.sqlite` | SQLite database path |
| `STREAMDOC_MEDIA_ROOT` | `data/Media` | Downloaded media directory |
| `STREAMDOC_OUTPUT_ROOT` | `data/Outputs` | Generated outputs directory |
| `STREAMDOC_YT_DLP_BYPASS_MODE` | `po_token` | `po_token` (auto-starts Docker container), `cookies_from_browser`, `cookie`, or `default` |
| `STREAMDOC_YT_DLP_COOKIES_BROWSER` | `chrome` | Browser for `cookies_from_browser` mode (`chrome`, `edge`, `firefox`, `brave`, etc.) |
| `STREAMDOC_YT_DLP_COOKIES_BROWSER_PROFILE` | — | Optional browser profile name (e.g. `Default`) |
| `STREAMDOC_YT_DLP_BYPASS_FALLBACK_MODE` | `default` | Comma-separated fallback chain tried in order when the primary mode fails. Used when: (1) cookie DB is locked, (2) `po_token` mode is active but Docker is not available, (3) bot detection / rate limiting / HTTP 403. Options: `default` (no-auth, safe), `cookie` (pre-exported jar), `cookies_from_browser` (**opt-in only — ban risk on personal profiles!**), or empty to disable |
| `STREAMDOC_POT_PROVIDER_URL` | `http://127.0.0.1:4416` | PO Token provider HTTP server URL |
| `STREAMDOC_POT_PROVIDER_IMAGE` | `brainicism/bgutil-ytdlp-pot-provider:latest` | Docker image for the POT provider (official TypeScript/Node.js, matches yt-dlp's built-in bgutil plugin version) |
| `STREAMDOC_POT_PROVIDER_CONTAINER_NAME` | `streamdoc-pot` | Docker container name for the POT provider |
| `STREAMDOC_POT_AUTO_START` | `true` | Auto-start the POT container on app startup if Docker is available |
| `STREAMDOC_YT_DLP_JS_RUNTIMES` | `node` | JS runtime for yt-dlp's EJS n-challenge solver (required since yt-dlp 2026.07). Options: `node`, `deno`, `bun`, `quickjs`, or comma-separated. Node.js v22+ must be installed |
| `STREAMDOC_YT_DLP_COOKIEJAR_PATH` | — | Cookie jar for cookie bypass mode |
| `STREAMDOC_TRANSCRIPT_LANGUAGES` | `en,he,ar` | Preferred transcript languages (comma-separated) |
| `STREAMDOC_WHISPER_MODEL` | `small` | faster-whisper model name |
| `STREAMDOC_WHISPER_TIMEOUT_SECONDS` | `600` | Max seconds per Whisper transcription (10 min) |
| `STREAMDOC_USE_YT_DLP_SUBTITLES` | `false` | Fall back to yt-dlp subtitle download when youtube-transcript-api fails (uses cookie/PO-token bypass) |
| `STREAMDOC_NOTEBOOKLM_ENABLED` | `true` | Enable NotebookLM integration |
| `STREAMDOC_NOTEBOOKLM_BROWSER` | `chromium` | Playwright browser: `chromium`, `chrome`, or `msedge` |
| `STREAMDOC_NOTEBOOKLM_LOG_LEVEL` | `WARNING` | notebooklm-py internal log level: `WARNING`, `INFO`, or `DEBUG` |
| `STREAMDOC_NOTEBOOKLM_CDP_URL` | — | Chrome DevTools endpoint for unattended re-auth (e.g. `http://localhost:9222`) |
| `STREAMDOC_NOTEBOOKLM_AUTO_UPLOAD` | `true` | Auto-upload reports after fetch |
| `STREAMDOC_NOTEBOOKLM_TEMPLATES_DIR` | `config/prompts/notebooklm` | User prompt templates (gitignored) |
| `STREAMDOC_NOTEBOOKLM_SAMPLE_PROMPTS_DIR` | `assets/prompts/notebooklm` | Shipped sample prompts (tracked) |
| `STREAMDOC_RETENTION_MEDIA_HOURS` | `24` | Media cleanup window |
| `STREAMDOC_RETENTION_REPORTS_HOURS` | `168` | Report cleanup window (7 days) |
| `STREAMDOC_RETENTION_CLEANUP_INTERVAL_MINUTES` | `60` | How often scheduled cleanup runs |
| `STREAMDOC_TWITTER_CLI_BINARY_PATH` | auto | Path to `twitter` CLI |
| `STREAMDOC_RDT_CLI_BINARY_PATH` | auto | Path to `rdt` CLI |
| `STREAMDOC_STOCKTWITS_API_BASE` | `https://api.stocktwits.com/api/2/` | Stocktwits API base URL |

See [`.env.example`](.env.example) for the full list.

## Prompt templates

StreamDoc ships with sample prompt templates in `assets/prompts/notebooklm/` (tracked in git). On first run, these are **copied** to `config/prompts/notebooklm/` (gitignored). After that:

- **All user edits and new prompts** stay in `config/prompts/notebooklm/` — never committed to git.
- **Sample prompts** in `assets/prompts/notebooklm/` remain read-only references.
- To add a new "template prompt" for all users: add a `.yaml` file to `assets/prompts/notebooklm/` and commit it. Existing users can copy it manually; new clones get it via the seed-on-first-run.

This separation prevents accidental commits of user-specific prompts while keeping the repo shippable with good defaults.

## CLI reference

```bash
uv run streamdoc fetch <preset>                              # run a preset now
uv run streamdoc schedule add <preset> "interval:3600"       # schedule a preset (writes its schedule field)
uv run streamdoc schedule list                               # list scheduled presets
uv run streamdoc schedule run <preset>                       # run a preset once immediately
uv run streamdoc schedule remove <preset>                    # clear a preset's schedule

# NotebookLM subcommands
uv run streamdoc notebooklm auth status
uv run streamdoc notebooklm notebook list
uv run streamdoc notebooklm content generate <notebook_id> --type slide_deck
```

### Scheduling

Each preset carries a `schedule` field that is the **single source of truth** for when it runs automatically. The Presets page and the Scheduler page both read and write this same field, so they always stay in sync:

- Set a schedule in the Preset form (Schedule section) → it appears in the Scheduler page.
- Add a schedule from the Scheduler page → it is written to the preset's `schedule` field and shows on the Presets page.

Schedule string formats:
- `interval:<seconds>` — e.g. `interval:3600` (every hour)
- `cron:<5-field expr>` — e.g. `cron:0 6 * * *` (daily at 06:00 UTC)
- `cron:<seconds>` — single-field shorthand for an interval

The APScheduler runs inside the API process and reconciles its jobs with the presets table on startup and after every preset create/update/delete. Inactive presets (`active=false`) are not scheduled even if they have a `schedule` set. Legacy `schedule_interval_hours` values are auto-converted to `interval:` schedules for backward compatibility.

## Updating

StreamDoc has a unified update flow via `just update` that handles all four update layers. `pyproject.toml` uses lower-bound (`>=`) versions and default-branch git sources for fast-moving packages, so `uv lock --upgrade` always pulls the latest compatible releases.

| Layer | What | How |
|-------|------|-----|
| **App code** | StreamDoc source | `git pull` (aborts if working tree is dirty) |
| **Python deps** | `pyproject.toml` / `uv.lock` | `uv lock --upgrade` then `uv sync --extra dev` |
| **JS deps** | `frontend/package.json` | `npm install` / `npm update` |
| **Runtime tools** | yt-dlp, ffmpeg-python, faster-whisper, twitter-cli, rdt-cli | `uv lock --upgrade` / `uv tool upgrade` |
| **Frontend build** | React → static files | `npm run build` |

### Full update (after being away or when downloads fail)

```bash
just update
```

This runs all steps in order: git pull → Python deps (upgraded) → JS deps → runtime tools → rebuild frontend. Restart the app after.

### Check what's outdated (dry-run, no changes)

```bash
just update-check
```

Shows: git status + incoming commits, outdated Python packages, outdated npm packages, runtime tool versions with yt-dlp latest-from-PyPI comparison.

### Individual update targets

```bash
just update-git     # git pull only (aborts if dirty)
just update-deps    # sync Python + JS deps (no git, no tools, no rebuild)
just update-tools   # upgrade yt-dlp, ffmpeg-python, faster-whisper only
just sync           # upgrade + sync all Python packages and uv tools (no git/frontend)
```

### When yt-dlp downloads start failing

YouTube changes their player frequently. An outdated yt-dlp is the most common cause of download failures. Fix it with:

```bash
just update-tools   # upgrades yt-dlp to latest
# or full update:
just update
```

> **Why `uv lock --upgrade` instead of `uv pip install --upgrade`?**
> With uv's lockfile-based workflow, `uv pip install --upgrade` is temporary — the next `uv run` or `uv sync` reverts it to the locked version. `uv lock --upgrade` refreshes the lockfile to the newest releases that satisfy the `>=` lower bounds in `pyproject.toml`, and `uv sync` installs those exact versions. The upgrade persists across runs.

## Testing

```bash
just test              # unit + integration tests (no network)
just test-live         # live tests (requires network + yt-dlp)
```

Or with uv directly:

```bash
uv run pytest tests -m "not live" -q
uv run pytest tests -m live -v
```

## Architecture

```
CLI (click) / Web GUI (React) → FastAPI → PresetRunner
  → resolve channels → list videos → download media
  → extract transcript → extract/dedup frames → build outputs (MD + PDF)
  → [opt-in] NotebookLM upload & generation  |  [opt-in] agy skill run
```

| Module | Responsibility |
|--------|---------------|
| `core/downloader.py` | Single source of truth for all yt-dlp interactions (CLI + Python API), bypass-mode resolution, error classification, fallback retry |
| `core/pot_provider.py` | PO Token provider container lifecycle (auto-start, self-healing fallback, reachability probes) |
| `core/channel.py` | Channel/Video resolution with HTML-scrape fallback |
| `core/fetch.py` | Pipeline orchestration via `PresetRunner` (YouTube + social pipelines, dedup tracking, backend dispatch) |
| `core/transcript.py` | Official API → yt-dlp subtitles (optional) → Whisper fallback |
| `core/frames.py` | Frame extraction + multi-stage perceptual dedup pipeline (motion / phash / SSIM / histogram / variance) |
| `core/output.py` | Markdown + PDF generation |
| `core/report.py` | Per-preset run reports |
| `core/social_output.py` | Unified social report builder (Markdown + PDF, per-platform sections, embedded images) |
| `core/cleanup.py` | Retention cleanup (media, reports, notebooks) — runs after each job AND on a schedule |
| `core/notify.py` | Telegram post-success notifications |
| `integrations/notebooklm/` | NotebookLM client, auth, generation, retention, smart bundling |
| `integrations/agy/` | Antigravity CLI runner, skill management, here.now publishing |
| `integrations/social/` | Reddit / X / Stocktwits collectors with auth and dedup store |
| `api/` | FastAPI routes, SSE, schemas |

**Single-process production:** `just prod` and Docker both run a single `streamdoc-api` process that serves the FastAPI backend **and** the built React frontend on the same port (`:5454`). There is no separate frontend server in production mode. Only `just dev` uses two processes (for hot reload).

### Multi-stage frame deduplication

Frame extraction uses a configurable multi-stage pipeline (`STREAMDOC_FRAME_DEDUP_PIPELINE`, default: `motion,phash,ssim,variance`). Each stage runs left-to-right and a frame is kept only if it survives every enabled stage:

| Stage | Method | What it catches | Cost |
|-------|--------|-----------------|------|
| `motion` | Mean absolute pixel diff vs. last extracted frame | Static / duplicate frames | Very cheap |
| `phash` / `dhash` / `ahash` | Perceptual hash (Hamming distance) vs. kept frames | Near-duplicate visuals | Cheap |
| `ssim` | Structural Similarity Index vs. last N kept frames | Gradual changes phash misses | Medium |
| `hist` | Grayscale histogram correlation vs. last N kept frames | Color/tone shifts | Medium |
| `variance` | Post-filter: keep top 60% highest-variance frames if avg variance is very low | Talking-head videos with static backgrounds | Cheap |

All stages run on local CPU — no LLM, no API calls. The pipeline is tuned via `STREAMDOC_FRAME_*` env vars (thresholds, window sizes, hash algo).

## Project structure

```
StreamDoc/
├── src/streamdoc/          # Python backend (core, api, integrations, models)
├── frontend/               # React + Vite + Tailwind SPA (source)
├── assets/prompts/         # Shipped sample prompt templates (tracked in git)
├── config/                 # User config — gitignored
│   ├── presets/            # User preset YAML files
│   ├── prompts/notebooklm/ # User prompt templates (seeded from assets/ on first run)
│   └── integrations/       # Integration config
├── data/                   # Runtime data — gitignored
│   ├── State/              # SQLite databases
│   ├── Media/              # Downloaded videos, audio, frames
│   ├── Outputs/            # Generated Markdown + PDF reports
│   ├── Models/             # Whisper model cache
│   ├── cookies/            # yt-dlp cookie jar
│   └── integrations/       # NotebookLM session (Google cookies — secret!)
├── docs/                   # PRD, design brief, auth design
├── .agents/                # PRD + SYSTEM hard copy (source of truth for agents)
├── tests/                  # pytest unit + integration + live tests
├── scripts/                # Manual live verification scripts (not pytest)
├── justfile                # Task runner (just) — replaces Makefile
├── mprocs.yaml             # mprocs config for dev mode (optional)
├── Dockerfile              # Multi-stage build (experimental)
├── docker-compose.yml      # Single-service stack with volume mounts (experimental)
└── pyproject.toml          # Python deps + project config
```

**What's tracked vs gitignored:**

| Tracked (committed) | Gitignored (local only) |
|---------------------|------------------------|
| `src/` source code | `.env`, `.venv/` |
| `frontend/src/` source | `data/` (all runtime output) |
| `assets/prompts/` sample prompts | `config/presets/`, `config/prompts/` (user data) |
| `tests/`, `scripts/` | `frontend/node_modules/`, `frontend/dist/` |
| `docs/`, `.agents/` | `src/streamdoc/api/static/` (built frontend) |
| `justfile`, `mprocs.yaml` | `__pycache__/`, `.mypy_cache/`, etc. |
| `Dockerfile`, `docker-compose.yml` | `data/integrations/notebooklm/` (secrets) |

## Documentation

- [Product Requirements](docs/PRD.md) — specs and acceptance criteria
- [Social Presets & agy Templates](docs/social-presets.md) — authoring guide for social presets and agy templates
- [Social Platform Setup](docs/SOCIAL_SETUP.md) — install, authenticate, and verify Reddit/X/Stocktwits
- [System Architecture](.agents/SYSTEM.md) — module map and design decisions
- [Integrations & Auth](docs/integrations-auth.md) — NotebookLM auth and secret boundary
- [Design Brief](docs/design-brief.md) — UI/UX direction

## Tech stack

- **yt-dlp** — YouTube downloading and metadata extraction (with built-in bgutil PO Token plugin)
- **ffmpeg** — Media processing and frame extraction
- **faster-whisper** — Local speech-to-text fallback (no API cost)
- **reportlab** — PDF generation
- **imagehash + NumPy** — Perceptual frame deduplication (phash, SSIM, histogram, variance — all local CPU)
- **SQLAlchemy** — ORM and database management
- **APScheduler** — Job scheduling with SQLite persistent job store
- **Pydantic** — Settings validation
- **Click** — CLI interface
- **FastAPI** — REST API backend with SSE streaming
- **notebooklm-py** — Optional NotebookLM integration (opt-in LLM backend)
- **agy CLI** — Optional Antigravity skills runner (opt-in LLM backend)
- **React + Vite + TypeScript** — Frontend SPA
- **Tailwind CSS + shadcn/ui** — UI components and styling

## Acknowledgements

StreamDoc builds on the work of the open-source community. We gratefully acknowledge the following projects that make this tool possible:

### [notebooklm-py](https://github.com/teng-lin/notebooklm-py)

The NotebookLM integration in StreamDoc is powered by [notebooklm-py](https://github.com/teng-lin/notebooklm-py), an unofficial Python API and CLI for [Google NotebookLM](https://notebooklm.google.com), developed and maintained by [Teng-Lin](https://github.com/teng-lin) and the community.

**How StreamDoc uses it:** notebooklm-py provides the core browser automation, session management, and API calls that let StreamDoc authenticate with Google, create notebooks, upload sources (PDFs, transcripts, frames), generate content (slide decks, podcasts, infographics, reports), and download artifacts — all programmatically. StreamDoc wraps this in a higher-level integration layer (`src/streamdoc/integrations/notebooklm/`) that adds preset-driven automation, retention policies, keepalive session refresh, and a web GUI.

**License:** [MIT](https://opensource.org/licenses/MIT) — thank you to the authors for keeping this open.

> **Note:** notebooklm-py is an unofficial library that uses undocumented Google APIs. It is not affiliated with Google. APIs may change without notice. See the [project's README](https://github.com/teng-lin/notebooklm-py#readme) for details and limitations.

### Other open-source dependencies

| Library | Role | Link |
|---------|------|------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube video downloading and metadata | [MIT/Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE) |
| [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) | PO Token provider for YouTube bot-detection bypass | [GPL-3.0](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/blob/master/LICENSE) |
| [ffmpeg](https://ffmpeg.org/) | Media processing and frame extraction | [LGPL/GPL](https://ffmpeg.org/legal.html) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local speech-to-text (Whisper inference) | [MIT](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) |
| [imagehash](https://github.com/JohannesBuchner/imagehash) | Perceptual frame deduplication | [BSD-2-Clause](https://github.com/JohannesBuchner/imagehash/blob/master/LICENSE) |
| [FastAPI](https://github.com/tiangolo/fastapi) | REST API framework | [MIT](https://github.com/tiangolo/fastapi/blob/master/LICENSE) |
| [React](https://github.com/facebook/react) | Frontend UI library | [MIT](https://github.com/facebook/react/blob/main/LICENSE) |
| [Vite](https://github.com/vitejs/vite) | Frontend build tooling | [MIT](https://github.com/vitejs/vite/blob/main/LICENSE) |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | Utility-first CSS framework | [MIT](https://github.com/tailwindlabs/tailwindcss/blob/master/LICENSE) |
| [shadcn/ui](https://github.com/shadcn-ui/ui) | UI component collection | [MIT](https://github.com/shadcn-ui/ui/blob/main/LICENSE) |

### Social pipeline

| Library | Role | Link |
|---------|------|------|
| [twitter-cli (opencli)](https://github.com/jackwener/opencli) | X/Twitter post collection via CLI | [MIT](https://github.com/jackwener/opencli/blob/main/LICENSE) |
| Reddit public JSON API | Reddit post collection (stdlib urllib.request) | — |
| Stocktwits public API | Stocktwits post collection (stdlib urllib.request) | — |

## License

Private project — all rights reserved.
