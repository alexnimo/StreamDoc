"""
Preset runner: fetch, download, transcribe, extract frames, build outputs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from streamdoc.integrations.social import SocialPost

from streamdoc.config import settings
from streamdoc.core.channel import Channel, resolve_channel
from streamdoc.core.channel import Video as VideoDataclass
from streamdoc.core.cleanup import run_cleanup
from streamdoc.core.downloader import build_ydl_opts
from streamdoc.core.downloader import download as _yt_dlp_download
from streamdoc.core.downloader import (
    DownloadResult,
    classify_download_error,
    is_permanent_error,
)
from streamdoc.core.frames import extract_and_dedup
from streamdoc.core.jobs import complete_job, create_job, fail_job
from streamdoc.core.output import build_outputs
from streamdoc.core.social_output import build_unified_social_outputs
from streamdoc.core.transcript import (
    fallback_audio_to_wav,
    fetch_transcript,
    transcribe_audio,
)
from streamdoc.core.youtube_api import fetch_video_metadata as _fetch_video_metadata_from_api
from streamdoc.db import init_db, session_scope
from streamdoc.integrations.notebooklm import ContentType
from streamdoc.integrations.notebooklm.prompts import PromptManager
from streamdoc.models.preset import Preset
from streamdoc.models.video import Video as VideoModel
from streamdoc.presets import clone_preset, prompt_args_for_preset

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchPolicy:
    lookback_hours: int | None = None
    max_age_days: int | None = None
    require_new: bool = True


def default_policy() -> FetchPolicy:
    return FetchPolicy(lookback_hours=24, max_age_days=None, require_new=True)


class DownloadError(Exception):
    pass


def _effective_prompt_for_preset(preset: Preset) -> str:
    """Return the effective prompt text for the report header.

    Reason: the report header should reflect the same instructions that
    the active generation backend will receive. When a template is selected
    for the active backend, load its raw prompt text; otherwise fall back
    to the preset's custom prompt_md.

    Args:
        preset: Preset configuration.

    Returns:
        Prompt text to embed in the report header.
    """
    outputs_lc = (preset.outputs or "").lower()
    agy_active = "agy" in outputs_lc and getattr(preset, "agy_enabled", False)

    if agy_active:
        # Reason: when agy is the active backend, read the agy-specific
        # prompt template first so the report header matches what agy sees.
        template_name = getattr(preset, "agy_prompt_template", None)
        if template_name:
            try:
                pm = PromptManager(settings.agy_templates_dir, settings.agy_sample_prompts_dir)
                return pm.load_template(template_name).prompt or ""
            except Exception as exc:
                logger.warning(
                    "Failed to load agy prompt template %r for preset %s: %s",
                    template_name, preset.name, exc,
                )
        return preset.prompt_md or ""

    # Reason: legacy/NotebookLM-first path. If a NotebookLM template is
    # selected, use it; otherwise fall back to an agy template or custom
    # prompt. This preserves tests and older presets that set a template
    # without explicitly enabling a backend.
    template_name = getattr(preset, "notebooklm_prompt_template", None)
    if not template_name:
        template_name = getattr(preset, "agy_prompt_template", None)
    if template_name:
        try:
            pm = PromptManager(settings.notebooklm_templates_dir, settings.notebooklm_sample_prompts_dir)
            return pm.load_template(template_name).prompt or ""
        except Exception as exc:
            logger.warning(
                "Failed to load prompt template %r for preset %s: %s",
                template_name, preset.name, exc,
            )
    return preset.prompt_md or ""


def _notebooklm_prompt_args(preset: Preset) -> dict[str, str | None]:
    """Backward-compatible shim for ``prompt_args_for_preset(preset, "notebooklm")``.

    Reason: kept so existing tests and call sites outside of this module
    that import this name directly do not break. New code should call
    :func:`streamdoc.presets.prompt_args_for_preset` directly.
    """
    return prompt_args_for_preset(preset, "notebooklm")


def _design_prompt_for_preset(
    preset: Preset,
    content_type: ContentType,
) -> str | None:
    """Render the preset's ``design_prompt_template`` into injectable text.

    Reason (POR-91 T2): design injection is off-by-default — a NULL or
    blank ``design_prompt_template`` returns None so callers pass
    ``design_prompt=None`` and the upload layer emits byte-identical
    prompts. A bad template config must NEVER fail a run, so every
    failure mode (unknown name -> KeyError, unsupported content type ->
    ValueError, or anything else) logs a warning and returns None.

    Args:
        preset: Preset configuration.
        content_type: ContentType the design template renders against.

    Returns:
        Rendered design prompt text, or None.
    """
    template_name = (getattr(preset, "design_prompt_template", None) or "").strip()
    if not template_name:
        return None
    try:
        pm = PromptManager(
            settings.notebooklm_templates_dir,
            settings.notebooklm_sample_prompts_dir,
        )
        return pm.render_prompt(template_name, content_type)
    except Exception:
        logger.warning(
            "design template %r unusable; skipping design injection",
            template_name,
        )
        return None


class RunArtifact:
    """Result of processing a single video."""

    def __init__(
        self,
        video_id: str,
        md_path: Path,
        pdf_path: Path | None,
        status: str = "ready",
        *,
        title: str = "",
        channel_title: str = "",
        duration_seconds: int | None = None,
        frame_count: int = 0,
        transcript_word_count: int = 0,
        transcript_text: str = "",
        frame_paths: list[Path] | None = None,
        error: str | None = None,
    ):
        self.video_id = video_id
        self.md_path = md_path
        self.pdf_path = pdf_path
        self.status = status
        self.title = title
        self.channel_title = channel_title
        self.duration_seconds = duration_seconds
        self.frame_count = frame_count
        self.transcript_word_count = transcript_word_count
        self.transcript_text = transcript_text
        self.frame_paths = frame_paths or []
        self.error = error


class PresetRunner:
    def __init__(self, preset_name: str, policy: FetchPolicy | None = None):
        # Reason: preset_name is actually the preset ID (used to load from DB).
        # The display name is resolved from the Preset.name field in run_once.
        self.preset_id = preset_name
        self.preset_name = preset_name  # Reason: kept for backward compat
        self.policy = policy or default_policy()
        init_db()

    def run_once(self, job_id: str | None = None) -> list[RunArtifact]:
        """Run the preset fetch pipeline.

        Args:
            job_id: Optional pre-existing job ID. If None, a new job is created.
                When provided by the caller (e.g. API route), the caller's job
                is reused to avoid duplicates.
        """
        from streamdoc.api.sse import emit_progress

        own_job = job_id is None
        if own_job:
            job_id = create_job(self.preset_id)
        assert job_id is not None

        emit_progress(job_id, step="init", message=f"Loading preset: {self.preset_id}", progress=5)
        preset = self._load_preset(self.preset_id)

        # Reason: branch on preset_type so the social pipeline can run its
        # own collect → process → send loop without polluting the youtube path.
        preset_type = getattr(preset, "preset_type", "youtube") or "youtube"
        if preset_type == "social":
            return self._run_social(preset, job_id)
        # Default: youtube pipeline (unchanged below)

        # Reason: update the job's preset_name to the display name (e.g.
        # "full-poc-1") instead of the internal ID (e.g. "amd-report")
        # so the UI shows the user-friendly name.
        if preset.name and preset.name != self.preset_id:
            from streamdoc.db import session_scope as _ss
            from streamdoc.models.job import Job as _JobModel
            try:
                with _ss() as _s:
                    _j = _s.get(_JobModel, job_id)
                    if _j:
                        _j.preset_name = preset.name
            except Exception:
                pass

        lookback_hours = (
            preset.lookback_hours
            if preset.lookback_hours is not None
            else (self.policy.lookback_hours or 24)
        )
        date_range_days = preset.date_range_days
        text_filter = preset.text_filter
        max_videos = preset.max_videos
        playlist_mode = preset.playlist_mode

        emit_progress(job_id, step="channels", message="Resolving channels...", progress=10)
        channels = self._resolve_channels(preset)
        if not channels:
            logger.info("No channels resolved for preset=%s", self.preset_name)
            emit_progress(job_id, step="channels", message="No channels found", progress=100, status="completed")
            complete_job(job_id, [], {})
            return []

        emit_progress(
            job_id,
            step="channels",
            message=f"Resolved {len(channels)} channel(s)",
            progress=15,
        )

        # Reason: both fields define the same cutoff in different units. The
        # hours field is the default; if days is also set, it takes priority
        # so the user can express a longer window conveniently. They are not
        # additive — they are the same feature exposed as hours vs. days.
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        if date_range_days:
            cutoff = datetime.now(UTC) - timedelta(days=date_range_days)

        # Phase 1: Collect all candidate videos across all channels
        # Reason: we need the total video count upfront to calculate
        # accurate progress percentages. Without this, the progress bar
        # stays stuck at the same value for every video.
        # Reason: max_videos is a per-channel limit. For each channel we look
        # back to the cutoff, drop processed/filtered videos, and keep up to
        # max_videos of the newest ones. This prevents channels later in the
        # list from being starved by earlier channels and matches the product
        # expectation ("max videos per channel in the time window").
        total_channels = len(channels)
        all_candidates: list[tuple[Channel, VideoDataclass]] = []
        for ch_idx, ch in enumerate(channels):
            channel_progress_base = 15 + int((ch_idx / max(total_channels, 1)) * 10)
            emit_progress(
                job_id,
                step="list_videos",
                message=f"Listing videos for: {ch.title or ch.id}",
                progress=channel_progress_base,
            )
            try:
                # Reason: do not pass max_videos here; we want all recent
                # videos from the channel so the per-channel filter can pick
                # the newest ones accurately.
                vids = _list_videos(ch, playlist_mode=playlist_mode, max_videos=None)
            except Exception as exc:
                logger.warning("Channel resolution failed for %s: %s", ch.id, exc)
                emit_progress(job_id, step="list_videos", message=f"Failed to list videos for {ch.title}: {exc}", status="running")
                continue
            emit_progress(
                job_id,
                step="list_videos",
                message=f"Found {len(vids)} video(s) for {ch.title or ch.id}",
                progress=channel_progress_base + 2,
            )
            channel_candidates: list[tuple[Channel, VideoDataclass]] = []
            for v in vids:
                pub = _parse_published(v.published_at)
                if pub < cutoff:
                    logger.info("Skipping video=%s (published %s, before cutoff %s)", v.id, pub.isoformat(), cutoff.isoformat())
                    continue
                if text_filter and text_filter.lower() not in v.title.lower():
                    logger.info("Skipping video=%s (title doesn't match filter=%r)", v.id, text_filter)
                    continue
                if preset.skip_processed:
                    if _is_processed(v.id):
                        logger.info("Skipping already-processed video=%s", v.id)
                        continue
                channel_candidates.append((ch, v))
            # Reason: apply per-channel max_videos, keeping the newest videos
            # first. RSS/flat extraction already returns newest-first, but we
            # sort explicitly to be safe.
            channel_candidates.sort(key=lambda item: _parse_published(item[1].published_at), reverse=True)

            # Reason: skip Shorts before counting against max_videos. RSS feeds
            # don't include duration, so fetch metadata for any candidates that
            # are missing it. yt-dlp flat extraction already provides duration.
            if settings.skip_shorts and channel_candidates:
                missing_meta = [v for _, v in channel_candidates if v.duration_seconds is None]
                if missing_meta:
                    ids = [v.id for v in missing_meta]
                    meta = _fetch_video_metadata(ids, limit=len(ids), max_workers=5)
                    for _, v in channel_candidates:
                        if v.id in meta:
                            v.duration_seconds = meta[v.id].get("duration_seconds")
                            v.webpage_url = meta[v.id].get("webpage_url") or v.webpage_url
                            if not v.published_at:
                                v.published_at = meta[v.id].get("published_at") or ""
                filtered = [(c, v) for c, v in channel_candidates if not _is_short(v)]
                skipped = len(channel_candidates) - len(filtered)
                if skipped:
                    logger.info("Channel %s skipped %d Short(s)", ch.id, skipped)
                channel_candidates = filtered

            if max_videos and len(channel_candidates) > max_videos:
                logger.info(
                    "Channel %s has %d candidate(s) within window; capping to max_videos=%d",
                    ch.id, len(channel_candidates), max_videos,
                )
                channel_candidates = channel_candidates[:max_videos]
            all_candidates.extend(channel_candidates)

        # Reason: deduplicate candidates by video ID — the same video may
        # appear in multiple channels/playlists listed in the preset, which
        # would cause it to be downloaded and processed multiple times
        # (wasting time and generating duplicate artifacts).
        seen_ids: set[str] = set()
        deduped: list[tuple[Channel, VideoDataclass]] = []
        for ch, v in all_candidates:
            if v.id in seen_ids:
                logger.info("Skipping duplicate video=%s (already in candidates)", v.id)
                continue
            seen_ids.add(v.id)
            deduped.append((ch, v))
        all_candidates = deduped

        # Reason: sort newest first across all channels so the most recent
        # content is processed first.
        all_candidates.sort(key=lambda item: _parse_published(item[1].published_at), reverse=True)

        # Phase 2: Process videos with accurate progress
        # Reason: progress spans 15%–90% of the bar, divided evenly across
        # all candidate videos so the bar actually moves as each completes.
        total_to_process = len(all_candidates)
        artifacts: list[RunArtifact] = []
        for idx, (ch, v) in enumerate(all_candidates):
            vid_num = idx + 1
            # Progress: 15% (start) to 90% (end), scaled by video index
            if total_to_process > 0:
                video_progress = 15 + int((idx / total_to_process) * 75)
            else:
                video_progress = 15
            emit_progress(
                job_id,
                step="process",
                message=f"Processing video {vid_num}/{total_to_process}: {v.title}",
                progress=video_progress,
                video_title=v.title,
            )
            try:
                artifact = self._process_video(
                    preset, ch, v,
                    job_id=job_id,
                    vid_num=vid_num,
                    total_to_process=total_to_process,
                )
            except Exception as exc:
                logger.error("Processing failed for video=%s: %s", v.id, exc, exc_info=True)
                emit_progress(job_id, step="process", message=f"Failed: {v.title} — {exc}", status="running")
                continue
            if artifact is not None:
                artifacts.append(artifact)
                # Progress after completing this video
                if total_to_process > 0:
                    done_progress = 15 + int(((idx + 1) / total_to_process) * 75)
                else:
                    done_progress = 90
                emit_progress(
                    job_id,
                    step="process",
                    message=f"Done: {v.title} ({len(artifacts)}/{total_to_process} processed)",
                    progress=done_progress,
                    video_title=v.title,
                )

        emit_progress(job_id, step="report", message="Compiling preset report...", progress=90)
        from streamdoc.core.report import compile_preset_report
        if artifacts:
            # Reason: use preset.name (display name) to match build_outputs,
            # which saves individual reports under output_root/<preset.name>/.
            compile_preset_report(preset.name, artifacts)
        else:
            logger.info("No new artifacts to compile for preset %s (all videos already processed)", self.preset_id)

        emit_progress(
            job_id,
            step="upload",
            message="Uploading to destinations..." if artifacts else "Uploading existing reports to destinations...",
            progress=95,
        )
        # Reason: pass candidates_attempted so _send_reports can distinguish
        # "all videos already processed" (candidates_attempted == 0, artifacts
        # empty → OK to re-upload existing reports) from "all downloads failed"
        # (candidates_attempted > 0, artifacts empty → must NOT upload stale
        # reports from a previous run).
        destination_results = self._send_reports(
            preset, artifacts, job_id, candidates_attempted=total_to_process
        )
        complete_job(job_id, artifacts, destination_results)

        # Run retention cleanup
        try:
            run_cleanup()
        except Exception as exc:
            logger.warning("Retention cleanup failed: %s", exc)

        return artifacts

    def _send_reports(
        self,
        preset: Preset,
        artifacts: list[RunArtifact],
        job_id: str,
        candidates_attempted: int = 0,
    ) -> dict[str, Any]:
        """Send reports to configured external destinations.

        Dispatches to the appropriate backend based on ``preset.outputs`` and
        the backend-specific enable flags. The precedence is:
        1. ``"agy"`` in outputs AND ``preset.agy_enabled`` → agy backend
        2. ``"notebooklm"`` in outputs AND ``preset.notebooklm_kind`` → NotebookLM
        3. Neither matched → return empty dict (no upload attempted)

        Args:
            preset: Preset configuration.
            artifacts: Artifacts produced by the current run.
            job_id: Active job ID for log correlation.
            candidates_attempted: Number of videos that entered the processing
                phase. When > 0 and ``artifacts`` is empty, all downloads
                failed — the existing-report fallback must NOT trigger because
                it would upload stale reports from a previous run. When 0 and
                ``artifacts`` is empty, all videos were already processed (or
                no candidates matched) — re-uploading existing reports is the
                intended behaviour.

        Returns:
            Dict of destination name -> result value (str or list[str]).
        """
        destinations: dict[str, Any] = {}

        # Reason: determine the active backend from the outputs field + the
        # per-backend enable flags. agy takes priority over notebooklm when
        # both tokens appear in outputs and agy_enabled is True, matching the
        # product spec's "agy is the newer, preferred backend" rule. We use
        # getattr with safe defaults so older DB rows that lack the agy columns
        # (pre-migration) do not crash — they simply fall through to notebooklm.
        # Reason: when outputs is None or empty, we fall through to the
        # notebooklm_kind check for backward compat. Presets created before the
        # outputs field was introduced (or created directly in Python without
        # going through the DB) may have outputs=None even when notebooklm is
        # the intended backend. The notebooklm_kind guard below is the
        # authoritative check for the notebooklm branch.
        backend: str | None = None
        outputs_lc = (preset.outputs or "").lower()
        if "agy" in outputs_lc and getattr(preset, "agy_enabled", False):
            backend = "agy"
        elif "notebooklm" in outputs_lc and preset.notebooklm_kind:
            backend = "notebooklm"
        elif not outputs_lc and preset.notebooklm_kind:
            # Reason: backward compat — outputs is unset (None/empty) but
            # notebooklm_kind is configured. Treat as the notebooklm path
            # so existing presets and tests that don't set outputs explicitly
            # continue to work.
            backend = "notebooklm"
        if not backend:
            return destinations

        # Reason: short-circuit to _send_to_agy so the remaining function body
        # (the full NotebookLM branch) is reached only when backend=="notebooklm".
        if backend == "agy":
            return self._send_to_agy(
                preset, artifacts, job_id, candidates_attempted=candidates_attempted
            )

        if not preset.notebooklm_kind:
            return destinations

        # Reason: use preset.name (display name) for directory paths to
        # match build_outputs, which saves files under
        # output_root/<preset.name>/. The previous code used preset_id
        # which caused a directory mismatch — files were saved under
        # <display_name>/ but _send_reports looked in <preset_id>/.
        out_dir = Path(settings.output_root) / preset.name
        if not out_dir.exists():
            return destinations

        from streamdoc.core.notebooklm_upload import upload_to_notebooklm

        # Build report paths from artifacts
        # Reason: only upload PDF to NotebookLM — MD and PDF contain the same
        # content in different formats. PDF preserves formatting and is the
        # richer source for NotebookLM to process.
        report_paths: list[Path] = []
        for a in artifacts:
            if a.pdf_path and a.pdf_path.exists():
                report_paths.append(a.pdf_path)
            elif a.md_path and a.md_path.exists():
                # Reason: fallback to MD only if PDF is not available
                report_paths.append(a.md_path)

        # Reason: when skip_processed=True and all videos were already
        # processed, artifacts is empty. But the user may be re-running
        # specifically to upload existing reports to NotebookLM. Scan the
        # output directory for existing .pdf files and upload those.
        # HOWEVER: this fallback must only trigger when no candidates entered
        # processing (candidates_attempted == 0). If candidates_attempted > 0
        # and artifacts is empty, it means all downloads/processing FAILED —
        # uploading stale reports from a previous run would be misleading and
        # produce a presentation based on old content.
        if not report_paths and candidates_attempted == 0:
            existing_pdfs = sorted(out_dir.glob("*.pdf"))
            # Reason: exclude FULL_REPORT files — those are aggregate
            # reports, not per-video reports that NotebookLM should ingest.
            existing_pdfs = [p for p in existing_pdfs if p.stem != "FULL_REPORT"]
            if existing_pdfs:
                logger.info(
                    "No new artifacts, but found %d existing PDF report(s) in %s — uploading to NotebookLM",
                    len(existing_pdfs),
                    out_dir,
                )
                report_paths = existing_pdfs
        elif not report_paths and candidates_attempted > 0:
            # Reason: all candidates failed to process — do NOT upload stale
            # reports. Log a clear warning so the operator knows the run
            # produced nothing and the previous reports were intentionally
            # left untouched.
            logger.warning(
                "Skipping NotebookLM upload: %d video(s) entered processing but "
                "all failed — not uploading stale reports from previous runs",
                candidates_attempted,
            )

        if not report_paths:
            logger.warning("No report files found for NotebookLM upload")
            return destinations

        # Map notebooklm_kind to content types
        content_types: list[ContentType] = []
        kind = (preset.notebooklm_kind or "").lower().strip()
        if kind:
            try:
                content_types = [ContentType(kind)]
            except ValueError:
                logger.warning("Unknown notebooklm_kind=%s, skipping content generation", kind)

        try:
            from streamdoc.async_utils import run_async
            # Reason: notebooklm_kind is a content type (e.g. "slide_deck"),
            # NOT a prompt template name. The prompt comes from two sources:
            # 1. notebooklm_prompt_template: a named template (e.g. "financial_extraction")
            #    selected from the dropdown — highest priority
            # 2. prompt_md: raw text instructions the user typed in the prompt
            #    box — used as custom_prompt when no template is selected
            # 3. settings.notebooklm_default_prompt: system default — only
            #    used when neither of the above is set
            # Reason: use preset.name (display name) for the notebook title,
            # not self.preset_id which is the internal ID like "test1".
            # Reason: pass the preset's notebook_retention_hours so the
            # RetentionManager registers the notebook with the correct
            # expiration. When retention_enabled is False, mark as permanent
            # so the notebook is never cleaned up.
            notebook_retention = getattr(preset, "notebook_retention_hours", None)
            retention_enabled = getattr(preset, "retention_enabled", True)
            # Reason: use the helper so only one of prompt_template or
            # custom_prompt is passed. This enforces the preset's selected
            # mode (template vs custom) and makes the log output unambiguous.
            # Pass backend="notebooklm" so prompt_args_for_preset reads the
            # correct preset field (notebooklm_prompt_template).
            prompt_args = prompt_args_for_preset(preset, "notebooklm")
            logger.info(
                "Preset prompt config for NotebookLM: template=%r custom_prompt=%r chars",
                prompt_args["prompt_template"],
                len(prompt_args["custom_prompt"]) if prompt_args["custom_prompt"] else 0,
            )
            result = run_async(upload_to_notebooklm(
                report_paths=report_paths,
                preset_name=preset.name,
                job_id=job_id,
                content_types=content_types if content_types else None,
                prompt_template=prompt_args["prompt_template"],
                custom_prompt=prompt_args["custom_prompt"],
                design_prompt=_design_prompt_for_preset(
                    preset,
                    content_types[0] if content_types else ContentType.REPORT,
                ),
                retention_hours=notebook_retention,
                is_permanent=not retention_enabled,
                retry_generation=getattr(preset, "notebooklm_retry_failed", True),
                retry_attempts=getattr(preset, "notebooklm_retry_attempts", 1),
                retry_delay=(getattr(preset, "notebooklm_retry_delay_minutes", 5.0) or 5.0) * 60,
            ))

            if result.success:
                destinations["notebooklm"] = "success"
                if result.notebook_url:
                    destinations["notebooklm_url"] = result.notebook_url
                if result.generated_content:
                    for gc in result.generated_content:
                        ct_name = gc.content_type.value if hasattr(gc, "content_type") else str(gc.content_type)
                        gc_status = getattr(gc, "status", "")
                        gc_local = getattr(gc, "local_path", None)
                        gc_error = getattr(gc, "error", "")
                        # Reason: only store the path if the file actually exists
                        if gc_local and Path(gc_local).exists():
                            destinations[f"notebooklm_{ct_name}"] = str(gc_local)
                        elif gc_status == "pending":
                            # Reason: generation is still running async —
                            # the background poller will download it later
                            destinations[f"notebooklm_{ct_name}"] = "pending"
                        elif gc_status == "failed":
                            # Reason: use the actual error message (e.g.
                            # "Daily limit reached") so the job shows as
                            # "partial" with a clear reason.
                            destinations[f"notebooklm_{ct_name}"] = (
                                f"error: {gc_error}" if gc_error else "error: generation failed"
                            )
                        else:
                            # Reason: status is "completed" but the file
                            # doesn't exist — this is a phantom success.
                            # Mark as error so the job shows partial.
                            destinations[f"notebooklm_{ct_name}"] = (
                                f"error: {ct_name} generated but file not found on disk"
                            )
                # Reason: also capture errors from result.errors (e.g.
                # exceptions that escaped batch_generate) even when
                # result.success is True (notebook was created but some
                # content types failed).
                if result.errors:
                    for err in result.errors:
                        if "notebooklm" not in err.lower():
                            destinations.setdefault("notebooklm_errors", []).append(err)

                # T4: notify on notebooklm success — failures here MUST NOT affect job status
                try:
                    from streamdoc.core.notify import notify_run_success
                    # Reason: notebooklm has no single artifact_path; pick the first
                    # local_path from successful generated_content, else None.
                    nb_artifact: str | None = None
                    for gc in result.generated_content or []:
                        gc_local = getattr(gc, "local_path", None)
                        gc_status = getattr(gc, "status", None)
                        if gc_local and Path(gc_local).exists() and gc_status in (None, "completed"):
                            nb_artifact = str(gc_local)
                            break
                    notify_run_success(
                        preset.name,
                        getattr(result, "notebook_url", None),
                        nb_artifact,
                    )
                except Exception as exc:
                    logger.warning("notify_run_success (notebooklm) failed: %s", exc)
            else:
                err = "; ".join(result.errors) if result.errors else "Upload failed"
                destinations["notebooklm"] = f"error: {err}"
        except Exception as exc:
            destinations["notebooklm"] = f"error: {exc}"
            logger.warning("NotebookLM upload failed: %s", exc)

        return destinations

    def _run_social(self, preset: Preset, job_id: str) -> list[RunArtifact]:
        """Social sentiment pipeline: collect → process per-post → send.

        Iterates ``preset.social_sources``, invokes each registered
        ``SocialSource`` collector, deduplicates via the ``SocialPostStore``,
        builds one ``RunArtifact`` per post via ``_process_social_post``,
        and dispatches to configured destinations.

        Args:
            preset: Loaded preset with social configuration.
            job_id: Active job ID for progress tracking.

        Returns:
            List of RunArtifact objects (one per post).
        """
        import json as _json
        from datetime import datetime

        from streamdoc.api.sse import emit_progress
        from streamdoc.integrations.social import (
            SocialPostStore,
            get_collector,
        )
        from streamdoc.models.preset import (
            SocialSourceConfig,
        )

        # Reason: social sources are stored as a JSON array of
        # {platform, identifier, max_posts?} objects. The DB column is
        # plain Text, so we parse JSON first. Deserialize via the
        # SocialSourceConfig dataclass for validation.
        raw_sources = getattr(preset, "social_sources", None)
        if not raw_sources:
            logger.warning("Social preset %s has no social_sources configured", preset.name)
            emit_progress(job_id, step="social_error", message="No social sources configured", progress=100)
            fail_job(job_id, "Social preset has no social_sources configured")
            return []

        # Reason: social_sources is stored as a JSON string in the DB;
        # parse it into a list of dicts for SocialSourceConfig construction.
        if isinstance(raw_sources, str):
            try:
                raw_sources = _json.loads(raw_sources)
            except (ValueError, TypeError):
                logger.error("Cannot parse social_sources JSON for %s", preset.name)
                fail_job(job_id, "Invalid social_sources JSON")
                return []

        try:
            if isinstance(raw_sources, str):
                raw_sources = _json.loads(raw_sources)
            sources = [SocialSourceConfig(**s) if isinstance(s, dict) else s for s in raw_sources]
        except Exception as exc:
            logger.error("Invalid social_sources config for %s: %s", preset.name, exc)
            fail_job(job_id, f"Invalid social_sources config: {exc}")
            return []

        emit_progress(job_id, step="collect_social", message=f"Collecting from {len(sources)} sources...", progress=10)

        lookback_hours = getattr(preset, "social_lookback_hours", None) or 24
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        dedup_store = SocialPostStore()

        all_posts: list[SocialPost] = []

        # Reason: reset processed markers outside the lookback window so the
        # same content can be re-collected in a future run, mirroring the
        # video dedup pattern.
        dedup_store.reset_outside_window(preset.name, lookback_hours)

        skip_processed = getattr(preset, "skip_processed", True)

        for idx, src in enumerate(sources):
            platform = src.platform
            identifier = src.identifier
            max_posts_src = src.max_posts or getattr(preset, "social_max_posts", None)

            collector_cls = get_collector(platform)
            if collector_cls is None:
                logger.warning("No collector registered for platform=%s, skipping", platform)
                continue

            emit_progress(
                job_id,
                step="collect_social",
                message=f"Collecting from {platform}/{identifier}...",
                progress=10 + int((idx + 1) / len(sources) * 40),
            )

            try:
                collector = collector_cls()
                posts = collector.collect(
                    preset=preset,
                    source_descriptor=identifier,
                    cutoff=cutoff,
                    dedup_store=dedup_store,
                    max_posts=max_posts_src,
                    skip_processed=skip_processed,
                )
                logger.info("Collected %d posts from %s/%s", len(posts), platform, identifier)
                all_posts.extend(posts)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to collect from %s/%s: %s", platform, identifier, exc)
                # Continue with other sources — a single failure shouldn't
                # block the whole pipeline
                continue

        if not all_posts:
            logger.info("No social posts collected for preset %s", preset.name)
            emit_progress(job_id, step="social_done", message="No new social posts found", progress=100)
            complete_job(job_id, [], {})
            return []

        # Reason: sort newest-first so the report reads in reverse chronological
        # order, with the latest posts at the top.
        all_posts.sort(key=lambda p: p.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)

        emit_progress(
            job_id,
            step="process_post",
            message=f"Processing {len(all_posts)} posts...",
            progress=50,
        )

        emit_progress(job_id, step="report", message="Building unified social report...", progress=75)

        try:
            md_path, pdf_path = build_unified_social_outputs(
                posts=all_posts,
                preset_name=preset.name,
                prompt_md=_effective_prompt_for_preset(preset),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to build unified social report for %s: %s", preset.name, exc)
            emit_progress(job_id, step="social_done", message="Report generation failed", progress=100)
            fail_job(job_id, f"Report generation failed: {exc}")
            return []

        total_images = sum(len(post.images) for post in all_posts)
        total_words = sum(len(post.text.split()) for post in all_posts)

        # Reason: only mark posts as processed after the unified report is
        # successfully created, so a failure in report generation can be
        # retried on the next run.
        dedup_store.mark_processed_many(all_posts, preset.name)

        artifact = RunArtifact(
            video_id=md_path.stem,
            md_path=md_path,
            pdf_path=pdf_path,
            status="ready",
            title=f"Social Report — {preset.name}",
            channel_title="social",
            transcript_word_count=total_words,
            transcript_text="",
            frame_count=total_images,
            frame_paths=[Path(img) for post in all_posts for img in post.images],
        )

        emit_progress(job_id, step="upload", message="Sending to destinations...", progress=90)

        destination_results = self._send_reports(preset, [artifact], job_id)
        if not destination_results:
            logger.info("No destinations configured for preset %s", preset.name)

        emit_progress(job_id, step="social_done", message="Social pipeline complete", progress=100)
        complete_job(job_id, [artifact], destination_results)
        return [artifact]

    def _send_to_agy(
        self,
        preset: Preset,
        artifacts: list[RunArtifact],
        job_id: str,
        candidates_attempted: int = 0,
    ) -> dict[str, Any]:
        """Upload reports to the Antigravity (agy) backend.

        Delegates file selection and upload logic to
        :func:`streamdoc.core.agy_upload.send_reports_to_agy` so this file
        stays focused on pipeline orchestration.

        Args:
            preset: Preset configuration.
            artifacts: Artifacts produced by the current run.
            job_id: Active job ID passed through for log correlation.
            candidates_attempted: Number of videos that entered processing
                (passed through to guard the existing-report fallback).

        Returns:
            Dict of destination name -> result string.
        """
        from streamdoc.core.agy_upload import (
            _DEFAULT_AGY_CONTENT_TYPE,
            send_reports_to_agy,
        )

        prompt_args = prompt_args_for_preset(preset, "agy")
        logger.info(
            "Preset prompt config for agy: template=%r custom_prompt=%r chars",
            prompt_args["prompt_template"],
            len(prompt_args["custom_prompt"]) if prompt_args["custom_prompt"] else 0,
        )

        return send_reports_to_agy(
            preset=preset,
            artifacts=artifacts,
            job_id=job_id,
            prompt_template=prompt_args["prompt_template"],
            custom_prompt=prompt_args["custom_prompt"],
            candidates_attempted=candidates_attempted,
            design_prompt=_design_prompt_for_preset(preset, _DEFAULT_AGY_CONTENT_TYPE),
        )

    def _load_preset(self, name: str) -> Preset:
        with session_scope() as s:
            p = s.get(Preset, name)
            if p is None:
                raise ValueError(f"Preset not found: {name}")
            s.refresh(p)
            return clone_preset(p)

    def _resolve_channels(self, preset: Preset) -> list[Channel]:
        raw = preset.channel_list_id or ""
        if not raw.strip():
            return []
        out: list[Channel] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(resolve_channel(part))
            except Exception as exc:
                logger.warning("Failed to resolve channel/playlist %s: %s", part, exc)
        return out

    def _process_video(
        self,
        preset: Preset,
        ch: Channel,
        v: VideoDataclass,
        job_id: str = "",
        vid_num: int = 0,
        total_to_process: int = 0,
    ) -> RunArtifact | None:
        """Process a single video through the full pipeline.

        Args:
            preset: Preset configuration.
            ch: Channel the video belongs to.
            v: Video dataclass.
            job_id: Active job ID for SSE progress events.
            vid_num: 1-based index of this video for progress messages.
            total_to_process: Total videos to process (for progress messages).
        """
        from streamdoc.api.sse import emit_progress as _emit

        def _sub_progress(step: str, msg: str, sub_pct: float) -> None:
            """Emit a sub-step progress event within the current video's range."""
            if not job_id or total_to_process == 0:
                return
            # Reason: each video gets a slice of the 15-90% range.
            # Within that slice, sub_pct (0-1) tracks the sub-step.
            video_start = 15 + int((vid_num - 1) / total_to_process * 75)
            video_end = 15 + int(vid_num / total_to_process * 75)
            progress = video_start + int((video_end - video_start) * sub_pct)
            _emit(job_id, step=step, message=msg, progress=progress, video_title=v.title)

        label = f"{vid_num}/{total_to_process}" if total_to_process else ""
        logger.info("Processing video: %s — %s", v.id, v.title)
        now_iso = datetime.now(UTC).isoformat()
        vm = VideoModel(
            id=v.id,
            channel_id=ch.id,
            title=v.title,
            published_at=v.published_at,
            media_status="missing",
            transcript_status="missing",
            output_status="missing",
            processed_at=now_iso,
        )
        with session_scope() as s:
            s.merge(vm)
        # Reason: show the effective bypass mode alongside the download start
        # so the operator can confirm the PO token (or other bypass) is
        # actually in use for this run. The mode is resolved via the same
        # helper the downloader uses, so it matches exactly.
        try:
            from streamdoc.core.downloader import _resolve_effective_mode
            dl_mode = _resolve_effective_mode()
        except Exception:
            dl_mode = "unknown"
        _sub_progress("download", f"[{label}] Downloading video (bypass: {dl_mode})...", 0.1)
        logger.info("Downloading media for video: %s (bypass_mode=%s)", v.id, dl_mode)
        dl_result = _download_media(v)
        if dl_result.path is None:
            category = dl_result.error_category
            # Reason: permanent errors (members-only, private, deleted,
            # age-restricted, region-blocked) can never be resolved by
            # retrying. Mark the video with a distinct media_status so
            # _is_processed skips it on future runs and the UI can surface
            # why it was skipped.
            if is_permanent_error(category):
                status = "restricted"
                reason = {
                    "members_only": "members-only content",
                    "private_deleted": "private/deleted video",
                    "age_restricted": "age-restricted content",
                    "region_blocked": "region-blocked video",
                }.get(category, category)
                logger.warning("Download permanently failed for %s [%s]: %s", v.id, category, reason)
                _emit(
                    job_id,
                    step="download",
                    message=f"Skipped: {v.title} — {reason}",
                    status="running",
                    video_title=v.title,
                )
            else:
                status = "failed"
                logger.warning("Download failed for video: %s [%s]: %s", v.id, category, dl_result.error)
                _emit(
                    job_id,
                    step="download",
                    message=f"Download failed: {v.title} — {category}",
                    status="running",
                    video_title=v.title,
                )
            with session_scope() as s:
                vmd = s.get(VideoModel, v.id)
                if vmd:
                    vmd.media_status = status
            return None
        media_path = dl_result.path
        logger.info("Download complete: %s -> %s", v.id, media_path)
        _sub_progress("transcribe", f"[{label}] Transcribing audio...", 0.3)
        with session_scope() as s:
            vmd = s.get(VideoModel, v.id)
            if vmd:
                vmd.media_status = "ready"
                vmd.duration_seconds = v.duration_seconds
        logger.info("Fetching transcript for video: %s", v.id)
        transcript = _get_transcript(media_path, v.id)
        # Reason: if the transcript is empty, it means either the official
        # API failed AND Whisper timed out or failed. Log a clear warning
        # so the user understands why the report may have no transcript.
        if not transcript:
            logger.warning(
                "No transcript available for video=%s (official API + Whisper both failed/timed out) "
                "— report will contain frames only",
                v.id,
            )
            _sub_progress("transcribe", f"[{label}] No transcript — continuing with frames only", 0.5)
        transcript_status = "ready" if transcript else "failed"
        tx_word_count = sum(len(seg.get("text", "").split()) for seg in transcript) if transcript else 0
        tx_text = " ".join(seg.get("text", "").strip() for seg in transcript if seg.get("text", "").strip()) if transcript else ""
        logger.info("Transcript %s for video: %s (%d words)", transcript_status, v.id, tx_word_count)
        _sub_progress("frames", f"[{label}] Extracting frames...", 0.6)
        with session_scope() as s:
            vmd = s.get(VideoModel, v.id)
            if vmd:
                vmd.transcript_status = transcript_status
                vmd.transcript_word_count = tx_word_count
        frames: list[Path] = []
        try:
            logger.info("Extracting frames for video: %s", v.id)
            frames = extract_and_dedup(media_path)
            logger.info("Extracted %d frames for video: %s", len(frames), v.id)
        except Exception as exc:
            logger.warning("Frames pipeline failed for %s: %s", v.id, exc)
        _sub_progress("output", f"[{label}] Building report...", 0.8)
        with session_scope() as s:
            vmd = s.get(VideoModel, v.id)
            if vmd:
                vmd.frame_count = len(frames)
        logger.info("Building outputs for video: %s", v.id)
        md_path, pdf_path = build_outputs(
            video_id=v.id,
            title=v.title,
            channel_title=ch.title,
            published_at=v.published_at,
            source_url=v.webpage_url or ch.id,
            transcript=transcript,
            frames=frames,
            preset_name=preset.name,
            prompt_md=_effective_prompt_for_preset(preset),
        )
        # Reason: always mark the video as "ready" after outputs are built.
        # NotebookLM upload is handled as a batch operation in _send_reports
        # at the end of run_once, NOT per-video. The previous per-video
        # upload caused two bugs:
        # 1. "NotebookLM content type not selected" error when
        #    preset.notebooklm_kind was None (raised RuntimeError)
        # 2. output_status was set to "integration-failed" instead of
        #    "ready", so _is_processed returned False and videos were
        #    re-downloaded/re-transcribed on every run (infinite loop)
        output_status = "ready"
        with session_scope() as s:
            vmd = s.get(VideoModel, v.id)
            if vmd:
                vmd.output_status = output_status
        return RunArtifact(
            video_id=v.id,
            md_path=md_path,
            pdf_path=pdf_path,
            status=output_status,
            title=v.title,
            channel_title=ch.title,
            duration_seconds=v.duration_seconds,
            frame_count=len(frames),
            transcript_word_count=tx_word_count,
            transcript_text=tx_text,
            frame_paths=frames,
            error=None,
        )


