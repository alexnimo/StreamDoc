"""Notification aggregation for the notification bell.

Collects notifications from multiple sources:
  - Plugin updates available (from ``core.tools``)
  - NotebookLM auth expired (from the auth status check)
  - Recent job completions/failures (from the jobs DB)

The frontend polls ``/api/notifications`` periodically and displays the
results in a bell dropdown. Dismissed notifications are tracked client-side
via localStorage so the backend remains stateless.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from streamdoc.api.schemas import NotificationOut

logger = logging.getLogger(__name__)

UTC = timezone.utc


def _now_iso() -> str:
    """Return the current UTC time as an ISO string."""
    return datetime.now(UTC).isoformat()


def _collect_plugin_update_notifications() -> list[NotificationOut]:
    """Collect notifications for plugins with updates available.

    Returns:
        List of NotificationOut for each plugin with an update available.
    """
    notifications: list[NotificationOut] = []
    try:
        from streamdoc.core.tools import get_all_plugin_statuses

        statuses = get_all_plugin_statuses(force_check=False)
        for status in statuses:
            if status.update_available:
                version_info = ""
                if status.installed_version and status.latest_version:
                    version_info = f" ({status.installed_version} → {status.latest_version})"
                notifications.append(NotificationOut(
                    id=f"plugin_update:{status.name}",
                    type="plugin_update",
                    title=f"Update available: {status.display_name}",
                    message=f"{status.display_name} has a newer version{version_info}.",
                    severity="warning",
                    timestamp=status.last_checked or _now_iso(),
                    action_url="/settings",
                    action_label="Update",
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Plugin update notification check failed: %s", exc)
    return notifications


async def _collect_notebooklm_auth_notifications() -> list[NotificationOut]:
    """Collect a notification if NotebookLM auth is expired or not configured.

    Returns:
        List with 0 or 1 NotificationOut.
    """
    notifications: list[NotificationOut] = []
    try:
        from streamdoc.config import settings

        if not settings.notebooklm_enabled:
            return notifications

        from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager

        auth = NotebookLMAuthManager(
            settings.notebooklm_storage_state_path,
            settings.notebooklm_profile,
        )
        if not auth.is_configured():
            notifications.append(NotificationOut(
                id="notebooklm_auth:not_configured",
                type="notebooklm_auth",
                title="NotebookLM: Authentication required",
                message="NotebookLM is not configured. Click to log in.",
                severity="warning",
                timestamp=_now_iso(),
                action_url="/notebooklm",
                action_label="Log in",
            ))
            return notifications

        status = await auth.check_session_freshness(auto_refresh=False)
        if not status.is_valid:
            notifications.append(NotificationOut(
                id="notebooklm_auth:expired",
                type="notebooklm_auth",
                title="NotebookLM: Session expired",
                message=status.message or "Authentication cookie has expired.",
                severity="error",
                timestamp=_now_iso(),
                action_url="/notebooklm",
                action_label="Re-authenticate",
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("NotebookLM auth notification check failed: %s", exc)
    return notifications


def _collect_job_notifications() -> list[NotificationOut]:
    """Collect notifications for recently completed/failed jobs.

    Looks at jobs from the last 24 hours that have a completed or failed
    status. The frontend tracks which ones have been "seen" via localStorage.

    Returns:
        List of NotificationOut for recent completed/failed jobs.
    """
    notifications: list[NotificationOut] = []
    try:
        from streamdoc.core.jobs import list_jobs as _list_jobs

        jobs = _list_jobs(limit=20)
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        for job in jobs:
            status = job.get("status", "")
            if status not in ("completed", "failed"):
                continue
            completed_at = job.get("completed_at")
            if not completed_at:
                continue
            try:
                ts = datetime.fromisoformat(completed_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            job_id = job.get("id", "")
            preset = job.get("preset_name", "unknown")
            if status == "failed":
                notifications.append(NotificationOut(
                    id=f"job_failed:{job_id}",
                    type="job_failed",
                    title=f"Job failed: {preset}",
                    message=f"Job {job_id[:8]} for preset '{preset}' failed.",
                    severity="error",
                    timestamp=completed_at,
                    action_url="/jobs",
                    action_label="View jobs",
                ))
            else:
                artifact_count = job.get("artifact_count", 0)
                notifications.append(NotificationOut(
                    id=f"job_completed:{job_id}",
                    type="job_completed",
                    title=f"Job completed: {preset}",
                    message=f"Job {job_id[:8]} completed with {artifact_count} artifact(s).",
                    severity="info",
                    timestamp=completed_at,
                    action_url="/jobs",
                    action_label="View jobs",
                ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Job notification check failed: %s", exc)
    return notifications


async def get_notifications() -> list[NotificationOut]:
    """Aggregate notifications from all sources.

    Returns:
        List of NotificationOut sorted by timestamp (newest first).
    """
    notifications: list[NotificationOut] = []

    # Plugin updates (synchronous, uses cached data)
    notifications.extend(_collect_plugin_update_notifications())

    # NotebookLM auth (async)
    notifications.extend(await _collect_notebooklm_auth_notifications())

    # Job completions/failures (synchronous, reads DB)
    notifications.extend(_collect_job_notifications())

    # Sort by timestamp, newest first
    notifications.sort(key=lambda n: n.timestamp, reverse=True)
    return notifications
