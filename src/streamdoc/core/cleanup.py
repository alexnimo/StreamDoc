"""Retention cleanup — delete old media and reports after configured thresholds.

Two tiers:
- Media: videos, audio (.wav), extracted frames — deleted after retention_media_hours
- Reports: .md, .pdf, transcripts — deleted after retention_reports_hours

Per-preset overrides:
- Preset.file_retention_hours overrides the global retention_reports_hours for
  report files stored under output_root/<preset.name>/.
- Preset.notebook_retention_hours overrides the global
  notebooklm_default_retention_hours for NotebookLM notebooks created by that
  preset (enforced by the NotebookLM RetentionManager).

Cleanup runs automatically after each preset run and can be triggered manually.
`retention_dry_run`: log what would be deleted without actually deleting.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamdoc.config import settings
from streamdoc.db import session_scope
from streamdoc.models.video import Video

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        v = value
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v)
    except Exception:
        return None


def _is_older_than_hours(value: str | None, hours: float) -> bool:
    """Return True if the timestamp is older than N hours from now."""
    dt = _parse_dt(value)
    if not dt:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Reason: naive datetimes compare against UTC cutoff; this is safe because
    # processed_at is always stored as UTC ISO string
    try:
        return dt < cutoff
    except TypeError:
        # If dt is naive, assume UTC
        return dt.replace(tzinfo=timezone.utc) < cutoff


def _file_is_older_than_hours(path: Path, hours: float) -> bool:
    """Return True if the file's mtime is older than N hours from now.

    Args:
        path: File to check.
        hours: Retention threshold in hours.

    Returns:
        True if the file should be deleted based on age.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime < cutoff


def _load_preset_file_retention() -> dict[str, float]:
    """Load per-preset file retention overrides from the database.

    Returns:
        Dict mapping preset name -> file_retention_hours. Presets with
        retention_enabled=False are mapped to 0.0 (disabled — keep forever).
        Presets with file_retention_hours=None fall back to the global
        default and are NOT included in the returned dict.
    """
    overrides: dict[str, float] = {}
    try:
        from streamdoc.models.preset import Preset
        with session_scope() as s:
            rows = s.query(Preset).all()
            for p in rows:
                # Reason: when retention is disabled for this preset, map it
                # to 0.0 so cleanup skips its files entirely.
                if not getattr(p, "retention_enabled", True):
                    overrides[p.name] = 0.0
                    continue
                val = getattr(p, "file_retention_hours", None)
                if val is not None:
                    overrides[p.name] = float(val)
    except Exception as exc:
        logger.debug("Failed to load preset retention overrides: %s", exc)
    return overrides


def _resolve_file_retention_hours(preset_name: str, overrides: dict[str, float]) -> float:
    """Resolve the effective file retention for a preset directory.

    Args:
        preset_name: Preset display name (matches output_root subdir).
        overrides: Dict from _load_preset_file_retention().

    Returns:
        Retention in hours — preset override or global default.
    """
    if preset_name in overrides:
        return overrides[preset_name]
    return settings.retention_reports_hours


# ---------------------------------------------------------------------------
# Media cleanup (global — not per-preset)
# ---------------------------------------------------------------------------

