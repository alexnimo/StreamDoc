"""Tests for per-preset file and notebook retention.

Verifies that:
- Preset model stores file_retention_hours and notebook_retention_hours
- Preset loading (YAML/JSON) coerces retention values correctly
- cleanup_reports uses per-preset file_retention_hours (not just global)
- cleanup_full_reports uses per-preset file_retention_hours
- run_cleanup aggregates notebooklm cleanup counts
- NotebookLM RetentionManager registers with per-preset retention hours
- upload_to_notebooklm passes retention_hours through to RetentionManager
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamdoc.config import Settings
from streamdoc.core.cleanup import (
    _file_is_older_than_hours,
    _load_preset_file_retention,
    _resolve_file_retention_hours,
    cleanup_full_reports,
    cleanup_reports,
    run_cleanup,
)
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.presets import _coerce_float, _coerce_preset, upsert_preset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Isolate DB, media, and output dirs per test."""
    db_path = tmp_path / "test.sqlite"
    media_root = tmp_path / "media"
    output_root = tmp_path / "outputs"
    s = Settings(
        db_path=str(db_path),
        media_root=str(media_root),
        output_root=str(output_root),
        retention_media_hours=24.0,
        retention_reports_hours=48.0,
        retention_cleanup_enabled=True,
        retention_dry_run=False,
        notebooklm_enabled=False,  # Reason: disable so cleanup_notebooklm is a no-op
    )
    monkeypatch.setattr("streamdoc.core.cleanup.settings", s)
    monkeypatch.setattr("streamdoc.config.settings", s)
    init_db()
    yield


def _seed_preset(
    name: str,
    file_retention_hours: float | None = 24.0,
    notebook_retention_hours: float | None = 24.0,
    retention_enabled: bool = True,
) -> Preset:
    """Insert a preset with retention overrides."""
    p = Preset(
        id=name,
        name=name,
        channel_list_id="UCtest",
        prompt_md="",
        outputs="pdf,markdown",
        retention_enabled=retention_enabled,
        file_retention_hours=file_retention_hours,
        notebook_retention_hours=notebook_retention_hours,
    )
    with session_scope() as s:
        s.add(p)
    return p


def _set_file_mtime_hours_ago(path: Path, hours: float) -> None:
    """Set a file's mtime to N hours ago."""
    old_mtime = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    path.touch()
    os.utime(path, (old_mtime, old_mtime))


# ---------------------------------------------------------------------------
# Preset model & loader
# ---------------------------------------------------------------------------

def test_preset_model_has_retention_columns():
    """Preset model should have file_retention_hours and notebook_retention_hours."""
    p = Preset(id="test", name="test", file_retention_hours=12.0, notebook_retention_hours=48.0)
    assert p.file_retention_hours == 12.0
    assert p.notebook_retention_hours == 48.0


def test_preset_model_has_retention_enabled():
    """Preset model should have retention_enabled field."""
    p = Preset(id="test", name="test", retention_enabled=False)
    assert p.retention_enabled is False


def test_preset_model_defaults_retention_enabled_true():
    """Preset model should default retention_enabled to True."""
    with session_scope() as s:
        p = Preset(id="test-ret", name="test-ret")
        s.add(p)
        s.flush()
        assert p.retention_enabled is True


def test_preset_model_defaults_to_24h():
    """Preset model should default to 24h retention after DB flush."""
    with session_scope() as s:
        p = Preset(id="test", name="test")
        s.add(p)
        s.flush()
        assert p.file_retention_hours == 24.0
        assert p.notebook_retention_hours == 24.0


def test_coerce_float_valid():
    assert _coerce_float(12, 24.0) == 12.0
    assert _coerce_float("48", 24.0) == 48.0
    assert _coerce_float(3.5, 24.0) == 3.5


def test_coerce_float_none_returns_default():
    assert _coerce_float(None, 24.0) == 24.0


def test_coerce_float_invalid_returns_default():
    assert _coerce_float("abc", 24.0) == 24.0


def test_coerce_preset_includes_retention():
    """_coerce_preset should map retention fields from payload."""
    p = _coerce_preset({
        "name": "my-preset",
        "file_retention_hours": 72,
        "notebook_retention_hours": 12.5,
    })
    assert p.file_retention_hours == 72.0
    assert p.notebook_retention_hours == 12.5


def test_coerce_preset_includes_retention_enabled():
    """_coerce_preset should map retention_enabled from payload."""
    p = _coerce_preset({
        "name": "my-preset",
        "retention_enabled": False,
    })
    assert p.retention_enabled is False


