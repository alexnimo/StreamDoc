"""API routes for runtime plugin/tool management.

Provides endpoints to check plugin versions (yt-dlp, ffmpeg, whisper),
trigger manual updates, view the update history log, and check the
PO Token provider container status.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import (
    PluginStatusOut,
    PluginUpdateLogOut,
    PluginUpdateResultOut,
)
from streamdoc.core.tools import (
    get_all_plugin_statuses,
    get_plugin_status,
    get_update_logs,
    update_plugin,
)

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/plugins", response_model=list[PluginStatusOut])
def list_plugins() -> list[PluginStatusOut]:
    """List all registered plugins with version status.

    Uses cached version data unless the cadence window has elapsed.
    """
    statuses = get_all_plugin_statuses(force_check=False)
    return [PluginStatusOut(**s.__dict__) for s in statuses]


@router.post("/plugins/check", response_model=list[PluginStatusOut])
def check_all_plugins() -> list[PluginStatusOut]:
    """Force a fresh version check for all plugins (hits PyPI)."""
    statuses = get_all_plugin_statuses(force_check=True)
    return [PluginStatusOut(**s.__dict__) for s in statuses]


@router.post("/plugins/{name}/check", response_model=PluginStatusOut)
def check_plugin(name: str) -> PluginStatusOut:
    """Force a fresh version check for a single plugin."""
    try:
        status = get_plugin_status(name, force_check=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PluginStatusOut(**status.__dict__)


@router.post("/plugins/{name}/update", response_model=PluginUpdateResultOut)
def update_single_plugin(name: str) -> PluginUpdateResultOut:
    """Run a manual update for a single plugin (yt-dlp, whisper only)."""
    try:
        result = update_plugin(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PluginUpdateResultOut(
        plugin=result.plugin,
        action=result.action,
        from_version=result.from_version,
        to_version=result.to_version,
        success=result.success,
        message=result.message,
        timestamp=result.timestamp,
    )


@router.get("/logs", response_model=list[PluginUpdateLogOut])
def list_update_logs(limit: int = 50) -> list[PluginUpdateLogOut]:
    """Return recent plugin update/check log entries (newest first)."""
    logs = get_update_logs(limit=limit)
    return [PluginUpdateLogOut(**log) for log in logs]


@router.get("/pot-status")
def pot_status() -> dict[str, str | bool]:
    """Check the PO Token provider container status.

    Returns whether the POT provider is running, reachable, and whether
    Docker is available. Used by the frontend to display a status badge.
    """
    from streamdoc.core.pot_provider import get_pot_provider_status

    return get_pot_provider_status()