def run_fetch(preset_name: str, policy: FetchPolicy | None = None, job_id: str | None = None) -> list[RunArtifact]:
    return PresetRunner(preset_name=preset_name, policy=policy).run_once(job_id=job_id)


def _fetch_channel_rss(channel_id: str, *, retries: int = 2) -> list[VideoDataclass]:
    """Fetch recent videos from the YouTube channel RSS feed.

    YouTube provides an RSS feed at /feeds/videos.xml?channel_id=UC...
    that returns the 15 most recent videos with ISO 8601 publish dates.
    This is much faster than yt-dlp flat extraction (~0.5s vs ~5s) and
    doesn't require a YouTube Data API key. The RSS feed also returns
    more recent videos than yt-dlp's bypass-mode flat extraction, which
    can miss the latest uploads.

    Args:
        channel_id: Canonical YouTube channel ID (UC...).
        retries: Number of retry attempts on failure (default 2).

    Returns:
        List of VideoDataclass entries (newest first). Empty list if the
        feed is unavailable.
    """
    import time
    import urllib.request
    import xml.etree.ElementTree as ET

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read().decode("utf-8")
            root = ET.fromstring(xml_data)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt": "http://www.youtube.com/xml/schemas/2015",
            }
            out: list[VideoDataclass] = []
            for entry in root.findall("atom:entry", ns):
                vid_elem = entry.find("yt:videoId", ns)
                title_elem = entry.find("atom:title", ns)
                pub_elem = entry.find("atom:published", ns)
                link_elem = entry.find("atom:link", ns)
                if vid_elem is None or pub_elem is None:
                    continue
                vid_id = vid_elem.text or ""
                link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                out.append(
                    VideoDataclass(
                        id=vid_id,
                        channel_id=channel_id,
                        title=(title_elem.text or "") if title_elem is not None else vid_id,
                        published_at=pub_elem.text or "",
                        duration_seconds=None,
                        webpage_url=link or f"https://www.youtube.com/watch?v={vid_id}",
                    )
                )
            return out
        except Exception as exc:
            last_exc = exc
            # Reason: brief delay before retry to avoid hammering YouTube
            # when the RSS endpoint is temporarily rate-limited.
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    logger.debug("RSS feed fetch failed for channel %s after %d retries: %s", channel_id, retries, last_exc)
    return []