def cleanup_media(dry_run: bool | None = None) -> dict[str, int]:
    """Delete media files for videos processed longer than retention_media_hours ago.

    Args:
        dry_run: If True, only log what would be deleted. Defaults to settings.retention_dry_run.

    Returns:
        Dict with counts: {"videos_deleted": int, "audio_deleted": int, "frames_deleted": int}
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    hours = settings.retention_media_hours
    if hours <= 0:
        logger.info("Media retention is disabled (retention_media_hours=%s)", hours)
        return {"videos_deleted": 0, "audio_deleted": 0, "frames_deleted": 0}

    deleted = {"videos_deleted": 0, "audio_deleted": 0, "frames_deleted": 0}
    media_root = Path(settings.media_root)

    with session_scope() as session:
        # Reason: include videos with any output_status (ready, failed,
        # missing) so that media from hung/failed jobs is also cleaned up,
        # not just successfully processed videos. Without this, media files
        # from jobs that hung (e.g., Whisper timeout) would never be deleted.
        videos = session.query(Video).all()
        for v in videos:
            if not _is_older_than_hours(v.processed_at, hours):
                continue

            # Delete video file(s) in media_root/channel_id/video_id/
            video_dir = media_root / v.channel_id / v.id
            if video_dir.exists():
                for f in video_dir.iterdir():
                    if f.is_file():
                        if dry_run:
                            logger.info("[DRY-RUN] Would delete media file: %s", f)
                        else:
                            try:
                                f.unlink()
                                deleted["videos_deleted"] += 1
                            except OSError as exc:
                                logger.warning("Failed to delete %s: %s", f, exc)
                    elif f.is_dir() and f.name == "frames":
                        frame_count = sum(1 for _ in f.rglob("*") if _.is_file())
                        if dry_run:
                            logger.info("[DRY-RUN] Would delete frames dir: %s", f)
                        else:
                            try:
                                shutil.rmtree(f)
                                deleted["frames_deleted"] += frame_count
                            except OSError as exc:
                                logger.warning("Failed to delete frames dir %s: %s", f, exc)
                # Remove empty video dir
                if not dry_run and video_dir.exists():
                    try:
                        video_dir.rmdir()
                    except OSError:
                        pass

            # Update media_status so we know it's been cleaned
            if not dry_run:
                v.media_status = "cleaned"

    # Reason: also clean up orphaned media directories — files on disk
    # that have no corresponding Video record in the DB. This happens when
    # the DB is reset, video records are deleted, or a download completed
    # but the Video record was never committed (e.g., process killed mid-run).
    # We scan the media root and delete any video directory whose mtime is
    # older than the retention threshold and whose ID doesn't match any
    # Video record.
    known_video_ids: set[str] = set()
    with session_scope() as session:
        for v in session.query(Video).all():
            known_video_ids.add(v.id)

    if media_root.exists():
        for channel_dir in media_root.iterdir():
            if not channel_dir.is_dir():
                continue
            for video_dir in channel_dir.iterdir():
                if not video_dir.is_dir():
                    continue
                if video_dir.name in known_video_ids:
                    continue
                # Reason: only delete orphaned dirs that are older than the
                # retention threshold (by directory mtime).
                try:
                    if not _file_is_older_than_hours(video_dir, hours):
                        continue
                except OSError:
                    continue
                if dry_run:
                    logger.info("[DRY-RUN] Would delete orphaned media dir: %s", video_dir)
                else:
                    try:
                        shutil.rmtree(video_dir)
                        deleted["videos_deleted"] += 1
                        logger.info("Deleted orphaned media dir: %s", video_dir)
                    except OSError as exc:
                        logger.warning("Failed to delete orphaned dir %s: %s", video_dir, exc)

    logger.info(
        "Media cleanup complete (dry_run=%s): %s", dry_run, deleted
    )
    return deleted


# ---------------------------------------------------------------------------
# Report cleanup (per-preset)
# ---------------------------------------------------------------------------

def cleanup_reports(dry_run: bool | None = None) -> dict[str, int]:
    """Delete report files older than the per-preset file retention threshold.

    Report files (.md, .pdf) are stored under output_root/<preset.name>/.
    Each preset's file_retention_hours overrides the global
    retention_reports_hours. Files are aged by mtime.

    Args:
        dry_run: If True, only log what would be deleted.

    Returns:
        Dict with counts: {"reports_deleted": int}
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    global_hours = settings.retention_reports_hours
    if global_hours <= 0:
        logger.info("Report retention is disabled (retention_reports_hours=%s)", global_hours)
        return {"reports_deleted": 0}

    overrides = _load_preset_file_retention()
    deleted_count = 0
    output_root = Path(settings.output_root)

    if not output_root.exists():
        return {"reports_deleted": 0}

    for preset_dir in output_root.iterdir():
        if not preset_dir.is_dir():
            continue
        hours = _resolve_file_retention_hours(preset_dir.name, overrides)
        if hours <= 0:
            logger.info(
                "Skipping preset dir %s — file retention disabled (hours=%s)",
                preset_dir.name, hours,
            )
            continue
        for f in preset_dir.iterdir():
            if not f.is_file():
                continue
            # Reason: FULL_REPORT files are handled by cleanup_full_reports.
            if f.name.startswith("FULL_REPORT"):
                continue
            try:
                if not _file_is_older_than_hours(f, hours):
                    continue
            except OSError as exc:
                logger.warning("Failed to stat %s: %s", f, exc)
                continue
            if dry_run:
                logger.info("[DRY-RUN] Would delete report: %s", f)
            else:
                try:
                    f.unlink()
                    deleted_count += 1
                except OSError as exc:
                    logger.warning("Failed to delete %s: %s", f, exc)

    logger.info("Report cleanup complete (dry_run=%s): %s deleted", dry_run, deleted_count)
    return {"reports_deleted": deleted_count}