def test_coerce_preset_defaults_retention_enabled_true():
    """_coerce_preset should default retention_enabled to True."""
    p = _coerce_preset({"name": "my-preset"})
    assert p.retention_enabled is True


def test_coerce_preset_defaults_retention():
    """_coerce_preset should default retention to 24h when not in payload."""
    p = _coerce_preset({"name": "my-preset"})
    assert p.file_retention_hours == 24.0
    assert p.notebook_retention_hours == 24.0


def test_upsert_preset_persists_retention():
    """upsert_preset should save retention fields to DB."""
    p = upsert_preset({
        "name": "retention-test",
        "file_retention_hours": 72,
        "notebook_retention_hours": 36,
    })
    assert p.file_retention_hours == 72.0
    assert p.notebook_retention_hours == 36.0

    with session_scope() as s:
        loaded = s.get(Preset, "retention-test")
        assert loaded is not None
        assert loaded.file_retention_hours == 72.0
        assert loaded.notebook_retention_hours == 36.0


def test_upsert_preset_updates_retention():
    """upsert_preset should update retention on existing presets."""
    upsert_preset({"name": "update-test", "file_retention_hours": 12})
    p = upsert_preset({"name": "update-test", "file_retention_hours": 72, "notebook_retention_hours": 48})
    assert p.file_retention_hours == 72.0
    assert p.notebook_retention_hours == 48.0


def test_upsert_preset_persists_retention_enabled():
    """upsert_preset should save retention_enabled to DB."""
    p = upsert_preset({"name": "enabled-test", "retention_enabled": False})
    assert p.retention_enabled is False
    with session_scope() as s:
        loaded = s.get(Preset, "enabled-test")
        assert loaded.retention_enabled is False


def test_upsert_preset_updates_retention_enabled():
    """upsert_preset should update retention_enabled on existing presets."""
    upsert_preset({"name": "toggle-test", "retention_enabled": True})
    p = upsert_preset({"name": "toggle-test", "retention_enabled": False})
    assert p.retention_enabled is False


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

def test_file_is_older_than_hours_old_file(tmp_path):
    f = tmp_path / "old.txt"
    f.write_text("test")
    _set_file_mtime_hours_ago(f, 25)
    assert _file_is_older_than_hours(f, 24.0) is True


def test_file_is_older_than_hours_recent_file(tmp_path):
    f = tmp_path / "recent.txt"
    f.write_text("test")
    _set_file_mtime_hours_ago(f, 1)
    assert _file_is_older_than_hours(f, 24.0) is False


def test_load_preset_file_retention_returns_overrides():
    """_load_preset_file_retention should return dict of preset name -> hours."""
    _seed_preset("alpha", file_retention_hours=12.0)
    _seed_preset("beta", file_retention_hours=72.0)
    overrides = _load_preset_file_retention()
    assert overrides.get("alpha") == 12.0
    assert overrides.get("beta") == 72.0


def test_resolve_file_retention_uses_override():
    overrides = {"my-preset": 12.0}
    assert _resolve_file_retention_hours("my-preset", overrides) == 12.0


def test_resolve_file_retention_falls_back_to_global():
    from streamdoc.config import settings
    overrides = {}
    assert _resolve_file_retention_hours("unknown-preset", overrides) == settings.retention_reports_hours


# ---------------------------------------------------------------------------
# Per-preset report cleanup
# ---------------------------------------------------------------------------

def test_cleanup_reports_uses_per_preset_retention():
    """Reports under a preset dir should be deleted based on that preset's retention."""
    from streamdoc.config import settings
    _seed_preset("short-retention", file_retention_hours=12.0)
    _seed_preset("long-retention", file_retention_hours=200.0)

    out_root = Path(settings.output_root)
    short_dir = out_root / "short-retention"
    long_dir = out_root / "long-retention"
    short_dir.mkdir(parents=True)
    long_dir.mkdir(parents=True)

    # File 15h old — exceeds short-retention (12h) but not long-retention (200h)
    short_file = short_dir / "vid1.md"
    short_file.write_text("# Report")
    _set_file_mtime_hours_ago(short_file, 15)

    long_file = long_dir / "vid2.md"
    long_file.write_text("# Report")
    _set_file_mtime_hours_ago(long_file, 15)

    result = cleanup_reports()
    assert result["reports_deleted"] == 1
    assert not short_file.exists()
    assert long_file.exists()  # Not old enough for 200h retention


