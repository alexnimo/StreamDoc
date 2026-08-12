"""FastAPI application factory for StreamDoc.

Serves the API and (in production) the built React frontend.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from streamdoc.api.routes import api_router
from streamdoc.config import settings
from streamdoc.db import init_db

# Configure logging so backend logs are visible in the console
# Reason: without this, all logger.info/warning/error calls go nowhere
logging.basicConfig(
    level=os.environ.get("STREAMDOC_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="StreamDoc API",
        description="YouTube channel to PDF presentation pipeline with NotebookLM integration.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(api_router)

    # Health check
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # Serve built frontend (production mode)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        # Reason: Mount assets directory directly so JS/CSS files are served
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Reason: SPA catch-all — any non-API GET request serves index.html
        # so client-side routing (React Router) handles the path
        index_html = static_dir / "index.html"

        @app.get("/{full_path:path}")
        async def spa_catch_all(request: Request, full_path: str):
            # Let API routes handle their own paths (shouldn't reach here, but just in case)
            if full_path.startswith("api/"):
                return {"detail": "Not Found"}
            # Serve specific static files if they exist (favicon, etc.)
            candidate = static_dir / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index_html))
    else:
        @app.get("/")
        async def root():
            return {
                "message": "StreamDoc API",
                "docs": "/docs",
                "frontend": "Run 'npm run dev' in frontend/ for development",
            }

    # Track background tasks for cleanup
    _background_tasks: list[asyncio.Task] = []

    # Initialize DB and start background tasks on startup
    @app.on_event("startup")
    async def startup():
        init_db()
        logger.info("StreamDoc API started, DB initialized")

        # Reason: autoload presets from the configured directory so YAML/JSON
        # presets (and their schedules) are upserted into the DB before the
        # scheduler reconciles. This matches the PRD's "auto-loaded on startup"
        # requirement and is required for DB-driven scheduling to pick up
        # schedules defined in preset files.
        try:
            from streamdoc.presets import autoload_presets

            loaded = autoload_presets()
            if loaded:
                logger.info("Autoloaded %d preset(s) from disk.", len(loaded))
        except Exception as exc:
            logger.warning("Preset autoload failed: %s", exc)

        # Clean up stale jobs from previous sessions
        try:
            from streamdoc.core.jobs import cleanup_stale_jobs
            stale_count = cleanup_stale_jobs()
            if stale_count:
                logger.info("Cleaned up %d stale running jobs", stale_count)
        except Exception as exc:
            logger.warning("Failed to clean up stale jobs: %s", exc)

        # Reason: run retention cleanup on startup to delete files and
        # notebooks that expired while the server was down or while jobs
        # were hanging. This catches up on any missed cleanup cycles.
        try:
            from streamdoc.core.cleanup import run_cleanup
            counts = run_cleanup()
            if counts and any(v > 0 for v in counts.values()):
                logger.info("Startup retention cleanup: %s", counts)
        except Exception as exc:
            logger.warning("Startup retention cleanup failed: %s", exc)

        # Start the APScheduler singleton and reconcile jobs with the presets
        # table. Scheduled presets now actually execute inside the API process.
        try:
            from streamdoc.scheduler import start_scheduler

            start_scheduler()
        except Exception as exc:
            logger.warning("Failed to start scheduler: %s", exc)

        # Reason: check for plugin updates (yt-dlp, ffmpeg, whisper) on
        # startup and auto-update pip-managed plugins if enabled. An
        # outdated yt-dlp is the most common cause of YouTube download
        # failures, so keeping it current is critical. Runs in a background
        # thread so it never blocks the server from starting.
        try:
            from streamdoc.core.tools import run_startup_check

            statuses = run_startup_check()
            for s in statuses:
                if s.update_available:
                    logger.info(
                        "Plugin update available: %s (%s -> %s, auto_update=%s)",
                        s.display_name, s.installed_version, s.latest_version,
                        s.auto_update_enabled,
                    )
        except Exception as exc:
            logger.warning("Startup plugin check failed: %s", exc)

        # Reason: auto-provision agy skills on startup so a fresh install
        # or prod deployment has all vendored skills in .agents/skills/
        # without manual action. When agy_skills_auto_update is also True,
        # fetch the latest skill revisions from upstream via `npx skills`
        # before installing. This runs in a background thread so it never
        # blocks the server from starting (npx may take 30+ seconds on a
        # cold npm cache).
        if settings.agy_enabled and settings.agy_auto_provision_skills:
            def _provision_agy_skills():
                try:
                    from streamdoc.integrations.agy import skills as agy_skills

                    if settings.agy_skills_auto_update:
                        agy_skills.update_from_upstream()

                    installed = agy_skills.install_all()
                    if installed:
                        logger.info(
                            "Auto-provisioned %d agy skill(s): %s",
                            len(installed),
                            [p.name for p in installed],
                        )
                except Exception as exc:
                    logger.warning("agy skill auto-provisioning failed: %s", exc)

            import threading
            threading.Thread(
                target=_provision_agy_skills,
                name="agy-skill-provision",
                daemon=True,
            ).start()

        # Reason: ensure the PO Token provider container is running when
        # bypass_mode=po_token (the default). If Docker is not available,
        # the app gracefully falls back to cookies_from_browser or the
        # configured fallback mode. This runs synchronously because every
        # subsequent yt-dlp call depends on the bypass mode being correct.
        if settings.pot_auto_start and settings.yt_dlp_bypass_mode == "po_token":
            try:
                from streamdoc.core.pot_provider import ensure_pot_provider

                pot_result = ensure_pot_provider()
                logger.info("PO Token provider: %s — %s", pot_result.status.value, pot_result.message)
            except Exception as exc:
                logger.warning("PO Token provider startup check failed: %s", exc)

        # Start NotebookLM session keepalive background task
        if settings.notebooklm_enabled:
            try:
                from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager
                from streamdoc.integrations.notebooklm.keepalive import keepalive_loop

                auth_manager = NotebookLMAuthManager(
                    settings.notebooklm_storage_state_path,
                    profile=settings.notebooklm_profile,
                )
                task = asyncio.create_task(
                    keepalive_loop(
                        auth_manager,
                        interval_minutes=settings.notebooklm_keepalive_interval_minutes,
                    )
                )
                _background_tasks.append(task)
                logger.info(
                    "NotebookLM keepalive task started (interval: %.1fm)",
                    settings.notebooklm_keepalive_interval_minutes,
                )
            except Exception as exc:
                logger.warning("Failed to start NotebookLM keepalive: %s", exc)

            # Start NotebookLM generation poller for pending generations
            # Reason: long generations (10+ min) timeout during the initial
            # wait but continue running on NotebookLM's side. This poller
            # checks pending records every 30s and downloads artifacts
            # when they complete.
            try:
                from streamdoc.integrations.notebooklm.poller import (
                    generation_poller_loop,
                )
                poller_task = asyncio.create_task(generation_poller_loop())
                _background_tasks.append(poller_task)
                logger.info("NotebookLM generation poller started (interval: 30s)")
            except Exception as exc:
                logger.warning("Failed to start generation poller: %s", exc)

    @app.on_event("shutdown")
    async def shutdown():
        # Stop the scheduler singleton so APScheduler threads don't leak.
        try:
            from streamdoc.scheduler import shutdown_scheduler

            shutdown_scheduler()
        except Exception as exc:
            logger.warning("Failed to shut down scheduler: %s", exc)
        # Reason: stop the POT provider container if we started it.
        # If the user started it manually (via `just pot-up`), we leave
        # it running so it survives app restarts.
        try:
            from streamdoc.core.pot_provider import shutdown_pot_provider

            shutdown_pot_provider()
        except Exception as exc:
            logger.warning("Failed to shut down POT provider: %s", exc)
        for task in _background_tasks:
            task.cancel()
        for task in _background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        _background_tasks.clear()
        # Reason: shut down the shared async event loop used by run_async()
        from streamdoc.async_utils import shutdown_async_loop
        shutdown_async_loop()
        logger.info("StreamDoc API shutting down")

    return app


def run() -> None:
    """Run the API server with uvicorn.

    Reload is enabled only outside container/production environments so the
    same entrypoint works for local development and Docker.
    """
    import uvicorn
    from streamdoc.config import settings

    is_dev = settings.env.lower() not in {"container", "production", "prod"}
    uvicorn.run(
        "streamdoc.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=is_dev,
        reload_dirs=["src"] if is_dev else None,
        reload_excludes=["data", "config", "assets", "frontend", "tests"] if is_dev else None,
    )


app = create_app()
