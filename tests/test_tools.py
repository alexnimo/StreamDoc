"""Tests for the runtime plugin version/update service."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from streamdoc.config import settings
from streamdoc.core import tools


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect the tools state file to a temp dir so tests don't pollute real state."""
    monkeypatch.setattr(tools, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tools, "_STATE_PATH", tmp_path / "tools_state.json")
    return tmp_path


def test_classify_error_patterns():
    """classify_download_error is tested in test_downloader; here we test tools."""
    # Sanity: the tools module exposes the registry
    assert "yt_dlp" in tools._PLUGIN_REGISTRY
    assert "ffmpeg" in tools._PLUGIN_REGISTRY
    assert "faster_whisper" in tools._PLUGIN_REGISTRY


def test_get_plugin_status_unknown_plugin(isolated_state):
    """Unknown plugin name should raise ValueError."""
    with pytest.raises(ValueError):
        tools.get_plugin_status("nonexistent")


def test_get_plugin_status_ffmpeg_no_pypi(isolated_state, monkeypatch):
    """ffmpeg has no PyPI package; latest_version should stay None without a network call."""
    monkeypatch.setattr(settings, "tool_update_enabled", True)
    monkeypatch.setattr(settings, "tool_auto_update_ffmpeg", False)
    monkeypatch.setattr(settings, "tool_update_cadence", "manual")

    status = tools.get_plugin_status("ffmpeg", force_check=False)
    assert status.name == "ffmpeg"
    assert status.latest_version is None
    assert status.update_available is False


def test_should_check_manual_cadence_never_checks(monkeypatch):
    """Manual cadence should never auto-trigger a check."""
    monkeypatch.setattr(settings, "tool_update_cadence", "manual")
    assert tools._should_check("yt_dlp", None) is False
    assert tools._should_check("yt_dlp", "2020-01-01T00:00:00+00:00") is False


def test_should_check_daily_cadence(monkeypatch):
    """Daily cadence should check when last check was >1 day ago."""
    monkeypatch.setattr(settings, "tool_update_cadence", "daily")
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert tools._should_check("yt_dlp", old) is True
    recent = datetime.now(timezone.utc).isoformat()
    assert tools._should_check("yt_dlp", recent) is False


def test_should_check_no_last_checked(monkeypatch):
    """With no prior check, any non-manual cadence should check."""
    monkeypatch.setattr(settings, "tool_update_cadence", "weekly")
    assert tools._should_check("yt_dlp", None) is True


def test_update_plugin_not_pip_managed(isolated_state):
    """ffmpeg is not pip-managed; update should return a failure log entry."""
    result = tools.update_plugin("ffmpeg")
    assert result.success is False
    assert "manually" in result.message.lower() or "pip" in result.message.lower()


def test_update_plugin_unknown(isolated_state):
    """Unknown plugin update should raise ValueError."""
    with pytest.raises(ValueError):
        tools.update_plugin("nonexistent")


def test_get_update_logs_returns_newest_first(isolated_state):
    """Logs should be returned newest-first."""
    state = {
        "logs": [
            {"timestamp": "2026-01-01T00:00:00+00:00", "plugin": "yt_dlp", "action": "check",
             "from_version": "1", "to_version": "2", "success": True, "message": "old"},
            {"timestamp": "2026-01-02T00:00:00+00:00", "plugin": "yt_dlp", "action": "update",
             "from_version": "1", "to_version": "2", "success": True, "message": "new"},
        ]
    }
    tools._save_state(state)
    logs = tools.get_update_logs(10)
    assert len(logs) == 2
    assert logs[0]["message"] == "new"
    assert logs[1]["message"] == "old"


def test_state_persistence_roundtrip(isolated_state):
    """State save/load should round-trip correctly."""
    state = {"plugins": {"yt_dlp": {"last_check": "2026-01-01"}}, "logs": []}
    tools._save_state(state)
    loaded = tools._load_state()
    assert loaded["plugins"]["yt_dlp"]["last_check"] == "2026-01-01"


def test_get_all_plugin_statuses_returns_three(isolated_state, monkeypatch):
    """get_all_plugin_statuses should return all 3 registered plugins."""
    monkeypatch.setattr(settings, "tool_update_enabled", True)
    monkeypatch.setattr(settings, "tool_update_cadence", "manual")
    monkeypatch.setattr(settings, "tool_auto_update_yt_dlp", True)
    monkeypatch.setattr(settings, "tool_auto_update_ffmpeg", False)
    monkeypatch.setattr(settings, "tool_auto_update_whisper", False)

    statuses = tools.get_all_plugin_statuses(force_check=False)
    names = [s.name for s in statuses]
    assert "yt_dlp" in names
    assert "ffmpeg" in names
    assert "faster_whisper" in names
    # yt_dlp should have auto_update_enabled=True
    yt = next(s for s in statuses if s.name == "yt_dlp")
    assert yt.auto_update_enabled is True


def test_run_startup_check_disabled(monkeypatch, isolated_state):
    """When tool_update_enabled is False, startup check should not force updates."""
    monkeypatch.setattr(settings, "tool_update_enabled", False)
    statuses = tools.run_startup_check()
    assert len(statuses) == 3