def test_cleanup_reports_falls_back_to_global_for_unknown_preset():
    """Reports under a dir with no matching preset should use global retention."""
    from streamdoc.config import settings
    out_root = Path(settings.output_root)
    unknown_dir = out_root / "unknown-preset"
    unknown_dir.mkdir(parents=True)

    # Global retention is 48h — file 50h old should be deleted
    old_file = unknown_dir / "vid_old.md"
    old_file.write_text("# Report")
    _set_file_mtime_hours_ago(old_file, 50)

    # File 25h old — under 48h global, should be kept
    new_file = unknown_dir / "vid_new.md"
    new_file.write_text("# Report")
    _set_file_mtime_hours_ago(new_file, 25)

    result = cleanup_reports()
    assert result["reports_deleted"] == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_reports_dry_run_does_not_delete():
    from streamdoc.config import settings
    _seed_preset("dry-run-test", file_retention_hours=1.0)
    out_root = Path(settings.output_root)
    d = out_root / "dry-run-test"
    d.mkdir(parents=True)
    f = d / "vid.md"
    f.write_text("# Report")
    _set_file_mtime_hours_ago(f, 5)

    result = cleanup_reports(dry_run=True)
    assert result["reports_deleted"] == 0
    assert f.exists()


def test_cleanup_reports_skips_full_report_files():
    """FULL_REPORT files should be skipped by cleanup_reports."""
    from streamdoc.config import settings
    _seed_preset("full-test", file_retention_hours=1.0)
    out_root = Path(settings.output_root)
    d = out_root / "full-test"
    d.mkdir(parents=True)
    full = d / "FULL_REPORT.md"
    full.write_text("# Full")
    _set_file_mtime_hours_ago(full, 100)

    result = cleanup_reports()
    assert result["reports_deleted"] == 0
    assert full.exists()  # Handled by cleanup_full_reports, not cleanup_reports


def test_cleanup_full_reports_uses_per_preset_retention():
    """FULL_REPORT files should use per-preset retention."""
    from streamdoc.config import settings
    _seed_preset("full-preset", file_retention_hours=12.0)
    out_root = Path(settings.output_root)
    d = out_root / "full-preset"
    d.mkdir(parents=True)
    full = d / "FULL_REPORT.md"
    full.write_text("# Full")
    _set_file_mtime_hours_ago(full, 15)

    result = cleanup_full_reports()
    assert result["reports_deleted"] == 1
    assert not full.exists()


def test_cleanup_reports_disabled_retention_keeps_files():
    """When file_retention_hours is 0, files should be kept (retention disabled)."""
    from streamdoc.config import settings
    _seed_preset("disabled-retention", file_retention_hours=0.0)
    out_root = Path(settings.output_root)
    d = out_root / "disabled-retention"
    d.mkdir(parents=True)
    f = d / "vid.md"
    f.write_text("# Report")
    _set_file_mtime_hours_ago(f, 1000)

    result = cleanup_reports()
    assert result["reports_deleted"] == 0
    assert f.exists()


def test_cleanup_reports_retention_enabled_false_keeps_files():
    """When retention_enabled is False, files should be kept indefinitely."""
    from streamdoc.config import settings
    _seed_preset("retention-off", file_retention_hours=12.0, retention_enabled=False)
    out_root = Path(settings.output_root)
    d = out_root / "retention-off"
    d.mkdir(parents=True)
    f = d / "vid.md"
    f.write_text("# Report")
    _set_file_mtime_hours_ago(f, 1000)

    result = cleanup_reports()
    assert result["reports_deleted"] == 0
    assert f.exists()


def test_cleanup_full_reports_retention_enabled_false_keeps_files():
    """When retention_enabled is False, FULL_REPORT files should be kept."""
    from streamdoc.config import settings
    _seed_preset("full-retention-off", file_retention_hours=12.0, retention_enabled=False)
    out_root = Path(settings.output_root)
    d = out_root / "full-retention-off"
    d.mkdir(parents=True)
    f = d / "FULL_REPORT.md"
    f.write_text("# Full Report")
    _set_file_mtime_hours_ago(f, 1000)

    result = cleanup_full_reports()
    assert result["reports_deleted"] == 0
    assert f.exists()


def test_load_preset_file_retention_maps_disabled_to_zero():
    """_load_preset_file_retention should map retention_enabled=False to 0.0."""
    _seed_preset("enabled-preset", file_retention_hours=12.0, retention_enabled=True)
    _seed_preset("disabled-preset", file_retention_hours=12.0, retention_enabled=False)
    overrides = _load_preset_file_retention()
    assert overrides.get("enabled-preset") == 12.0
    assert overrides.get("disabled-preset") == 0.0


