"""Tests for retention cleanup module."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from streamdoc.config import Settings
from streamdoc.core.cleanup import (
    _is_older_than_hours,
    _parse_dt,
    cleanup_full_reports,
    cleanup_media,
    cleanup_reports,
    run_cleanup,
)
from streamdoc.db import init_db, session_scope
from streamdoc.models.video import Video


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
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
    )
    monkeypatch.setattr("streamdoc.core.cleanup.settings", s)
    monkeypatch.setattr("streamdoc.config.settings", s)
    init_db()
    yield


def _seed_video(video_id: str, channel_id: str = "UCtest", processed_hours_ago: float | None = None) -> Video:
    """Insert a video record with optional processed_at timestamp."""
    now = datetime.now(timezone.utc)
    processed_at = None
    if processed_hours_ago is not None:
        processed_at = (now - timedelta(hours=processed_hours_ago)).isoformat()
    v = Video(
        id=video_id,
        channel_id=channel_id,
        title="Test",
        published_at=now.isoformat(),
        output_status="ready",
        processed_at=processed_at,
    )
    with session_scope() as session:
        session.add(v)
    return v


def test_parse_dt():
    assert _parse_dt("2024-01-01T00:00:00+00:00") is not None
    assert _parse_dt("2024-01-01T00:00:00Z") is not None
    assert _parse_dt(None) is None
    assert _parse_dt("") is None


def test_is_older_than_hours():
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert _is_older_than_hours(old, 24.0) is True
    assert _is_older_than_hours(recent, 24.0) is False


def test_cleanup_media_deletes_old_files(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid001", processed_hours_ago=25)
    video_dir = Path(settings.media_root) / "UCtest" / "vid001"
    video_dir.mkdir(parents=True)
    video_file = video_dir / "video.mp4"
    video_file.write_text("fake video")
    frames_dir = video_dir / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame1.jpg").write_text("fake frame")

    result = cleanup_media()
    assert result["videos_deleted"] == 1
    assert result["frames_deleted"] == 1
    assert not video_file.exists()


def test_cleanup_media_skips_recent_files(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid002", processed_hours_ago=1)
    video_dir = Path(settings.media_root) / "UCtest" / "vid002"
    video_dir.mkdir(parents=True)
    video_file = video_dir / "video.mp4"
    video_file.write_text("fake video")

    result = cleanup_media()
    assert result["videos_deleted"] == 0
    assert video_file.exists()


def test_cleanup_media_dry_run(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid003", processed_hours_ago=25)
    video_dir = Path(settings.media_root) / "UCtest" / "vid003"
    video_dir.mkdir(parents=True)
    video_file = video_dir / "video.mp4"
    video_file.write_text("fake video")

    result = cleanup_media(dry_run=True)
    assert result["videos_deleted"] == 0
    assert video_file.exists()  # not actually deleted


def test_cleanup_reports_deletes_old_reports(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid004", processed_hours_ago=49)
    out_dir = Path(settings.output_root) / "preset1"
    out_dir.mkdir(parents=True)
    report = out_dir / "vid004.md"
    report.write_text("# Report")
    # Reason: cleanup_reports now uses file mtime (not Video.processed_at) so
    # per-preset retention can be applied. Set the file's mtime to be old.
    import os
    old_mtime = (datetime.now(timezone.utc) - timedelta(hours=50)).timestamp()
    os.utime(report, (old_mtime, old_mtime))

    result = cleanup_reports()
    assert result["reports_deleted"] == 1
    assert not report.exists()


def test_cleanup_reports_skips_recent(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid005", processed_hours_ago=1)
    out_dir = Path(settings.output_root) / "preset1"
    out_dir.mkdir(parents=True)
    report = out_dir / "vid005.md"
    report.write_text("# Report")

    result = cleanup_reports()
    assert result["reports_deleted"] == 0
    assert report.exists()


def test_cleanup_full_reports_deletes_old_full_reports(tmp_path, monkeypatch):
    from streamdoc.config import settings
    out_dir = Path(settings.output_root) / "preset1"
    out_dir.mkdir(parents=True)
    full_report = out_dir / "FULL_REPORT.md"
    full_report.write_text("# Full Report")
    # Set mtime to older than 48h
    old_mtime = (datetime.now(timezone.utc) - timedelta(hours=50)).timestamp()
    full_report.touch()
    import os
    os.utime(full_report, (old_mtime, old_mtime))

    result = cleanup_full_reports()
    assert result["reports_deleted"] == 1
    assert not full_report.exists()


def test_run_cleanup_aggregates_counts(tmp_path, monkeypatch):
    from streamdoc.config import settings
    v = _seed_video("vid006", processed_hours_ago=25)
    video_dir = Path(settings.media_root) / "UCtest" / "vid006"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp4").write_text("v")

    out_dir = Path(settings.output_root) / "preset1"
    out_dir.mkdir(parents=True)
    (out_dir / "vid006.md").write_text("r")

    total = run_cleanup()
    assert total["videos_deleted"] == 1
    # Report is only 25h old, below 48h threshold, so not deleted
    assert total["reports_deleted"] == 0
    assert total["social_posts_deleted"] == 0


def test_cleanup_media_deletes_failed_video_files(tmp_path, monkeypatch):
    """Media from failed/hung videos should also be cleaned up, not just 'ready'."""
    from streamdoc.config import settings
    # Reason: seed a video with output_status="failed" (e.g., from a
    # Whisper timeout) and verify its media is still cleaned up.
    now = datetime.now(timezone.utc)
    v = Video(
        id="vid_failed",
        channel_id="UCtest",
        title="Failed Video",
        published_at=now.isoformat(),
        output_status="failed",
        processed_at=(now - timedelta(hours=25)).isoformat(),
    )
    with session_scope() as session:
        session.add(v)

    video_dir = Path(settings.media_root) / "UCtest" / "vid_failed"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp4").write_text("fake failed video")

    result = cleanup_media()
    assert result["videos_deleted"] == 1
    assert not (video_dir / "video.mp4").exists()


def test_cleanup_media_deletes_orphaned_dirs(tmp_path, monkeypatch):
    """Orphaned media dirs (no DB record) should be cleaned up by mtime."""
    from streamdoc.config import settings
    import os

    # Reason: create a media directory with no corresponding Video record.
    orphan_dir = Path(settings.media_root) / "UCorphan" / "vid_orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "video.mp4").write_text("orphan video")

    # Set mtime to 25h ago (older than the 24h retention threshold).
    old_mtime = (datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()
    os.utime(orphan_dir, (old_mtime, old_mtime))

    result = cleanup_media()
    # Reason: orphaned dir should be deleted.
    assert result["videos_deleted"] >= 1
    assert not orphan_dir.exists()


def test_cleanup_media_skips_recent_orphaned_dirs(tmp_path, monkeypatch):
    """Recent orphaned media dirs should NOT be deleted (within retention window)."""
    from streamdoc.config import settings

    orphan_dir = Path(settings.media_root) / "UCorphan" / "vid_recent_orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "video.mp4").write_text("recent orphan")

    # Don't set old mtime — the dir is brand new (within 24h threshold).
    result = cleanup_media()
    # Reason: recent orphan should NOT be deleted.
    assert orphan_dir.exists()
