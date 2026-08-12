"""Tests for the DB-driven scheduler sync logic.

Verifies that the presets table is the single source of truth for scheduled
jobs and that add_job/remove_job/list_jobs stay in sync with it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamdoc.config import Settings
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc import scheduler as sched


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Isolate DB + legacy state path per test."""
    db_path = tmp_path / "test.sqlite"
    output_root = tmp_path / "outputs"
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    s = Settings(
        db_path=str(db_path),
        output_root=str(output_root),
        media_root=str(media_root),
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    # Reason: the legacy state path is computed at import time from
    # settings.media_root, so patch the module attribute directly.
    monkeypatch.setattr(sched, "_LEGACY_STATE_PATH", tmp_path / "scheduler_state.json")
    # Scheduler singleton must not leak a real BackgroundScheduler between tests.
    monkeypatch.setattr(sched, "_scheduler", None)
    init_db()
    yield


def _seed_preset(name: str, schedule: str | None = None, active: bool = True) -> None:
    """Insert a preset row directly into the DB."""
    with session_scope() as s:
        s.merge(
            Preset(
                id=name,
                name=name,
                channel_list_id="fake://unit-test",
                prompt_md="",
                outputs="pdf,markdown",
                schedule=schedule,
                active=active,
            )
        )


def test_list_jobs_returns_only_scheduled_active_presets():
    """list_jobs derives from the presets table, not a side-store."""
    _seed_preset("alpha", schedule="interval:3600")
    _seed_preset("beta", schedule=None)
    _seed_preset("gamma", schedule="cron:0 6 * * *")
    _seed_preset("delta", schedule="interval:7200", active=False)

    jobs = sched.list_jobs()
    presets = sorted(j["preset"] for j in jobs)
    assert presets == ["alpha", "gamma"]
    assert all("trigger" in j and "schedule" in j and "id" in j for j in jobs)


def test_add_job_writes_schedule_to_preset():
    """add_job sets the preset's schedule field (single source of truth)."""
    _seed_preset("alpha", schedule=None)
    # sync_jobs is a no-op because the singleton scheduler isn't running.
    job = sched.add_job("alpha", "interval:3600")

    assert job["preset"] == "alpha"
    assert job["schedule"] == "interval:3600"
    with session_scope() as s:
        p = s.get(Preset, "alpha")
        assert p.schedule == "interval:3600"
    # And list_jobs now reflects it.
    assert any(j["preset"] == "alpha" for j in sched.list_jobs())


def test_add_job_rejects_unknown_preset():
    """add_job raises when the preset does not exist."""
    with pytest.raises(ValueError, match="not found"):
        sched.add_job("ghost", "interval:3600")


def test_add_job_rejects_invalid_schedule():
    """add_job raises on a malformed schedule string."""
    _seed_preset("alpha", schedule=None)
    with pytest.raises(ValueError):
        sched.add_job("alpha", "cron:bad expr here totally")


def test_remove_job_clears_schedule():
    """remove_job nulls the preset's schedule field."""
    _seed_preset("alpha", schedule="interval:3600")
    sched.remove_job("alpha")
    with session_scope() as s:
        p = s.get(Preset, "alpha")
        assert p.schedule is None
    assert all(j["preset"] != "alpha" for j in sched.list_jobs())


def test_remove_job_missing_preset_is_safe():
    """remove_job on a non-existent preset does not raise."""
    sched.remove_job("ghost")  # should not raise


def test_sync_jobs_noop_when_scheduler_not_running():
    """sync_jobs is a safe no-op when the singleton isn't started."""
    _seed_preset("alpha", schedule="interval:3600")
    # Should not raise even though no scheduler is running.
    sched.sync_jobs()


def test_legacy_state_migration_imports_into_presets():
    """Legacy scheduler_state.json schedules are imported into preset rows."""
    _seed_preset("alpha", schedule=None)
    _seed_preset("beta", schedule="interval:7200")  # already has a schedule
    legacy = {
        "jobs": [
            {"id": "streamdoc:alpha", "preset": "alpha", "schedule": "cron:0 6 * * *"},
            {"id": "streamdoc:beta", "preset": "beta", "schedule": "cron:0 8 * * *"},
            {"id": "streamdoc:ghost", "preset": "ghost", "schedule": "interval:3600"},
        ]
    }
    sched._LEGACY_STATE_PATH.write_text(json.dumps(legacy), encoding="utf-8")

    sched._migrate_legacy_state()

    with session_scope() as s:
        alpha = s.get(Preset, "alpha")
        beta = s.get(Preset, "beta")
        # alpha had no schedule -> imported from legacy
        assert alpha.schedule == "cron:0 6 * * *"
        # beta already had a schedule -> kept existing, not overwritten
        assert beta.schedule == "interval:7200"
    # Legacy file retired (renamed to .bak).
    assert not sched._LEGACY_STATE_PATH.exists()
    assert sched._LEGACY_STATE_PATH.with_suffix(".json.bak").exists()


def test_legacy_state_migration_no_file_is_safe():
    """_migrate_legacy_state is a no-op when no legacy file exists."""
    sched._migrate_legacy_state()  # should not raise


def test_presets_coerce_interval_hours_to_schedule():
    """Old presets with only schedule_interval_hours get a derived schedule."""
    from streamdoc.presets import _coerce_preset

    p = _coerce_preset({"name": "legacy", "schedule_interval_hours": 6})
    assert p.schedule == "interval:21600"

    # Explicit schedule wins over interval_hours.
    p2 = _coerce_preset({"name": "explicit", "schedule": "cron:0 6 * * *", "schedule_interval_hours": 6})
    assert p2.schedule == "cron:0 6 * * *"

    # No schedule and no interval -> None.
    p3 = _coerce_preset({"name": "manual"})
    assert p3.schedule is None


def test_cleanup_job_id_is_dedicated():
    """The cleanup job ID is separate from preset job IDs."""
    assert sched._CLEANUP_JOB_ID == "streamdoc:retention-cleanup"
    assert sched._CLEANUP_JOB_ID != sched._job_id("any-preset")


def test_scheduled_cleanup_calls_run_cleanup(monkeypatch):
    """_run_scheduled_cleanup delegates to core.cleanup.run_cleanup."""
    called = {"run": False}

    def _fake_run_cleanup():
        called["run"] = True
        return {"videos_deleted": 1}

    # Reason: patch run_cleanup in the module where _run_scheduled_cleanup
    # imports it (via `from streamdoc.core.cleanup import run_cleanup`).
    import streamdoc.core.cleanup as cleanup_mod
    monkeypatch.setattr(cleanup_mod, "run_cleanup", _fake_run_cleanup)

    sched._run_scheduled_cleanup()
    assert called["run"] is True


def test_scheduled_cleanup_handles_errors(monkeypatch):
    """_run_scheduled_cleanup should not raise on cleanup errors."""
    def _failing_cleanup():
        raise RuntimeError("DB locked")

    import streamdoc.core.cleanup as cleanup_mod
    monkeypatch.setattr(cleanup_mod, "run_cleanup", _failing_cleanup)

    # Reason: should not raise — errors are logged, not propagated.
    sched._run_scheduled_cleanup()


def test_ensure_cleanup_job_noop_when_not_running():
    """_ensure_cleanup_job is a safe no-op when scheduler isn't running."""
    # Reason: _scheduler is None (set by the fixture), so this should
    # just return without raising.
    sched._ensure_cleanup_job()


def test_ensure_cleanup_job_skips_when_retention_disabled(monkeypatch, tmp_path):
    """_ensure_cleanup_job does nothing when retention is globally disabled."""
    from apscheduler.schedulers.background import BackgroundScheduler

    s = Settings(
        db_path=str(tmp_path / "test.sqlite"),
        output_root=str(tmp_path / "outputs"),
        media_root=str(tmp_path / "media"),
        retention_cleanup_enabled=False,
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    monkeypatch.setattr(sched, "settings", s)

    # Reason: create a real BackgroundScheduler so _ensure_cleanup_job
    # can actually try to add/remove jobs.
    test_sched = BackgroundScheduler()
    test_sched.start()
    monkeypatch.setattr(sched, "_scheduler", test_sched)
    try:
        sched._ensure_cleanup_job()
        # Reason: no cleanup job should have been added.
        job_ids = [j.id for j in test_sched.get_jobs()]
        assert sched._CLEANUP_JOB_ID not in job_ids
    finally:
        test_sched.shutdown(wait=False)


def test_ensure_cleanup_job_adds_interval_job(monkeypatch, tmp_path):
    """_ensure_cleanup_job adds an interval job when retention is enabled."""
    from apscheduler.schedulers.background import BackgroundScheduler

    s = Settings(
        db_path=str(tmp_path / "test.sqlite"),
        output_root=str(tmp_path / "outputs"),
        media_root=str(tmp_path / "media"),
        retention_cleanup_enabled=True,
        retention_cleanup_interval_minutes=30.0,
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    monkeypatch.setattr(sched, "settings", s)

    test_sched = BackgroundScheduler()
    test_sched.start()
    monkeypatch.setattr(sched, "_scheduler", test_sched)
    try:
        sched._ensure_cleanup_job()
        job_ids = [j.id for j in test_sched.get_jobs()]
        assert sched._CLEANUP_JOB_ID in job_ids
    finally:
        test_sched.shutdown(wait=False)


# ---------------------------------------------------------------------------
# _run_social_auth_refresh — enabled-flag and authentication gating
# ---------------------------------------------------------------------------

def test_social_auth_refresh_skips_disabled_platforms(monkeypatch, tmp_path):
    """Disabled platforms should not be refreshed at all."""
    s = Settings(
        db_path=str(tmp_path / "test.sqlite"),
        output_root=str(tmp_path / "outputs"),
        media_root=str(tmp_path / "media"),
        social_x_enabled=True,
        social_reddit_enabled=False,
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    monkeypatch.setattr(sched, "settings", s)

    refreshed: list[str] = []

    class FakeManager:
        def __init__(self, platform: str):
            self.platform = platform

        def is_authenticated(self) -> bool:
            return True

        def refresh(self) -> bool:
            refreshed.append(self.platform)
            return True

    monkeypatch.setattr(sched, "x_auth_manager", lambda: FakeManager("x"))
    monkeypatch.setattr(sched, "reddit_auth_manager", lambda: FakeManager("reddit"))

    sched._run_social_auth_refresh()

    # Reason: reddit is disabled, so only x should be refreshed.
    assert refreshed == ["x"]


def test_social_auth_refresh_skips_unauthenticated_platforms(monkeypatch, tmp_path):
    """Platforms without a prior login should be skipped to avoid timeouts."""
    s = Settings(
        db_path=str(tmp_path / "test.sqlite"),
        output_root=str(tmp_path / "outputs"),
        media_root=str(tmp_path / "media"),
        social_x_enabled=True,
        social_reddit_enabled=True,
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    monkeypatch.setattr(sched, "settings", s)

    refreshed: list[str] = []

    class FakeManager:
        def __init__(self, platform: str, authenticated: bool):
            self.platform = platform
            self._authed = authenticated

        def is_authenticated(self) -> bool:
            return self._authed

        def refresh(self) -> bool:
            refreshed.append(self.platform)
            return True

    # Reason: x is authenticated, reddit is not — only x should be refreshed.
    monkeypatch.setattr(sched, "x_auth_manager", lambda: FakeManager("x", True))
    monkeypatch.setattr(sched, "reddit_auth_manager", lambda: FakeManager("reddit", False))

    sched._run_social_auth_refresh()

    assert refreshed == ["x"]