def test_run_cleanup_includes_notebooklm_counts():
    """run_cleanup should include notebooklm cleanup counts in the aggregate."""
    from streamdoc.config import settings
    # Reason: notebooklm_enabled=False in fixture, so cleanup_notebooklm returns zeros
    total = run_cleanup()
    assert "notebooks_deleted" in total
    assert "notebooklm_artifacts_deleted" in total
    assert "notebooklm_local_files_deleted" in total
    assert "notebooklm_errors" in total


# ---------------------------------------------------------------------------
# NotebookLM retention integration
# ---------------------------------------------------------------------------

def test_retention_manager_registers_with_preset_hours():
    """RetentionManager.register_notebook should store the given retention_hours."""
    from streamdoc.integrations.notebooklm.retention import (
        NotebookLMContent,
        RetentionManager,
    )

    with session_scope() as s:
        mgr = RetentionManager(MagicMock(), s, default_retention_hours=24.0)
        content = mgr.register_notebook(
            notebook_id="nb-123",
            title="Test",
            preset_name="my-preset",
            retention_hours=72.0,
        )
        assert content.retention_hours == 72.0
        assert content.expires_at is not None
        # expires_at should be ~72h from now
        delta = content.expires_at - datetime.utcnow()
        assert 71 < delta.total_seconds() / 3600 < 73


def test_retention_manager_default_hours_when_none():
    """RetentionManager should use default_retention_hours when retention_hours is None."""
    from streamdoc.integrations.notebooklm.retention import RetentionManager

    with session_scope() as s:
        mgr = RetentionManager(MagicMock(), s, default_retention_hours=48.0)
        content = mgr.register_notebook(
            notebook_id="nb-default",
            title="Default Test",
            preset_name="my-preset",
            retention_hours=None,
        )
        assert content.retention_hours == 48.0


def test_retention_manager_permanent_notebook_no_expiry():
    """Permanent notebooks should have expires_at=None."""
    from streamdoc.integrations.notebooklm.retention import RetentionManager

    with session_scope() as s:
        mgr = RetentionManager(MagicMock(), s, default_retention_hours=24.0)
        content = mgr.register_notebook(
            notebook_id="nb-perm",
            title="Permanent",
            preset_name="my-preset",
            is_permanent=True,
            retention_hours=24.0,
        )
        assert content.is_permanent is True
        assert content.expires_at is None
        assert content.is_expired() is False


def test_retention_manager_expired_content_detected():
    """Content past its expires_at should be flagged as expired."""
    from streamdoc.integrations.notebooklm.retention import (
        NotebookLMContent,
        RetentionManager,
    )
    from datetime import timedelta

    with session_scope() as s:
        mgr = RetentionManager(MagicMock(), s, default_retention_hours=24.0)
        content = mgr.register_notebook(
            notebook_id="nb-expired",
            title="Expired",
            preset_name="my-preset",
            retention_hours=1.0,
        )
        # Force expiry
        content.expires_at = datetime.utcnow() - timedelta(hours=1)
        s.flush()
        expired = mgr.get_expired_content()
        ids = [c.notebook_id for c in expired]
        assert "nb-expired" in ids


def test_cleanup_expired_deletes_local_files_and_updates_db():
    """cleanup_expired should delete local files and mark content as deleted."""
    from streamdoc.integrations.notebooklm.retention import RetentionManager

    # Create a temp file to simulate a downloaded artifact
    tmp_file = pytest.tmp_path / "artifact.pptx" if hasattr(pytest, 'tmp_path') else None
    # Reason: use the fixture-provided tmp_path via the test function param
    # Actually, tmp_path is a fixture — we need it as a param. Let's use a different approach.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tf:
        local_path = Path(tf.name)
    local_path.write_bytes(b"fake artifact")

    try:
        with session_scope() as s:
            mgr = RetentionManager(MagicMock(), s, default_retention_hours=24.0)
            content = mgr.register_notebook(
                notebook_id="nb-cleanup",
                title="Cleanup Test",
                preset_name="my-preset",
                retention_hours=1.0,
            )
            mgr.register_artifact(
                content_id=content.id,
                artifact_type="slide_deck",
                artifact_id="art-1",
                local_path=local_path,
            )
            # Force expiry
            content.expires_at = datetime.utcnow() - timedelta(hours=1)
            s.flush()
            content_id = content.id

        # Run cleanup — mock the client so remote deletion is a no-op
        with session_scope() as s:
            mock_client = MagicMock()
            mock_client.artifacts = MagicMock()
            mock_client.artifacts.delete = AsyncMock()
            mock_client.notebooks = MagicMock()
            mock_client.notebooks.delete = AsyncMock()

            mgr = RetentionManager(mock_client, s, default_retention_hours=24.0)
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                report = loop.run_until_complete(
                    mgr.cleanup_expired(dry_run=False, delete_remote=True, delete_local=True)
                )
            finally:
                loop.close()

        assert len(report.deleted_local_files) == 1
        assert not local_path.exists()  # File should be deleted

        # DB record should be marked as deleted
        with session_scope() as s:
            from streamdoc.integrations.notebooklm.retention import NotebookLMContent
            record = s.query(NotebookLMContent).filter_by(id=content_id).first()
            assert record.status == "deleted"
    finally:
        if local_path.exists():
            local_path.unlink()


