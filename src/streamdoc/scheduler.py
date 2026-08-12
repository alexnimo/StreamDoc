"""APScheduler-backed preset scheduling.

Single source of truth: the ``Preset.schedule`` column in the SQLite DB.
This module keeps a singleton :class:`BackgroundScheduler` running inside the
API process and reconciles its jobs with the DB whenever a preset is
created/updated/deleted or the API starts up.

Legacy ``scheduler_state.json`` entries are imported once into the matching
presets' ``schedule`` field on first start, then the JSON file is retired.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED, JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from streamdoc.config import settings
from streamdoc.db import session_scope
from streamdoc.integrations.social.auth import reddit_auth_manager, x_auth_manager
from streamdoc.models.preset import Preset

logger = logging.getLogger(__name__)

# Reason: retired legacy state file. Kept only for one-time migration of any
# jobs that were created before the DB-driven scheduler was introduced.
_LEGACY_STATE_PATH = Path(settings.media_root).parent / "scheduler_state.json"

# Module-level singleton scheduler. Started once on API startup, shut down on
# API shutdown. Reconciled with the DB via sync_jobs().
_scheduler: BackgroundScheduler | None = None


def _make_scheduler() -> BackgroundScheduler:
    """Build a fresh BackgroundScheduler configured from settings.

    Returns:
        BackgroundScheduler with SQLAlchemy jobstore and threadpool executor.
    """
    # Reason: BackgroundScheduler runs jobs in a thread pool, so long-running
    # preset fetches don't block other scheduled jobs from executing.
    # max_workers allows multiple presets to run in parallel.
    jobstores = {"default": {"type": "sqlalchemy", "url": f"sqlite:///{Path(settings.db_path)}"}}
    executors = {
        "default": {
            "type": "threadpool",
            "max_workers": settings.scheduler_max_workers,
        }
    }
    return BackgroundScheduler(jobstores=jobstores, executors=executors)


def _job_id(preset: str) -> str:
    """Build the canonical APScheduler job id for a preset name.

    Args:
        preset: Preset name/id.

    Returns:
        The job id string ``streamdoc:<preset>``.
    """
    return f"streamdoc:{preset}"


# Reason: dedicated job ID for the scheduled retention cleanup task.
# This is separate from preset jobs so it can be managed independently.
_CLEANUP_JOB_ID = "streamdoc:retention-cleanup"
_SOCIAL_REFRESH_JOB_ID = "streamdoc:social-auth-refresh"


def _run_scheduled_cleanup() -> None:
    """Run retention cleanup on a schedule, independent of job completion.

    Reason: cleanup normally runs at the end of each preset run (in
    ``run_once``). But if a job hangs or the server restarts, cleanup
    never runs and files/notebooks accumulate indefinitely. This
    scheduled task ensures cleanup runs periodically regardless of
    job outcomes.
    """
    try:
        from streamdoc.core.cleanup import run_cleanup
        logger.info("Running scheduled retention cleanup")
        counts = run_cleanup()
        if counts:
            logger.info("Scheduled cleanup summary: %s", counts)
    except Exception as exc:
        logger.error("Scheduled retention cleanup failed: %s", exc, exc_info=True)


def _trigger_for(schedule: str):
    """Build an APScheduler trigger from a schedule string.

    Supported formats:
        - ``cron:<5-field expr>``        -> CronTrigger
        - ``cron:<seconds>`` (1 field)   -> IntervalTrigger (seconds)
        - ``interval:<seconds>``         -> IntervalTrigger
        - ``<int>``                      -> IntervalTrigger (seconds)

    Args:
        schedule: Schedule string from a preset.

    Returns:
        A CronTrigger or IntervalTrigger.

    Raises:
        ValueError: If the schedule string is empty or malformed.
    """
    schedule = (schedule or "").strip()
    if not schedule:
        raise ValueError("Empty schedule")
    if schedule.startswith("cron:"):
        expr = schedule.split("cron:", 1)[1]
        parts = expr.split()
        if len(parts) == 5:
            return CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4])
        if len(parts) == 1:
            return IntervalTrigger(seconds=int(parts[0]))
        raise ValueError(f"Unsupported cron expression: {expr!r}")
    if schedule.startswith("interval:"):
        value = schedule.split("interval:", 1)[1]
        return IntervalTrigger(seconds=int(value))
    value = int(schedule)
    return IntervalTrigger(seconds=value)


def _trigger_label(schedule: str) -> str:
    """Human-readable label for a schedule string, used in API responses.

    Args:
        schedule: Schedule string from a preset.

    Returns:
        A short label like ``interval[1h]`` or ``cron[0 6 * * *]``.
    """
    try:
        return str(_trigger_for(schedule))
    except Exception:
        return schedule


def _scheduled_presets() -> list[Preset]:
    """Return all active presets that have a non-empty schedule.

    Returns:
        List of Preset model instances with a schedule set and active=True.
    """
    with session_scope() as s:
        rows = (
            s.query(Preset)
            .filter(Preset.schedule.isnot(None))
            .filter(Preset.schedule != "")
            .filter(Preset.active.is_(True))
            .all()
        )
        # Reason: detach from session by reading attributes into new Preset
        # instances so callers can use them after the session closes.
        return [
            Preset(
                id=r.id,
                name=r.name,
                schedule=r.schedule,
                active=r.active,
            )
            for r in rows
        ]


def list_jobs() -> list[dict[str, Any]]:
    """List scheduled jobs derived from the presets table.

    Returns:
        List of dicts with keys ``id``, ``preset``, ``schedule``, ``trigger``.
    """
    out: list[dict[str, Any]] = []
    for p in _scheduled_presets():
        sched = p.schedule or ""
        out.append(
            {
                "id": _job_id(p.id),
                "preset": p.id,
                "schedule": sched,
                "trigger": _trigger_label(sched),
            }
        )
    # Reason: stable ordering by preset id keeps the Scheduler page list
    # deterministic across reloads.
    out.sort(key=lambda j: j["preset"])
    return out


def add_job(preset: str, schedule: str) -> dict[str, Any]:
    """Schedule a preset by writing its schedule field, then sync the scheduler.

    This writes the schedule to the preset's DB row (single source of truth)
    and reconciles the live APScheduler with the DB.

    Args:
        preset: Preset id/name.
        schedule: Schedule string (e.g. ``interval:3600`` or ``cron:0 6 * * *``).

    Returns:
        The scheduled job dict (same shape as ``list_jobs`` entries).

    Raises:
        ValueError: If the preset does not exist or the schedule is invalid.
    """
    # Validate the schedule string early.
    _trigger_for(schedule)
    with session_scope() as s:
        p = s.get(Preset, preset)
        if p is None:
            raise ValueError(f"Preset '{preset}' not found")
        p.schedule = schedule
        s.flush()
    sync_jobs()
    return {
        "id": _job_id(preset),
        "preset": preset,
        "schedule": schedule,
        "trigger": _trigger_label(schedule),
    }


def remove_job(preset: str) -> None:
    """Clear a preset's schedule and remove it from the live scheduler.

    Args:
        preset: Preset id/name.
    """
    with session_scope() as s:
        p = s.get(Preset, preset)
        if p is not None:
            p.schedule = None
            s.flush()
    sync_jobs()


def run_once(preset: str) -> None:
    """Run a preset immediately, once, outside of the scheduler.

    Args:
        preset: Preset id/name.
    """
    _run_preset(preset)


def _run_preset(preset: str) -> None:
    """Execute a preset fetch run, logging any errors.

    Args:
        preset: Preset id/name.
    """
    try:
        from streamdoc.core.fetch import run_fetch
    except Exception as exc:
        logger.error("Failed to import runner for preset=%s: %s", preset, exc)
        return
    logger.info("Running preset=%s", preset)
    try:
        artifacts = run_fetch(preset)
    except Exception as exc:
        logger.error("Preset run failed for %s: %s", preset, exc, exc_info=True)
        return
    logger.info("Preset %s completed with %s artifact(s).", preset, len(artifacts))


def sync_jobs() -> None:
    """Reconcile the live APScheduler's jobs with the presets table.

    For every active preset with a schedule, ensures a matching APScheduler
    job exists (added or replaced). Removes APScheduler jobs whose preset no
    longer has a schedule, is inactive, or was deleted. Also ensures the
    scheduled retention cleanup job is always present.

    Safe to call repeatedly. No-op if the scheduler singleton is not running.
    """
    global _scheduler
    if _scheduler is None or _scheduler.state == STATE_STOPPED:
        logger.debug("sync_jobs called but scheduler not running; skipping live reconcile.")
        return

    desired: dict[str, str] = {p.id: (p.schedule or "") for p in _scheduled_presets()}

    # Remove jobs that are no longer desired.
    # Reason: skip the cleanup job — it's managed separately below and
    # should not be removed during preset reconciliation.
    for job in list(_scheduler.get_jobs()):
        if job.id == _CLEANUP_JOB_ID:
            continue
        preset = job.id.removeprefix("streamdoc:") if job.id.startswith("streamdoc:") else None
        if preset is None or preset not in desired:
            try:
                _scheduler.remove_job(job.id)
            except JobLookupError:
                pass

    # Add/replace desired jobs.
    for preset, schedule in desired.items():
        try:
            trigger = _trigger_for(schedule)
            _scheduler.add_job(
                _run_preset,
                trigger=trigger,
                id=_job_id(preset),
                args=[preset],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                name=f"streamdoc:{preset}",
            )
        except Exception as exc:
            logger.error("Failed to schedule job for preset=%s: %s", preset, exc)

    # Reason: ensure the retention cleanup job is always scheduled so
    # that files and notebooks are cleaned up even when no preset jobs
    # complete successfully (e.g., a job hangs or the server restarts).
    _ensure_cleanup_job()
    _ensure_social_auth_refresh_job()


def _ensure_cleanup_job() -> None:
    """Add or replace the scheduled retention cleanup job.

    Reason: cleanup normally only runs at the end of ``run_once``. But
    if a job hangs (e.g., Whisper timeout regression) or the server
    restarts, cleanup never executes and files/notebooks accumulate
    indefinitely. This scheduled job runs cleanup on a configurable
    interval (default: every 60 minutes) independent of job outcomes.
    """
    global _scheduler
    if _scheduler is None or _scheduler.state == STATE_STOPPED:
        return
    if not settings.retention_cleanup_enabled:
        # Reason: if retention is globally disabled, remove any existing
        # cleanup job so it doesn't run pointlessly.
        try:
            _scheduler.remove_job(_CLEANUP_JOB_ID)
        except JobLookupError:
            pass
        return
    try:
        interval_s = int(settings.retention_cleanup_interval_minutes * 60)
        _scheduler.add_job(
            _run_scheduled_cleanup,
            trigger=IntervalTrigger(seconds=interval_s),
            id=_CLEANUP_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            name="streamdoc:retention-cleanup",
        )
        logger.debug(
            "Scheduled retention cleanup job (interval: %.0fm)",
            settings.retention_cleanup_interval_minutes,
        )
    except Exception as exc:
        logger.error("Failed to schedule retention cleanup job: %s", exc)


def _run_social_auth_refresh() -> None:
    """Refresh captured X and Reddit cookies from the persistent profile.

    Reason: only refresh platforms that are both enabled (via
    ``social_*_enabled`` settings) and already authenticated (have an existing
    cookie storage file). Skipping disabled platforms avoids spurious headless
    browser launches and timeout warnings for integrations the operator is not
    using. Skipping unauthenticated platforms avoids a 30s headless browser
    wait for a cookie that will never appear (no prior interactive login).
    """
    candidates: list[tuple[str, Any]] = []
    if settings.social_x_enabled:
        candidates.append(("x", x_auth_manager()))
    if settings.social_reddit_enabled:
        candidates.append(("reddit", reddit_auth_manager()))

    for platform, manager in candidates:
        # Reason: if there is no prior interactive login (no cookie file),
        # a headless refresh cannot capture cookies that don't exist — it
        # will just time out after 30s and emit a misleading warning. Skip
        # it; the operator should run the interactive login first.
        if not manager.is_authenticated():
            logger.debug(
                "Skipping social auth refresh for %s — not authenticated "
                "(no prior interactive login found)",
                platform,
            )
            continue
        try:
            ok = manager.refresh()
            if ok:
                logger.info("Scheduled social auth refresh succeeded for %s", platform)
            else:
                logger.warning(
                    "Scheduled social auth refresh failed for %s; "
                    "interactive login may be required.",
                    platform,
                )
        except Exception:
            logger.exception("Scheduled social auth refresh raised for %s", platform)


def _ensure_social_auth_refresh_job() -> None:
    """Add or replace the scheduled social auth refresh job."""
    if _scheduler is None or _scheduler.state == STATE_STOPPED:
        return
    if not settings.social_auth_refresh_interval_hours:
        try:
            _scheduler.remove_job(_SOCIAL_REFRESH_JOB_ID)
        except JobLookupError:
            pass
        return
    try:
        interval_s = int(settings.social_auth_refresh_interval_hours * 3600)
        _scheduler.add_job(
            _run_social_auth_refresh,
            trigger=IntervalTrigger(seconds=interval_s),
            id=_SOCIAL_REFRESH_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            name="streamdoc:social-auth-refresh",
        )
        logger.debug(
            "Scheduled social auth refresh job (interval: %.0fh)",
            settings.social_auth_refresh_interval_hours,
        )
    except Exception:
        logger.exception("Failed to schedule social auth refresh job")


def _migrate_legacy_state() -> None:
    """One-time import of retired scheduler_state.json into preset schedules.

    For each legacy job whose preset exists in the DB and has no schedule set,
    copy the legacy schedule into the preset's ``schedule`` field. Then rename
    the legacy file aside so it is not re-imported.
    """
    if not _LEGACY_STATE_PATH.exists():
        return
    try:
        state = json.loads(_LEGACY_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Legacy scheduler state unreadable: %s", _LEGACY_STATE_PATH)
        return
    jobs = state.get("jobs", []) if isinstance(state, dict) else []
    if not jobs:
        try:
            _LEGACY_STATE_PATH.rename(_LEGACY_STATE_PATH.with_suffix(".json.bak"))
        except Exception:
            pass
        return
    migrated = 0
    with session_scope() as s:
        for j in jobs:
            preset = j.get("preset")
            schedule = j.get("schedule")
            if not preset or not schedule:
                continue
            p = s.get(Preset, preset)
            if p is None:
                logger.info("Legacy job preset '%s' not found; skipping.", preset)
                continue
            if p.schedule:
                # Preset already has a schedule; keep the existing one.
                continue
            p.schedule = schedule
            migrated += 1
    if migrated:
        logger.info("Migrated %d legacy scheduled job(s) into preset schedules.", migrated)
    try:
        _LEGACY_STATE_PATH.rename(_LEGACY_STATE_PATH.with_suffix(".json.bak"))
    except Exception as exc:
        logger.warning("Could not retire legacy scheduler state: %s", exc)


def start_scheduler() -> None:
    """Start the singleton scheduler and sync jobs from the DB.

    Called once on API startup. Idempotent: if already running, just syncs.
    """
    global _scheduler
    _migrate_legacy_state()
    if _scheduler is None:
        _scheduler = _make_scheduler()
    if _scheduler.state == STATE_STOPPED:
        _scheduler.start()
        logger.info("StreamDoc scheduler started (max_workers=%s).", settings.scheduler_max_workers)
    sync_jobs()


def shutdown_scheduler() -> None:
    """Shut down the singleton scheduler if it is running.

    Called on API shutdown. Safe to call multiple times.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.state != STATE_STOPPED:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("StreamDoc scheduler stopped.")
        except Exception as exc:
            logger.warning("Scheduler shutdown error: %s", exc)


def run_scheduler() -> None:
    """Start the scheduler and block until interrupted.

    Legacy entrypoint for standalone CLI use. The API process uses
    ``start_scheduler``/``shutdown_scheduler`` instead.
    """
    start_scheduler()
    import time

    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        shutdown_scheduler()
