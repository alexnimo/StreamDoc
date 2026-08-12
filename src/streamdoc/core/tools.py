"""Runtime plugin/tool version checking and auto-update service.

Detects installed versions of yt-dlp, ffmpeg, and faster-whisper, checks
for newer releases, and (when enabled) auto-updates pip-managed plugins.
Results are persisted to a JSON state file so the cadence (daily/weekly)
is respected across restarts, and a rolling update log is exposed to the UI.

Reason: YouTube frequently changes its bot-detection logic, so an outdated
yt-dlp is the single most common cause of download failures. Surfacing
version status and auto-updating keeps the pipeline healthy without
requiring the operator to manually run pip commands.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from streamdoc.config import settings

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Reason: persist check timestamps and update history so the cadence is
# honored across restarts and the UI can show what happened.
_STATE_DIR = Path("data/State")
_STATE_PATH = _STATE_DIR / "tools_state.json"

# Plugins managed by this service. Each entry maps the internal name to
# (display_name, pypi_package_or_none, auto_update_config_flag).
_PLUGIN_REGISTRY: dict[str, tuple[str, str | None, str]] = {
    "yt_dlp": ("yt-dlp", "yt-dlp", "tool_auto_update_yt_dlp"),
    "faster_whisper": ("faster-whisper", "faster-whisper", "tool_auto_update_whisper"),
    "ffmpeg": ("ffmpeg", None, "tool_auto_update_ffmpeg"),
}

_CADENCE_DAYS = {"daily": 1, "weekly": 7, "manual": 0}


@dataclass
class PluginStatus:
    """Status of a single runtime plugin.

    Attributes:
        name: Internal plugin identifier (yt_dlp, ffmpeg, faster_whisper).
        display_name: Human-readable name for the UI.
        installed_version: Currently installed version string, or None.
        latest_version: Latest available version string, or None if unknown.
        update_available: True if a newer version is available.
        auto_update_enabled: Whether auto-update is enabled for this plugin.
        binary_path: Path to the binary/module, if detected.
        last_checked: ISO timestamp of the last version check.
        last_updated: ISO timestamp of the last successful update.
        update_message: Human-readable result of the last update attempt.
    """
    name: str
    display_name: str
    installed_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    auto_update_enabled: bool = False
    binary_path: str | None = None
    last_checked: str | None = None
    last_updated: str | None = None
    update_message: str | None = None


@dataclass
class UpdateLogEntry:
    """A single entry in the update history log.

    Attributes:
        timestamp: ISO timestamp of the event.
        plugin: Plugin name the event applies to.
        action: "check" or "update".
        from_version: Version before the action (if known).
        to_version: Version after the action (if known).
        success: Whether the action succeeded.
        message: Human-readable detail.
    """
    timestamp: str
    plugin: str
    action: str
    from_version: str | None = None
    to_version: str | None = None
    success: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    """Load the persisted tools state, returning an empty dict on failure."""
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to load tools state: %s", exc)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    """Persist the tools state to disk."""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to save tools state: %s", exc)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def _detect_yt_dlp_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for yt-dlp."""
    try:
        import yt_dlp
        version = getattr(yt_dlp, "version", None)
        if version is not None:
            return version.__version__, None
    except Exception:
        pass
    # Fallback: run yt-dlp --version
    binary = shutil.which("yt-dlp")
    if binary:
        try:
            result = subprocess.run(
                [binary, "--version"], capture_output=True, text=True,
                timeout=10, check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip().splitlines()[0].strip(), binary
        except Exception:
            pass
    return None, None


def _detect_faster_whisper_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for faster-whisper."""
    try:
        import faster_whisper
        version = getattr(faster_whisper, "__version__", None)
        if version:
            return version, None
    except Exception:
        pass
    return None, None


def _detect_ffmpeg_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for ffmpeg."""
    binary = shutil.which("ffmpeg")
    if not binary:
        return None, None
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, text=True,
            timeout=10, check=False,
        )
        if result.returncode == 0:
            # First line: "ffmpeg version 7.0.2 Copyright ..."
            first_line = result.stdout.strip().splitlines()[0]
            parts = first_line.split()
            if len(parts) >= 3:
                return parts[2].strip(), binary
    except Exception:
        pass
    return None, binary