# ---------------------------------------------------------------------------
# upload_to_notebooklm retention passthrough
# ---------------------------------------------------------------------------

def test_upload_to_notebooklm_passes_retention_hours_to_manager(monkeypatch):
    """upload_to_notebooklm should pass retention_hours to RetentionManager.register_notebook."""
    import asyncio
    from streamdoc.core.notebooklm_upload import upload_to_notebooklm

    # Reason: the autouse fixture disables notebooklm_enabled, so re-enable
    # it for this test to reach the retention tracking code path.
    from streamdoc.config import settings
    monkeypatch.setattr(settings, "notebooklm_enabled", True)
    monkeypatch.setattr("streamdoc.core.notebooklm_upload.settings", settings)

    # Mock the auth and client
    with patch("streamdoc.core.notebooklm_upload.NotebookLMAuthManager") as MockAuth, \
         patch("streamdoc.core.notebooklm_upload.NotebookLMClientWrapper") as MockClientWrapper, \
         patch("streamdoc.core.notebooklm_upload.NotebookManager") as MockNotebookMgr, \
         patch("streamdoc.core.notebooklm_upload.ContentManager") as MockContentMgr, \
         patch("streamdoc.core.notebooklm_upload.PromptManager"), \
         patch("streamdoc.core.notebooklm_upload.RetentionManager") as MockRetention:

        # Setup mocks
        auth_instance = MockAuth.return_value
        auth_instance.require_auth = AsyncMock()
        auth_instance.check_session_freshness = AsyncMock(
            return_value=MagicMock(is_valid=True, message="ok")
        )

        mock_nb = MagicMock()
        mock_nb.id = "test-nb-id"
        mock_nb.title = "Test Notebook"
        mock_notebooks = MockNotebookMgr.return_value
        mock_notebooks.create_notebook = AsyncMock(return_value=mock_nb)
        mock_notebooks.enable_sharing = AsyncMock(return_value="https://example.com")

        mock_source = MagicMock()
        mock_source.id = "src-1"
        mock_source.title = "source"
        mock_content_mgr = MockContentMgr.return_value
        mock_content_mgr.upload_report = AsyncMock(return_value=mock_source)

        mock_batch_result = MagicMock()
        mock_batch_result.results = []
        mock_batch_result.errors = []
        mock_content_mgr.batch_generate = AsyncMock(return_value=mock_batch_result)

        # Mock the async context manager
        mock_client = MockClientWrapper.return_value
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Mock RetentionManager
        mock_retention = MockRetention.return_value
        mock_content_record = MagicMock()
        mock_content_record.id = "content-1"
        mock_retention.register_notebook = MagicMock(return_value=mock_content_record)

        # Create a temp report file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            report_path = Path(tf.name)
        report_path.write_bytes(b"fake report")

        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    upload_to_notebooklm(
                        report_paths=[report_path],
                        preset_name="test-preset",
                        retention_hours=72.0,
                    )
                )
            finally:
                loop.close()

            # Verify RetentionManager was called with 72.0
            MockRetention.assert_called()
            # The register_notebook should have been called with retention_hours=72.0
            mock_retention.register_notebook.assert_called_once()
            call_kwargs = mock_retention.register_notebook.call_args
            assert call_kwargs.kwargs.get("retention_hours") == 72.0 or \
                   call_kwargs[1].get("retention_hours") == 72.0
        finally:
            report_path.unlink(missing_ok=True)