def _fetch_video_metadata(
    video_ids: list[str],
    *,
    limit: int | None = None,
    max_workers: int = 5,
) -> dict[str, dict[str, Any]]:
    """Fetch metadata for a list of video IDs.

    Tries the YouTube Data API v3 first if ``STREAMDOC_YOUTUBE_API_KEY`` is
    configured, then falls back to yt-dlp full extraction. The returned
    metadata includes ``published_at`` (YYYYMMDD or ISO 8601),
    ``duration_seconds``, and ``webpage_url``.

    Args:
        video_ids: List of YouTube video IDs.
        limit: Optional cap on how many IDs to fetch.
        max_workers: Maximum number of concurrent yt-dlp calls.

    Returns:
        Dict mapping video ID -> dict with ``published_at`` (str | None),
        ``duration_seconds`` (int | None), and ``webpage_url`` (str | None).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ids = video_ids[:limit] if limit is not None else list(video_ids)
    if not ids:
        return {}

    metadata: dict[str, dict[str, Any]] = {}

    # --- Phase 1: Try YouTube Data API v3 if an API key is configured ---
    api_key = settings.youtube_api_key
    if api_key:
        logger.info("Fetching metadata for %d video(s) via YouTube Data API", len(ids))
        api_meta = _fetch_video_metadata_from_api(ids, api_key)
        for vid_id, meta in api_meta.items():
            # Reason: API doesn't return webpage_url; construct the canonical watch URL.
            metadata[vid_id] = {
                "published_at": meta.get("published_at"),
                "duration_seconds": meta.get("duration_seconds"),
                "webpage_url": f"https://www.youtube.com/watch?v={vid_id}",
                "title": meta.get("title"),
            }
        if len(metadata) >= len(ids):
            return metadata
        remaining = [vid_id for vid_id in ids if vid_id not in metadata]
        ids = remaining

    if not ids:
        return metadata

    # --- Phase 2: Fallback to yt-dlp full extraction ---
    # Reason: build opts for individual video extraction — NOT flat mode,
    # because we need the full metadata. Reuse the central build_ydl_opts
    # so cookies, PO-token, user-agent, and extra args are applied.
    opts = build_ydl_opts(extract_flat=False, dump_single_json=False, playlistend=len(ids))

    def _fetch_one(vid_id: str) -> tuple[str, dict[str, Any]]:
        """Fetch metadata for a single video."""
        import yt_dlp  # type: ignore[import-untyped]
        url = f"https://www.youtube.com/watch?v={vid_id}"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                return (vid_id, {
                    "published_at": str(info.get("upload_date") or info.get("release_date") or ""),
                    "duration_seconds": int(info.get("duration")) if info.get("duration") else None,
                    "webpage_url": info.get("webpage_url") or info.get("url") or url,
                    "title": info.get("title"),
                })
        except Exception as exc:
            logger.debug("Failed to fetch metadata for %s: %s", vid_id, exc)
        return (vid_id, {})

    logger.info("Fetching metadata for %d video(s) via yt-dlp (%d workers)", len(ids), max_workers)
    try:
        # Reason: each thread creates its own YoutubeDL instance because
        # yt-dlp's YoutubeDL is not guaranteed thread-safe. The opts dict
        # is shared (read-only) across threads.
        with ThreadPoolExecutor(max_workers=min(max_workers, len(ids))) as pool:
            futures = {pool.submit(_fetch_one, vid_id): vid_id for vid_id in ids}
            for fut in as_completed(futures):
                vid_id, meta = fut.result()
                if meta:
                    metadata[vid_id] = meta
    except Exception as exc:
        logger.debug("Concurrent metadata fetching failed: %s — falling back to sequential", exc)
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                for vid_id in ids:
                    try:
                        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid_id}", download=False)
                        if info:
                            metadata[vid_id] = {
                                "published_at": str(info.get("upload_date") or info.get("release_date") or ""),
                                "duration_seconds": int(info.get("duration")) if info.get("duration") else None,
                                "webpage_url": info.get("webpage_url") or info.get("url") or f"https://www.youtube.com/watch?v={vid_id}",
                                "title": info.get("title"),
                            }
                    except Exception:
                        pass
        except Exception:
            pass
    return metadata


def _fetch_video_upload_dates(videos: list[VideoDataclass], limit: int = 15, max_workers: int = 5) -> dict[str, str]:
    """Fetch upload dates for videos that don't have them.

    Convenience wrapper around ``_fetch_video_metadata`` that returns only
    the upload date. Kept for backwards compatibility with callers that
    only need ``published_at``.

    Args:
        videos: List of videos to check for missing dates.
        limit: Maximum number of undated videos to fetch dates for.
        max_workers: Maximum number of concurrent yt-dlp calls.

    Returns:
        Dict mapping video ID -> upload_date string (YYYYMMDD from yt-dlp
        or ISO 8601 from the API).
    """
    undated = [v for v in videos if not v.published_at][:limit]
    if not undated:
        return {}

    metadata = _fetch_video_metadata([v.id for v in undated], limit=limit, max_workers=max_workers)
    return {
        vid_id: meta["published_at"]
        for vid_id, meta in metadata.items()
        if meta.get("published_at")
    }


def _list_videos(ch: Channel, *, playlist_mode: bool = False, max_videos: int | None = None) -> list[VideoDataclass]:
    """List videos for a channel or playlist.

    For channels (non-playlist mode), uses the YouTube RSS feed as the
    primary source — it's fast (~0.5s), returns the 15 most recent videos
    with accurate publish dates, and doesn't require an API key. If more
    than 15 videos are needed, falls back to yt-dlp flat extraction for
    the rest (older videos without dates, likely filtered out by cutoff).

    For playlists, uses yt-dlp flat extraction only (RSS feeds don't
    support playlists).

    Args:
        ch: Channel dataclass with id and title.
        playlist_mode: If True, treat the channel ID as a playlist URL directly.
        max_videos: Cap the number of entries returned.

    Returns:
        List of VideoDataclass entries (newest first).
    """
    from streamdoc.core.channel import _ensure_youtube_url

    yt_url = _ensure_youtube_url(ch.id)
    is_playlist = "/playlist?list=" in yt_url or playlist_mode

    # --- Channel mode: use RSS feed as primary source ---
    if not is_playlist:
        rss_videos = _fetch_channel_rss(ch.id)
        if rss_videos:
            # Reason: RSS gives us 15 videos with dates. If max_videos
            # is set and we need more, supplement with flat extraction.
            # But for most date-filtered use cases, 15 recent videos is
            # sufficient — older videos from flat extraction would be
            # filtered out by the lookback cutoff anyway.
            if max_videos and len(rss_videos) < max_videos:
                extra = _list_videos_flat(ch, max_videos=max_videos)
                # Reason: merge flat-extracted videos that aren't already
                # in the RSS list (dedup by video ID)
                seen_ids = {v.id for v in rss_videos}
                for v in extra:
                    if v.id not in seen_ids:
                        rss_videos.append(v)
                        seen_ids.add(v.id)
            return rss_videos[:max_videos] if max_videos else rss_videos
        # Reason: RSS feed failed — fall back to flat extraction
        logger.warning("RSS feed unavailable for channel %s, falling back to yt-dlp", ch.id)

    # --- Playlist mode or RSS fallback: use yt-dlp flat extraction ---
    return _list_videos_flat(ch, max_videos=max_videos, playlist_mode=playlist_mode)


def _list_videos_flat(ch: Channel, *, max_videos: int | None = None, playlist_mode: bool = False) -> list[VideoDataclass]:
    """List videos using yt-dlp flat extraction, with date backfill.

    Flat extraction is fast but does not include ``upload_date`` for
    channel listings. After extraction, this function backfills missing
    dates by fetching each video's metadata individually via yt-dlp
    (limited to the first 15 undated videos to avoid excessive API calls).

    Reason: without date backfill, all flat-extracted videos get epoch
    (1970-01-01) from ``_parse_published`` and are filtered out by the
    lookback cutoff — causing the regression where no videos are
    processed even though the channel has recent uploads.

    Args:
        ch: Channel dataclass with id and title.
        max_videos: Cap the number of entries returned.
        playlist_mode: If True, treat the channel ID as a playlist URL.

    Returns:
        List of VideoDataclass entries with publish dates backfilled
        where possible. Videos whose dates could not be fetched retain
        empty ``published_at`` (treated as epoch by ``_parse_published``).
    """
    import yt_dlp

    from streamdoc.core.channel import _ensure_youtube_url

    yt_url = _ensure_youtube_url(ch.id)
    is_playlist = "/playlist?list=" in yt_url or playlist_mode

    if not is_playlist and ("/@" in yt_url or "/channel/" in yt_url):
        yt_url = yt_url.rstrip("/") + "/videos"

    limit = max_videos if max_videos else 100
    ydl_opts = build_ydl_opts(playlistend=limit)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(yt_url, download=False)
    if info is None:
        return []

    entries = info.get("entries") or []
    out: list[VideoDataclass] = []
    for e in entries:
        if e is None:
            continue
        vid_id = str(e.get("id"))
        published = str(e.get("upload_date") or e.get("release_date") or "")
        out.append(
            VideoDataclass(
                id=vid_id,
                channel_id=ch.id,
                title=str(e.get("title") or e.get("id")),
                published_at=published,
                duration_seconds=(int(e.get("duration")) if e.get("duration") else None),
                webpage_url=e.get("url") or e.get("webpage_url"),
            )
        )

    # Reason: backfill missing publish dates by fetching each video's
    # metadata individually. Flat extraction returns videos in newest-first
    # order, so the first 15 undated videos are the most recent ones.
    undated = [v for v in out if not v.published_at]
    if undated:
        date_limit = min(len(undated), max_videos or 15)
        dates = _fetch_video_upload_dates(out, limit=date_limit)
        if dates:
            backfilled = []
            for v in out:
                if not v.published_at and v.id in dates:
                    # Reason: replace with the fetched date so the cutoff
                    # filter can correctly include recent videos.
                    backfilled.append(
                        VideoDataclass(
                            id=v.id,
                            channel_id=v.channel_id,
                            title=v.title,
                            published_at=dates[v.id],
                            duration_seconds=v.duration_seconds,
                            webpage_url=v.webpage_url,
                        )
                    )
                else:
                    backfilled.append(v)
            out = backfilled
            logger.info("Backfilled upload dates for %d/%d undated video(s)", len(dates), len(undated))

    return out


def _is_playlist_url(url: str) -> bool:
    """Return True if the URL is a YouTube playlist URL."""
    return "/playlist?list=" in url or "&list=" in url


def _parse_published(value: str) -> datetime:
    """Parse a published-at timestamp string.

    Handles multiple formats:
      - ISO 8601 with timezone: 2026-06-29T19:34:57+00:00
      - ISO 8601 with Z suffix:  2026-06-29T19:34:57Z
      - yt-dlp YYYYMMDD format:  20260629

    Falls back to epoch (1970-01-01) on failure so unparseable dates are
    treated as *old* rather than *recent*, preventing them from sneaking
    past the lookback window.

    Args:
        value: Date string from yt-dlp, RSS feed, or API.

    Returns:
        Timezone-aware datetime in UTC.
    """
    try:
        if not value:
            return datetime(1970, 1, 1, tzinfo=UTC)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        # Reason: yt-dlp's YYYYMMDD format parses as a naive datetime.
        # We must attach UTC timezone before comparing with the
        # timezone-aware cutoff, otherwise Python raises TypeError.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        # Reason: unparseable dates should NOT be treated as recent
        return datetime(1970, 1, 1, tzinfo=UTC)


def _is_processed(video_id: str) -> bool:
    with session_scope() as s:
        existing = s.get(VideoModel, video_id)
        if not existing:
            return False
        # Reason: only "ready" means fully processed. Failed statuses should
        # be retried. "restricted" means a permanent download failure
        # (members-only, private, deleted, age/region-blocked) that can
        # never succeed — skip it permanently to avoid wasting time.
        if str(existing.output_status or "") == "ready":
            return True
        if str(existing.media_status or "") == "restricted":
            return True
        return False


def _is_short(v: VideoDataclass) -> bool:
    """Return True if the video should be treated as a YouTube Short.

    Shorts are detected by:
      - The canonical URL containing ``/shorts/`` (yt-dlp sets this for
        Shorts from the channel ``videos`` tab).
      - The video duration being at or below ``STREAMDOC_SHORTS_MAX_SECONDS``.
      - The global ``STREAMDOC_SKIP_SHORTS`` setting being enabled.

    Args:
        v: Video dataclass to evaluate.

    Returns:
        True if the video should be skipped, False otherwise.
    """
    if not settings.skip_shorts:
        return False
    if v.webpage_url and "/shorts/" in v.webpage_url:
        return True
    if v.duration_seconds is not None and v.duration_seconds <= settings.shorts_max_seconds:
        return True
    return False


def _download_media(v: VideoDataclass) -> DownloadResult:
    """Download media for a video via yt-dlp, with error classification.

    Args:
        v: Video dataclass to download.

    Returns:
        DownloadResult with the media path on success, or an error
        category on failure. Permanent errors (members-only, private,
        deleted) are classified so the caller can mark the video as
        permanently skipped instead of retrying on every run.
    """
    out_dir = Path(settings.media_root) / v.channel_id / v.id
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "%(id)s.%(ext)s")
    try:
        result = _yt_dlp_download(url=v.webpage_url or v.id, output_template=template)
    except Exception as exc:
        err_msg = str(exc)
        category = classify_download_error(err_msg)
        logger.error("yt-dlp download failed for %s [%s]: %s", v.id, category, err_msg)
        return DownloadResult(error=err_msg, error_category=category)
    if result.returncode != 0:
        err_msg = result.stderr or result.stdout or f"yt-dlp exited {result.returncode}"
        category = classify_download_error(err_msg)
        logger.error("yt-dlp failed for %s [%s]: %s", v.id, category, err_msg)
        return DownloadResult(error=err_msg, error_category=category)
    candidates = list(out_dir.glob(f"{v.id}.*"))
    if not candidates:
        logger.error("Download output missing for %s", v.id)
        return DownloadResult(error="Download output missing", error_category="other")
    return DownloadResult(path=sorted(candidates)[0])


def _get_transcript(media_path: Path, video_id: str) -> list[dict[str, Any]]:
    """Fetch transcript: official API first, then Whisper fallback."""
    try:
        items = fetch_transcript(video_id)
        if items:
            logger.info("Official transcript found for video: %s (%d segments)", video_id, len(items))
            return items
        logger.info("No official transcript for video: %s, falling back to Whisper", video_id)
    except Exception as exc:
        logger.info("Official transcript unavailable for %s: %s — falling back to Whisper", video_id, exc)
    wav = media_path.with_suffix(".wav")
    if not wav.exists():
        try:
            logger.info("Converting audio to WAV for Whisper transcription: %s", video_id)
            wav = fallback_audio_to_wav(media_path, wav)
        except Exception as exc:
            logger.error("Audio conversion failed for %s: %s", video_id, exc)
            return []
    try:
        logger.info("Starting Whisper transcription for video: %s", video_id)
        return transcribe_audio(wav)
    except Exception as exc:
        logger.error("Whisper transcription failed for %s: %s", video_id, exc)
        return []


def _send_to_notebooklm(md_path: Path, preset: Preset) -> bool:
    """Upload markdown report to NotebookLM if enabled and configured.

    Args:
        md_path: Path to the generated markdown report.
        preset: Preset object with notebooklm_kind and other settings.

    Returns:
        True if upload succeeded.

    Raises:
        RuntimeError: If NotebookLM is disabled, not authenticated, or upload fails.
    """
    from streamdoc.config import settings

    if not settings.notebooklm_enabled:
        raise RuntimeError("NotebookLM integration is disabled")

    # Reason: skip upload if preset doesn't request notebooklm content generation
    if not preset.notebooklm_kind:
        raise RuntimeError("NotebookLM content type not selected for this preset")

    from streamdoc.core.notebooklm_upload import upload_to_notebooklm

    # Map notebooklm_kind to content type for per-video upload
    content_types = []
    kind = (preset.notebooklm_kind or "").lower().strip()
    if kind:
        try:
            content_types = [ContentType(kind)]
        except ValueError:
            logger.warning("Unknown notebooklm_kind=%s", kind)

    # Reason: upload_to_notebooklm is async but _process_video is sync,
    # so we run it via the shared event loop for thread safety.
    # Prompt resolution: template name > custom prompt (prompt_md) > default
    from streamdoc.async_utils import run_async
    prompt_args = _notebooklm_prompt_args(preset)
    result = run_async(
        upload_to_notebooklm(
            report_paths=[md_path],
            preset_name=preset.name,
            content_types=content_types if content_types else None,
            prompt_template=prompt_args["prompt_template"],
            custom_prompt=prompt_args["custom_prompt"],
            design_prompt=_design_prompt_for_preset(
                preset,
                content_types[0] if content_types else ContentType.REPORT,
            ),
            retry_generation=getattr(preset, "notebooklm_retry_failed", True),
            retry_attempts=getattr(preset, "notebooklm_retry_attempts", 1),
            retry_delay=(getattr(preset, "notebooklm_retry_delay_minutes", 5.0) or 5.0) * 60,
        )
    )

    if not result.success:
        raise RuntimeError("; ".join(result.errors) if result.errors else "Upload failed")

    logger.info("NotebookLM upload succeeded for %s (notebook: %s)", md_path.name, result.notebook_id)
    return True