def _detect_version(name: str) -> tuple[str | None, str | None]:
    """Dispatch to the correct version detector for a plugin."""
    if name == "yt_dlp":
        return _detect_yt_dlp_version()
    if name == "faster_whisper":
        return _detect_faster_whisper_version()
    if name == "ffmpeg":
        return _detect_ffmpeg_version()
    return None, None


# ---------------------------------------------------------------------------
# Latest version checking (PyPI)
# ---------------------------------------------------------------------------

def _fetch_pypi_latest(package: str) -> str | None:
    """Fetch the latest version of a package from PyPI.

    Args:
        package: PyPI package name (e.g. "yt-dlp").

    Returns:
        Latest version string, or None if the check failed.
    """
    import urllib.request
    import urllib.error

    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StreamDoc/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("info", {}).get("version")
    except Exception as exc:
        logger.debug("PyPI latest check failed for %s: %s", package, exc)
        return None


def _compare_versions(installed: str, latest: str) -> bool:
    """Return True if latest is newer than installed.

    Uses packaging.version when available, falling back to a simple
    string comparison for safety.
    """
    try:
        from packaging.version import parse
        return parse(latest) > parse(installed)
    except Exception:
        return latest != installed


# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------

def _run_uv_upgrade(package: str) -> tuple[bool, str]:
    """Upgrade a pip package via uv.

    Args:
        package: PyPI package name to upgrade.

    Returns:
        Tuple of (success, message).
    """
    try:
        result = subprocess.run(
            ["uv", "pip", "install", "--upgrade", package],
            capture_output=True, text=True, timeout=120, check=False,
            cwd=str(Path.cwd()),
        )
        if result.returncode == 0:
            msg = (result.stdout or "").strip().splitlines()
            return True, msg[-1] if msg else "Updated"
        return False, (result.stderr or result.stdout or "uv failed").strip()
    except FileNotFoundError:
        # Reason: uv not on PATH — fall back to pip
        return _run_pip_upgrade(package)
    except Exception as exc:
        return False, str(exc)


def _run_pip_upgrade(package: str) -> tuple[bool, str]:
    """Fallback: upgrade a pip package via python -m pip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", package],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode == 0:
            return True, "Updated via pip"
        return False, (result.stderr or result.stdout or "pip failed").strip()
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_plugin_status(name: str, *, force_check: bool = False) -> PluginStatus:
    """Get the status of a single plugin, optionally checking for updates.

    Args:
        name: Plugin identifier (yt_dlp, ffmpeg, faster_whisper).
        force_check: If True, always fetch the latest version from PyPI
            regardless of cadence. Used by manual "check now" actions.

    Returns:
        PluginStatus with installed/latest versions and update availability.
    """
    if name not in _PLUGIN_REGISTRY:
        raise ValueError(f"Unknown plugin: {name}")
    display_name, pypi_pkg, auto_flag = _PLUGIN_REGISTRY[name]
    state = _load_state()
    plugin_state = state.get("plugins", {}).get(name, {})

    installed, binary = _detect_version(name)
    auto_enabled = bool(getattr(settings, auto_flag, False)) and settings.tool_update_enabled

    last_checked = plugin_state.get("last_check")
    last_updated = plugin_state.get("last_update")
    update_message = plugin_state.get("update_message")

    # Reason: only hit PyPI when the cadence allows it (or when forced).
    # This avoids unnecessary network calls on every UI load.
    latest = plugin_state.get("last_known_latest")
    should_check = force_check or _should_check(name, last_checked)
    if pypi_pkg and should_check:
        latest = _fetch_pypi_latest(pypi_pkg)
        last_checked = _now_iso()
        plugin_state["last_check"] = last_checked
        plugin_state["last_known_latest"] = latest
        state.setdefault("plugins", {})[name] = plugin_state
        _append_log(state, UpdateLogEntry(
            timestamp=last_checked, plugin=name, action="check",
            from_version=installed, to_version=latest,
            success=latest is not None,
            message="Checked PyPI" if latest else "PyPI check failed",
        ))
        _save_state(state)

    update_available = False
    if installed and latest:
        update_available = _compare_versions(installed, latest)

    return PluginStatus(
        name=name,
        display_name=display_name,
        installed_version=installed,
        latest_version=latest,
        update_available=update_available,
        auto_update_enabled=auto_enabled,
        binary_path=binary,
        last_checked=last_checked,
        last_updated=last_updated,
        update_message=update_message,
    )


def get_all_plugin_statuses(*, force_check: bool = False) -> list[PluginStatus]:
    """Get status for all registered plugins.

    Args:
        force_check: If True, force a fresh version check for all plugins.

    Returns:
        List of PluginStatus for yt_dlp, faster_whisper, and ffmpeg.
    """
    return [get_plugin_status(name, force_check=force_check) for name in _PLUGIN_REGISTRY]


def update_plugin(name: str) -> UpdateLogEntry:
    """Run an auto-update for a plugin (yt_dlp or faster_whisper only).

    Args:
        name: Plugin identifier.

    Returns:
        UpdateLogEntry describing the result.
    """
    if name not in _PLUGIN_REGISTRY:
        raise ValueError(f"Unknown plugin: {name}")
    display_name, pypi_pkg, _ = _PLUGIN_REGISTRY[name]
    if not pypi_pkg:
        entry = UpdateLogEntry(
            timestamp=_now_iso(), plugin=name, action="update",
            success=False, message=f"{display_name} is not pip-managed; update manually.",
        )
        _append_log_to_state(entry)
        return entry

    installed_before, _ = _detect_version(name)
    success, message = _run_uv_upgrade(pypi_pkg)
    installed_after, _ = _detect_version(name)
    timestamp = _now_iso()

    state = _load_state()
    plugin_state = state.setdefault("plugins", {}).setdefault(name, {})
    plugin_state["last_update"] = timestamp
    plugin_state["update_message"] = message
    if success and installed_after:
        plugin_state["last_known_latest"] = installed_after
    _save_state(state)

    entry = UpdateLogEntry(
        timestamp=timestamp, plugin=name, action="update",
        from_version=installed_before, to_version=installed_after,
        success=success, message=message,
    )
    _append_log_to_state(entry)
    return entry


def get_update_logs(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent update log entries (newest first).

    Args:
        limit: Maximum number of entries to return.

    Returns:
        List of log entry dicts.
    """
    state = _load_state()
    logs = state.get("logs", [])
    return list(reversed(logs))[:limit]


