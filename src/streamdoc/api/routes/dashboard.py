"""Dashboard routes — aggregated stats."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import DashboardStats, JobOut, ReportSummary
from streamdoc.config import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats():
    """Get aggregated dashboard statistics."""
    ensure_db()

    from streamdoc.db import session_scope
    from streamdoc.models.preset import Preset
    from streamdoc.models.video import Video
    from streamdoc.models.job import Job
    from streamdoc.core.jobs import list_jobs
    from pathlib import Path

    # Reason: extract all needed attributes from ORM objects while the
    # session is still open. Accessing attributes after session close
    # triggers DetachedInstanceError because SQLAlchemy tries to lazy-load.
    recent_video_data: list[dict] = []
    with session_scope() as s:
        presets = s.query(Preset).all()
        total_presets = len(presets)
        active_presets = sum(1 for p in presets if p.active)

        videos_processed = s.query(Video).filter(
            Video.output_status == "ready"
        ).count()

        # Get recent processed videos for report cards
        recent_videos = s.query(Video).filter(
            Video.output_status == "ready"
        ).order_by(Video.processed_at.desc()).limit(12).all()

        # Reason: copy attributes to plain dicts before session closes
        for v in recent_videos:
            recent_video_data.append({
                "id": v.id,
                "channel_id": v.channel_id,
                "title": v.title,
                "published_at": v.published_at,
                "transcript_word_count": v.transcript_word_count or 0,
                "duration_seconds": v.duration_seconds,
                "processed_at": v.processed_at or "",
            })

    recent_reports: list[ReportSummary] = []
    for vd in recent_video_data:
        # Reason: frames are stored in a "frames" subdirectory
        frame_dir = Path(settings.media_root) / vd["channel_id"] / vd["id"] / "frames"
        if not frame_dir.exists():
            frame_dir = Path(settings.media_root) / vd["channel_id"] / vd["id"]
        frame_count = 0
        has_frames = False
        if frame_dir.exists():
            frames = list(frame_dir.glob("*.jpg")) + list(frame_dir.glob("*.png"))
            frame_count = len(frames)
            has_frames = frame_count > 0

        # Check for report files
        out_root = Path(settings.output_root)
        has_pdf = False
        has_markdown = False
        for subdir in out_root.iterdir() if out_root.exists() else []:
            if (subdir / f"{vd['id']}.pdf").exists():
                has_pdf = True
            if (subdir / f"{vd['id']}.md").exists():
                has_markdown = True

        # Reason: use YouTube's CDN thumbnail directly — always available
        # for public videos, no need to check local frames.
        thumbnail = f"https://img.youtube.com/vi/{vd['id']}/hqdefault.jpg"

        recent_reports.append(ReportSummary(
            video_id=vd["id"],
            title=vd["title"],
            channel_title="",
            preset_name="",
            preset_id="",
            job_id="",
            published_at=vd["published_at"],
            has_pdf=has_pdf,
            has_markdown=has_markdown,
            has_frames=has_frames,
            frame_count=frame_count,
            transcript_word_count=vd["transcript_word_count"],
            duration_seconds=vd["duration_seconds"],
            thumbnail_path=thumbnail,
            created_at=vd["processed_at"],
        ))

    # Jobs
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()
    recent_jobs_raw = list_jobs(limit=10)
    jobs_24h = sum(1 for j in recent_jobs_raw if j.get("created_at", "") >= cutoff)
    jobs_completed = sum(1 for j in recent_jobs_raw if j.get("status") == "completed")
    jobs_failed = sum(1 for j in recent_jobs_raw if j.get("status") == "failed")

    recent_jobs = [JobOut(**j) for j in recent_jobs_raw]

    # NotebookLM notebooks count
    notebooklm_count = 0
    if settings.notebooklm_enabled:
        try:
            from streamdoc.integrations.notebooklm.retention import NotebookLMContent
            with session_scope() as s:
                notebooklm_count = s.query(NotebookLMContent).count()
        except Exception:
            pass

    return DashboardStats(
        total_presets=total_presets,
        active_presets=active_presets,
        jobs_24h=jobs_24h,
        jobs_completed=jobs_completed,
        jobs_failed=jobs_failed,
        videos_processed=videos_processed,
        notebooklm_notebooks=notebooklm_count,
        notebooklm_enabled=settings.notebooklm_enabled,
        recent_jobs=recent_jobs,
        recent_reports=recent_reports,
    )