def cleanup_full_reports(dry_run: bool | None = None) -> dict[str, int]:
    """Delete FULL_REPORT files older than the per-preset file retention threshold.

    Uses file mtime as the age signal since these are not tied to a single video.

    Returns:
        Dict with counts: {"reports_deleted": int}
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    global_hours = settings.retention_reports_hours
    if global_hours <= 0:
        return {"reports_deleted": 0}

    overrides = _load_preset_file_retention()
    deleted_count = 0
    output_root = Path(settings.output_root)

    if output_root.exists():
        for preset_dir in output_root.iterdir():
            if not preset_dir.is_dir():
                continue
            hours = _resolve_file_retention_hours(preset_dir.name, overrides)
            if hours <= 0:
                continue
            for f in preset_dir.iterdir():
                if f.is_file() and f.name.startswith("FULL_REPORT"):
                    try:
                        if not _file_is_older_than_hours(f, hours):
                            continue
                    except OSError as exc:
                        logger.warning("Failed to stat %s: %s", f, exc)
                        continue
                    if dry_run:
                        logger.info("[DRY-RUN] Would delete full report: %s", f)
                    else:
                        try:
                            f.unlink()
                            deleted_count += 1
                        except OSError as exc:
                            logger.warning("Failed to delete %s: %s", f, exc)

    logger.info("Full-report cleanup complete (dry_run=%s): %s deleted", dry_run, deleted_count)
    return {"reports_deleted": deleted_count}


# ---------------------------------------------------------------------------
# NotebookLM retention cleanup
# ---------------------------------------------------------------------------

def cleanup_notebooklm(dry_run: bool | None = None) -> dict[str, int]:
    """Clean up expired NotebookLM notebooks.

    Each NotebookLMContent record stores its own retention_hours (set from the
    preset's notebook_retention_hours at registration time). This function
    delegates to the RetentionManager which deletes expired notebooks, their
    artifacts, and local downloaded files.

    Args:
        dry_run: If True, only report what would be deleted.

    Returns:
        Dict with counts: {"notebooks_deleted": int, "artifacts_deleted": int,
        "local_files_deleted": int, "errors": int}
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    if not settings.notebooklm_enabled:
        return {
            "notebooks_deleted": 0,
            "artifacts_deleted": 0,
            "local_files_deleted": 0,
            "errors": 0,
        }

    try:
        from streamdoc.async_utils import run_async
        from streamdoc.integrations.notebooklm import (
            NotebookLMClientWrapper,
            NotebookLMAuthManager,
            RetentionManager,
        )
        from streamdoc.integrations.notebooklm.exceptions import (
            NotebookLMAuthRequiredError,
            NotebookLMIntegrationError,
        )
    except ImportError:
        logger.debug("NotebookLM integration not available — skipping cleanup")
        return {
            "notebooks_deleted": 0,
            "artifacts_deleted": 0,
            "local_files_deleted": 0,
            "errors": 0,
        }

    auth = NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile,
    )
    try:
        async def _do_cleanup() -> dict[str, int]:
            async with NotebookLMClientWrapper(auth) as client:
                with session_scope() as s:
                    mgr = RetentionManager(
                        client, s, settings.notebooklm_default_retention_hours,
                    )
                    report = await mgr.cleanup_expired(
                        dry_run=dry_run,
                        delete_remote=True,
                        delete_local=True,
                    )
                    return {
                        "notebooks_deleted": len(report.deleted_notebooks),
                        "artifacts_deleted": len(report.deleted_artifacts),
                        "local_files_deleted": len(report.deleted_local_files),
                        "errors": len(report.errors),
                    }
        return run_async(_do_cleanup())
    except (NotebookLMAuthRequiredError, NotebookLMIntegrationError) as exc:
        logger.warning("NotebookLM cleanup skipped (auth/integration): %s", exc)
        return {
            "notebooks_deleted": 0,
            "artifacts_deleted": 0,
            "local_files_deleted": 0,
            "errors": 0,
        }
    except Exception as exc:
        logger.warning("NotebookLM cleanup failed: %s", exc)
        return {
            "notebooks_deleted": 0,
            "artifacts_deleted": 0,
            "local_files_deleted": 0,
            "errors": 1,
        }


