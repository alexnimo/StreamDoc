"""Fetch routes — trigger preset runs with SSE progress streaming."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import (
    FetchRequest,
    FetchResponse,
    SingleVideoFetchRequest,
    SingleVideoFetchResponse,
)
from streamdoc.api.sse import ProgressEvent, sse_manager, emit_progress

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fetch", tags=["fetch"])


def _run_fetch_background(job_id: str, preset: str, lookback_hours: int | None) -> None:
    """Run fetch in a background thread, emitting SSE progress events."""
    try:
        emit_progress(job_id, step="init", message=f"Starting fetch for preset: {preset}", status="running")

        from streamdoc.core.fetch import FetchPolicy, PresetRunner
        policy = None
        if lookback_hours is not None:
            policy = FetchPolicy(lookback_hours=lookback_hours)

        emit_progress(job_id, step="init", message="Initializing pipeline...", progress=0)

        runner = PresetRunner(preset, policy=policy)
        artifacts = runner.run_once(job_id=job_id)

        emit_progress(
            job_id,
            step="complete",
            message=f"Completed: {len(artifacts)} artifact(s) processed",
            progress=100,
            status="completed",
        )
    except Exception as exc:
        logger.error("Fetch failed for preset=%s: %s", preset, exc, exc_info=True)
        emit_progress(job_id, step="error", message=str(exc), status="failed")
        from streamdoc.core.jobs import fail_job
        fail_job(job_id, str(exc))
    finally:
        sse_manager.complete(job_id)


@router.post("/{preset}", response_model=FetchResponse)
async def start_fetch(
    preset: str,
    background_tasks: BackgroundTasks,
    body: FetchRequest | None = None,
):
    """Start a fetch run for a preset. Returns a job_id for SSE streaming."""
    ensure_db()

    from streamdoc.core.jobs import create_job
    job_id = create_job(preset)

    lookback = body.lookback_hours if body else None
    background_tasks.add_task(_run_fetch_background, job_id, preset, lookback)

    return FetchResponse(job_id=job_id, preset=preset, message="Fetch started")


@router.get("/{job_id}/stream")
async def fetch_stream(job_id: str):
    """SSE stream for a fetch job's progress events."""
    queue = sse_manager.subscribe(job_id)

    async def event_generator():
        try:
            # Send an initial connection event
            init_event = ProgressEvent(
                job_id=job_id,
                step="connected",
                message="Connected to stream",
                status="info",
            )
            yield f"data: {init_event.to_sse()}\n\n"

            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                if event is None:
                    # Completion signal
                    yield f"data: {{\"job_id\":\"{job_id}\",\"status\":\"done\"}}\n\n"
                    break
                yield f"data: {event.to_sse()}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {{\"job_id\":\"{job_id}\",\"status\":\"timeout\"}}\n\n"
        finally:
            sse_manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _run_single_video_background(
    job_id: str,
    url: str,
    preset_name: str | None,
    prompt_md: str,
    outputs: str,
) -> None:
    """Process a single video in the background."""
    try:
        emit_progress(job_id, step="init", message=f"Resolving video: {url}", status="running")

        from streamdoc.core.channel import resolve_video
        from streamdoc.core.fetch import (
            FetchPolicy,
            PresetRunner,
            RunArtifact,
            _download_media,
            _get_transcript,
            _is_processed,
        )
        from streamdoc.core.frames import extract_and_dedup
        from streamdoc.core.output import build_outputs
        from streamdoc.core.jobs import complete_job, create_job
        from streamdoc.db import session_scope
        from streamdoc.models.video import Video as VideoModel
        from datetime import datetime, timezone
        from pathlib import Path
        from streamdoc.config import settings

        emit_progress(job_id, step="resolve", message="Resolving video metadata...", progress=10)

        video = resolve_video(url)
        emit_progress(
            job_id,
            step="resolve",
            message=f"Found: {video.title}",
            progress=20,
            video_title=video.title,
        )

        # Check if already processed
        if _is_processed(video.id):
            emit_progress(job_id, step="skip", message="Video already processed", progress=100, status="completed")
            complete_job(job_id, [], {})
            return

        # Create video record
        now_iso = datetime.now(timezone.utc).isoformat()
        vm = VideoModel(
            id=video.id,
            channel_id=video.channel_id,
            title=video.title,
            published_at=video.published_at,
            media_status="missing",
            transcript_status="missing",
            output_status="missing",
            processed_at=now_iso,
        )
        with session_scope() as s:
            s.merge(vm)

        # Download
        emit_progress(job_id, step="download", message="Downloading video...", progress=30, video_title=video.title)
        media_path = _download_media(video)
        if media_path is None:
            with session_scope() as s:
                vmd = s.get(VideoModel, video.id)
                if vmd:
                    vmd.media_status = "failed"
            emit_progress(job_id, step="error", message="Download failed", status="failed")
            complete_job(job_id, [], {})
            return

        with session_scope() as s:
            vmd = s.get(VideoModel, video.id)
            if vmd:
                vmd.media_status = "ready"
                vmd.duration_seconds = video.duration_seconds

        # Transcribe
        emit_progress(job_id, step="transcribe", message="Transcribing audio...", progress=50, video_title=video.title)
        transcript = _get_transcript(media_path, video.id)
        tx_word_count = sum(len(seg.get("text", "").split()) for seg in transcript) if transcript else 0
        with session_scope() as s:
            vmd = s.get(VideoModel, video.id)
            if vmd:
                vmd.transcript_status = "ready" if transcript else "failed"
                vmd.transcript_word_count = tx_word_count

        # Extract frames
        emit_progress(job_id, step="frames", message="Extracting frames...", progress=70, video_title=video.title)
        frames: list[Path] = []
        try:
            frames = extract_and_dedup(media_path)
        except Exception as exc:
            logger.warning("Frames pipeline failed for %s: %s", video.id, exc)

        with session_scope() as s:
            vmd = s.get(VideoModel, video.id)
            if vmd:
                vmd.frame_count = len(frames)

        # Build outputs
        emit_progress(job_id, step="output", message="Building report...", progress=85, video_title=video.title)
        p_name = preset_name or "single_video"
        md_path, pdf_path = build_outputs(
            video_id=video.id,
            title=video.title,
            channel_title="",
            published_at=video.published_at,
            source_url=video.webpage_url or video.id,
            transcript=transcript,
            frames=frames,
            preset_name=p_name,
            prompt_md=prompt_md,
        )

        with session_scope() as s:
            vmd = s.get(VideoModel, video.id)
            if vmd:
                vmd.output_status = "ready"

        artifact = RunArtifact(
            video_id=video.id,
            md_path=md_path,
            pdf_path=pdf_path,
            status="ready",
            title=video.title,
            frame_count=len(frames),
            transcript_word_count=tx_word_count,
            frame_paths=frames,
        )

        emit_progress(
            job_id,
            step="complete",
            message=f"Completed: {video.title}",
            progress=100,
            status="completed",
            video_title=video.title,
        )
        complete_job(job_id, [artifact], {})

    except Exception as exc:
        logger.error("Single video fetch failed for %s: %s", url, exc, exc_info=True)
        emit_progress(job_id, step="error", message=str(exc), status="failed")
        from streamdoc.core.jobs import fail_job
        fail_job(job_id, str(exc))
    finally:
        sse_manager.complete(job_id)


@router.post("/single", response_model=SingleVideoFetchResponse)
async def fetch_single_video(
    body: SingleVideoFetchRequest,
    background_tasks: BackgroundTasks,
):
    """Start processing a single video URL (not tied to a preset).

    Accepts any YouTube video URL and processes it ad-hoc.
    """
    ensure_db()

    from streamdoc.core.jobs import create_job
    job_id = create_job(body.preset_name or "single_video")

    background_tasks.add_task(
        _run_single_video_background,
        job_id,
        body.url,
        body.preset_name,
        body.prompt_md,
        body.outputs,
    )

    # Try to get video ID from URL for immediate response
    video_id = ""
    video_title = ""
    try:
        from streamdoc.core.channel import resolve_video
        v = resolve_video(body.url)
        video_id = v.id
        video_title = v.title
    except Exception:
        pass

    return SingleVideoFetchResponse(
        job_id=job_id,
        video_id=video_id,
        video_title=video_title,
        message="Single video fetch started",
    )