def run_startup_check() -> list[PluginStatus]:
    """Run a version check + auto-update on startup if cadence allows.

    Respects ``tool_update_check_on_startup`` and ``tool_update_cadence``.
    For each plugin with auto-update enabled, attempts the upgrade after
    confirming a newer version is available.

    Returns:
        List of PluginStatus for all plugins after the check.
    """
    if not settings.tool_update_enabled or not settings.tool_update_check_on_startup:
        logger.debug("Tool update check disabled on startup")
        return get_all_plugin_statuses(force_check=False)

    statuses = get_all_plugin_statuses(force_check=_should_force_on_startup())
    # Reason: auto-update only pip-managed plugins with the flag on.
    for status in statuses:
        if status.update_available and status.auto_update_enabled:
            logger.info("Auto-updating %s: %s -> %s",
                        status.name, status.installed_version, status.latest_version)
            update_plugin(status.name)
    # Reason: re-detect after updates so the returned statuses reflect
    # the post-update versions.
    return get_all_plugin_statuses(force_check=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _should_check(name: str, last_checked: str | None) -> bool:
    """Return True if enough time has passed to re-check this plugin."""
    cadence = settings.tool_update_cadence
    days = _CADENCE_DAYS.get(cadence, 7)
    if days == 0:
        # Reason: manual cadence means never auto-check; only force_check
        # triggers a network call.
        return False
    if not last_checked:
        return True
    try:
        last = datetime.fromisoformat(last_checked)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return datetime.now(UTC) - last >= timedelta(days=days)
    except Exception:
        return True


def _should_force_on_startup() -> bool:
    """Return True if the startup check should force a network call."""
    # Reason: on startup we always want a fresh check (the server may have
    # been down for a while). The cadence is still honored for non-startup
    # UI loads.
    return True


def _append_log(state: dict[str, Any], entry: UpdateLogEntry) -> None:
    """Append a log entry to the in-memory state dict (not saved here)."""
    logs = state.setdefault("logs", [])
    logs.append(asdict(entry))
    # Reason: keep the log bounded so the state file doesn't grow forever.
    if len(logs) > 200:
        del logs[:len(logs) - 200]


def _append_log_to_state(entry: UpdateLogEntry) -> None:
    """Load state, append a log entry, and save."""
    state = _load_state()
    _append_log(state, entry)
    _save_state(state)