# ---------------------------------------------------------------------------
# Social cleanup
# ---------------------------------------------------------------------------


def cleanup_social(dry_run: bool | None = None) -> dict[str, int]:
    """Clean up expired social posts and their downloaded media files.

    Removes SocialPost records older than ``social_lookback_hours * 2``
    (or configured social retention) and deletes orphaned media directories
    under ``media_root/social/``.

    Args:
        dry_run: If True, only log what would be deleted.

    Returns:
        Dict with counts: {"social_posts_deleted": int, "social_files_deleted": int}
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    if not settings.retention_cleanup_enabled:
        return {"social_posts_deleted": 0, "social_files_deleted": 0}

    from streamdoc.models.social_post import SocialPost as SocialPostModel

    # Determine retention: default to 48h (2 * 24h lookback)
    retention_hours = getattr(settings, "social_retention_hours", None) or 48
    if retention_hours <= 0:
        return {"social_posts_deleted": 0, "social_files_deleted": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    cutoff_iso = cutoff.isoformat()
    deleted_posts = 0
    deleted_files = 0

    with session_scope() as session:
        old_posts = (
            session.query(SocialPostModel)
            .filter(SocialPostModel.processed_at < cutoff_iso)
            .all()
        )
        for post in old_posts:
            if dry_run:
                logger.info("[DRY-RUN] Would delete social post: %s (platform=%s, source_id=%s)", post.id, post.platform, post.source_id)
            else:
                session.delete(post)
                deleted_posts += 1

    # Clean up downloaded social media files
    social_media = Path(settings.media_root) / "social"
    if social_media.exists():
        for platform_dir in social_media.iterdir():
            if not platform_dir.is_dir():
                continue
            for source_dir in platform_dir.iterdir():
                if not source_dir.is_dir():
                    continue
                # Check if source_dir is older than retention by mtime
                try:
                    mtime = datetime.fromtimestamp(source_dir.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if mtime >= cutoff:
                    continue
                if dry_run:
                    logger.info("[DRY-RUN] Would delete social media dir: %s", source_dir)
                else:
                    try:
                        shutil.rmtree(source_dir)
                        deleted_files += 1
                    except OSError as exc:
                        logger.warning("Failed to delete %s: %s", source_dir, exc)

    logger.info("Social cleanup complete (dry_run=%s): %d posts, %d files", dry_run, deleted_posts, deleted_files)
    return {"social_posts_deleted": deleted_posts, "social_files_deleted": deleted_files}


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def run_cleanup(dry_run: bool | None = None) -> dict[str, int]:
    """Run all cleanup tiers and return aggregate counts.

    Args:
        dry_run: Override settings.retention_dry_run for this run.

    Returns:
        Aggregated deletion counts.
    """
    if dry_run is None:
        dry_run = settings.retention_dry_run

    if not settings.retention_cleanup_enabled:
        logger.info("Retention cleanup is disabled")
        return {}

    media = cleanup_media(dry_run=dry_run)
    reports = cleanup_reports(dry_run=dry_run)
    full_reports = cleanup_full_reports(dry_run=dry_run)
    notebooklm = cleanup_notebooklm(dry_run=dry_run)
    social = cleanup_social(dry_run=dry_run)

    total = {
        "videos_deleted": media.get("videos_deleted", 0),
        "audio_deleted": media.get("audio_deleted", 0),
        "frames_deleted": media.get("frames_deleted", 0),
        "reports_deleted": reports.get("reports_deleted", 0) + full_reports.get("reports_deleted", 0),
        "notebooks_deleted": notebooklm.get("notebooks_deleted", 0),
        "notebooklm_artifacts_deleted": notebooklm.get("artifacts_deleted", 0),
        "notebooklm_local_files_deleted": notebooklm.get("local_files_deleted", 0),
        "notebooklm_errors": notebooklm.get("errors", 0),
        "social_posts_deleted": social.get("social_posts_deleted", 0),
        "social_files_deleted": social.get("social_files_deleted", 0),
    }
    logger.info("Cleanup summary (dry_run=%s): %s", dry_run, total)
    return total
