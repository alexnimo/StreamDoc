"""Reports listing and detail routes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import ReportDetail, ReportSummary
from streamdoc.config import settings
from streamdoc.db import session_scope
from streamdoc.models.video import Video as VideoModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


def _find_report_files(video_id: str, preset_name: str) -> tuple[Path | None, Path | None]:
    """Find markdown and PDF report files for a video.

    Args:
        video_id: YouTube video ID.
        preset_name: Preset name (used as subdirectory). If empty, searches
            all subdirectories of the output root.

    Returns:
        Tuple of (markdown_path, pdf_path), either may be None.
    """
    out_root = Path(settings.output_root)

    # Reason: when preset_name is provided, look only in that subdirectory.
    # When empty (called from list/get/download routes that don't know the
    # preset), search all subdirectories — files are saved as
    # output_root/<preset_name>/<video_id>.md
    search_dirs: list[Path] = []
    if preset_name:
        search_dirs = [out_root / preset_name]
    else:
        # Search root first (legacy), then all subdirectories
        search_dirs = [out_root]
        if out_root.exists():
            search_dirs.extend(sorted(out_root.iterdir()))

    for out_dir in search_dirs:
        if not out_dir.exists() or not out_dir.is_dir():
            continue
        md = out_dir / f"{video_id}.md"
        pdf = out_dir / f"{video_id}.pdf"
        md_found = md if md.exists() else None
        pdf_found = pdf if pdf.exists() else None
        if md_found or pdf_found:
            return (md_found, pdf_found)

    return (None, None)


def _find_thumbnail(video_id: str, channel_id: str) -> str | None:
    """Find a thumbnail image for a video.

    Uses the official YouTube thumbnail URL directly — no download needed.
    YouTube serves thumbnails at predictable URLs for all public videos.
    Falls back to extracted frames if the YouTube thumbnail is unavailable.

    Args:
        video_id: YouTube video ID.
        channel_id: Channel ID for directory path (used for frame fallback).

    Returns:
        Thumbnail URL (YouTube CDN or local frame endpoint) or None.
    """
    # Reason: YouTube thumbnails are always available at predictable URLs
    # for public videos. hqdefault.jpg is always present (even for older
    # videos); maxresdefault.jpg may not exist for all videos.
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


@router.get("", response_model=list[ReportSummary])
def list_reports(preset: str | None = None, limit: int = 50) -> list[ReportSummary]:
    """List processed video reports with metadata."""
    ensure_db()
    reports: list[ReportSummary] = []

    with session_scope() as s:
        query = s.query(VideoModel).filter(VideoModel.output_status == "ready")
        if preset:
            query = query.filter(VideoModel.channel_id == preset)
        rows = query.order_by(VideoModel.processed_at.desc()).limit(limit).all()

        # Reason: build a lookup of video_id → (job_id, preset_id) by
        # querying recent jobs. We store the preset_id (not display name)
        # because the preset name can change — we resolve the current
        # display name from the Preset table at query time.
        video_to_job: dict[str, tuple[str, str]] = {}
        preset_cache: dict[str, str] = {}
        try:
            from streamdoc.models.job import Job as JobModel
            from streamdoc.models.preset import Preset as PresetModel
            import json as _json
            recent_jobs = s.query(JobModel).order_by(
                JobModel.created_at.desc()
            ).limit(50).all()
            for job in recent_jobs:
                try:
                    details = _json.loads(job.details) if job.details else {}
                except Exception:
                    details = {}
                for vid in details.get("videos", []):
                    vid_id = vid.get("video_id", "")
                    if vid_id and vid_id not in video_to_job:
                        video_to_job[vid_id] = (job.id, job.preset_name)
        except Exception:
            pass

        def _resolve_preset_name(preset_id: str) -> str:
            """Look up the current display name for a preset ID.

            Args:
                preset_id: The preset's internal ID.

            Returns:
                The preset's display name, or the ID if not found.
            """
            if not preset_id:
                return ""
            if preset_id in preset_cache:
                return preset_cache[preset_id]
            try:
                p = s.get(PresetModel, preset_id)
                name = p.name if p else preset_id
                preset_cache[preset_id] = name
                return name
            except Exception:
                return preset_id

        for v in rows:
            md_path, pdf_path = _find_report_files(v.id, "")
            if not md_path and not pdf_path:
                continue

            # Reason: frames are stored in a "frames" subdirectory
            frame_dir = Path(settings.media_root) / v.channel_id / v.id / "frames"
            if not frame_dir.exists():
                frame_dir = Path(settings.media_root) / v.channel_id / v.id
            frame_count = 0
            has_frames = False
            if frame_dir.exists():
                frames = list(frame_dir.glob("*.jpg")) + list(frame_dir.glob("*.png"))
                frame_count = len(frames)
                has_frames = frame_count > 0

            job_id, preset_id = video_to_job.get(v.id, ("", ""))
            # Reason: resolve the current preset display name from the
            # Preset table so renaming a preset updates the grouping.
            preset_name = _resolve_preset_name(preset_id)

            reports.append(ReportSummary(
                video_id=v.id,
                title=v.title,
                channel_title="",
                preset_name=preset_name,
                preset_id=preset_id,
                job_id=job_id,
                published_at=v.published_at,
                has_pdf=pdf_path is not None,
                has_markdown=md_path is not None,
                has_frames=has_frames,
                frame_count=frame_count,
                transcript_word_count=v.transcript_word_count or 0,
                duration_seconds=v.duration_seconds,
                thumbnail_path=_find_thumbnail(v.id, v.channel_id),
                report_path=str(pdf_path) if pdf_path else (str(md_path) if md_path else None),
                created_at=v.processed_at or "",
            ))

    return reports


@router.get("/{video_id}", response_model=ReportDetail)
def get_report(video_id: str) -> ReportDetail:
    """Get detailed report for a single video including markdown content and frame paths."""
    ensure_db()

    with session_scope() as s:
        v = s.get(VideoModel, video_id)
        if v is None:
            raise HTTPException(status_code=404, detail=f"Video '{video_id}' not found")

        md_path, pdf_path = _find_report_files(v.id, "")
        markdown_content = ""
        if md_path and md_path.exists():
            try:
                markdown_content = md_path.read_text(encoding="utf-8")
            except Exception:
                pass

        # Reason: frames are stored in a "frames" subdirectory
        frame_dir = Path(settings.media_root) / v.channel_id / v.id / "frames"
        if not frame_dir.exists():
            frame_dir = Path(settings.media_root) / v.channel_id / v.id
        frame_paths: list[str] = []
        if frame_dir.exists():
            for f in sorted(frame_dir.glob("*.jpg")):
                frame_paths.append(f"/api/reports/frame/{video_id}/{f.name}")

        # Reason: fetch NotebookLM + Antigravity generated content for
        # this video's preset to build a combined report hub with both
        # local data and generated artifacts (slide deck, notebook URL,
        # here.now link, etc.).
        notebooklm_url = None
        notebooklm_generations: list[dict[str, Any]] = []
        agy_herenow_url = None
        agy_artifact_path = None

        try:
            from streamdoc.models.generation import Generation as GenModel
            from streamdoc.models.job import Job as JobModel
            # Reason: find jobs that processed this video and check their
            # generations. We search by matching the video_id in job details.
            jobs_with_video = s.query(JobModel).filter(
                JobModel.details.contains(video_id)
            ).order_by(JobModel.created_at.desc()).limit(5).all()

            for job in jobs_with_video:
                gens = s.query(GenModel).filter(GenModel.job_id == job.id).all()
                for g in gens:
                    if g.status == "completed" and g.local_path:
                        notebooklm_generations.append({
                            "id": g.id,
                            "content_type": g.content_type,
                            "status": g.status,
                            "local_path": g.local_path,
                            "notebook_id": g.notebook_id,
                        })
                    elif g.status in ("pending", "in_progress"):
                        notebooklm_generations.append({
                            "id": g.id,
                            "content_type": g.content_type,
                            "status": g.status,
                            "local_path": None,
                            "notebook_id": g.notebook_id,
                        })

                # Reason: get the notebook URL and agy here.now URL/artifact
                # path from job destinations when this video was part of the job.
                if job.destinations:
                    import json
                    try:
                        dests = json.loads(job.destinations)
                        if not notebooklm_url and "notebooklm_url" in dests:
                            notebooklm_url = dests["notebooklm_url"]
                        if not agy_herenow_url and "agy_herenow_url" in dests:
                            agy_herenow_url = dests["agy_herenow_url"]
                        if not agy_artifact_path and "agy_artifact_path" in dests:
                            agy_artifact_path = dests["agy_artifact_path"]
                    except Exception:
                        pass
        except Exception:
            pass

        return ReportDetail(
            video_id=v.id,
            title=v.title,
            channel_title="",
            preset_name="",
            published_at=v.published_at,
            duration_seconds=v.duration_seconds,
            frame_count=len(frame_paths),
            transcript_word_count=v.transcript_word_count or 0,
            has_pdf=pdf_path is not None,
            has_markdown=md_path is not None,
            has_frames=len(frame_paths) > 0,
            markdown_content=markdown_content,
            frame_paths=frame_paths,
            report_path=str(pdf_path) if pdf_path else (str(md_path) if md_path else None),
            thumbnail_path=_find_thumbnail(v.id, v.channel_id),
            notebooklm_url=notebooklm_url,
            notebooklm_generations=notebooklm_generations,
            agy_herenow_url=agy_herenow_url,
            agy_artifact_path=agy_artifact_path,
        )


@router.get("/thumbnail/{video_id}/{channel_id}")
def get_thumbnail(video_id: str, channel_id: str) -> FileResponse:
    """Serve a thumbnail image for a video.

    Looks in the frames subdirectory first, then falls back to the
    video directory itself for older data.
    """
    # Reason: frames are stored in a "frames" subdirectory
    frames_dir = Path(settings.media_root) / channel_id / video_id / "frames"
    if not frames_dir.exists():
        frames_dir = Path(settings.media_root) / channel_id / video_id
    if not frames_dir.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    for ext in ("*.jpg", "*.png", "*.jpeg"):
        candidates = sorted(frames_dir.glob(ext))
        if candidates:
            return FileResponse(str(candidates[0]), media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="Thumbnail not found")


@router.get("/frame/{video_id}/{filename}")
def get_frame(video_id: str, filename: str) -> FileResponse:
    """Serve an individual frame image for a video."""
    from streamdoc.models.video import Video as VideoModel

    ensure_db()
    with session_scope() as s:
        v = s.get(VideoModel, video_id)
        if v is None:
            raise HTTPException(status_code=404, detail="Video not found")

        # Reason: frames are stored in a "frames" subdirectory
        frame_path = Path(settings.media_root) / v.channel_id / video_id / "frames" / filename
        if not frame_path.exists():
            # Reason: fallback for older data without frames subdir
            frame_path = Path(settings.media_root) / v.channel_id / video_id / filename
        if not frame_path.exists():
            raise HTTPException(status_code=404, detail="Frame not found")

        return FileResponse(str(frame_path), media_type="image/jpeg")


@router.get("/download/{video_id}")
def download_report(video_id: str, format: str = "pdf") -> FileResponse:
    """Download a report file (pdf or markdown)."""
    ensure_db()

    with session_scope() as s:
        v = s.get(VideoModel, video_id)
        if v is None:
            raise HTTPException(status_code=404, detail="Video not found")

        md_path, pdf_path = _find_report_files(v.id, "")

        if format == "pdf" and pdf_path:
            return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{video_id}.pdf")
        elif format == "markdown" and md_path:
            return FileResponse(str(md_path), media_type="text/markdown", filename=f"{video_id}.md")
        elif format == "pdf" and md_path and not pdf_path:
            return FileResponse(str(md_path), media_type="text/markdown", filename=f"{video_id}.md")
        else:
            raise HTTPException(status_code=404, detail=f"Report not found in {format} format")


@router.get("/generation/{generation_id}/download")
def download_generation(generation_id: str) -> FileResponse:
    """Download a NotebookLM generated artifact (e.g. slide deck PDF).

    Args:
        generation_id: The ID of the Generation record to download.

    Returns:
        FileResponse with the generated PDF.
    """
    ensure_db()

    from streamdoc.models.generation import Generation as GenModel

    with session_scope() as s:
        gen = s.get(GenModel, generation_id)
        if gen is None:
            raise HTTPException(status_code=404, detail="Generation not found")
        if gen.status != "completed" or not gen.local_path:
            raise HTTPException(status_code=404, detail="Generated content not ready")

        from pathlib import Path
        p = Path(gen.local_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Generated file not found on disk")

        filename = f"{gen.content_type}_{gen.id}.pdf"
        return FileResponse(str(p), media_type="application/pdf", filename=filename)


@router.get("/job/{job_id}/artifact/{content_type}/download")
def download_job_artifact(job_id: str, content_type: str) -> FileResponse:
    """Download a NotebookLM generated artifact from a job's destinations.

    Used by the Jobs page to download slide decks and other generated
    content directly from the job's destination file path, without
    needing a generation_id.

    Args:
        job_id: The job ID.
        content_type: The content type key (e.g. "slide_deck").

    Returns:
        FileResponse with the generated PDF.
    """
    ensure_db()

    import json as _json
    from streamdoc.models.job import Job as JobModel

    with session_scope() as s:
        job = s.get(JobModel, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        try:
            dests = _json.loads(job.destinations) if job.destinations else {}
        except Exception:
            dests = {}

        dest_key = f"notebooklm_{content_type}"
        file_path = dests.get(dest_key)

        if not file_path or not isinstance(file_path, str):
            raise HTTPException(status_code=404, detail=f"No {content_type} artifact for this job")

        # Reason: reject error strings — only allow actual file paths
        if file_path.startswith("error") or file_path in ("pending", "in_progress"):
            raise HTTPException(status_code=404, detail=f"Artifact not ready: {file_path}")

        from pathlib import Path
        p = Path(file_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Generated file not found on disk")

        filename = f"{content_type}.pdf"
        return FileResponse(str(p), media_type="application/pdf", filename=filename)
