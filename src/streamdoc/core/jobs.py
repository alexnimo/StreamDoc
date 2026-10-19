"""Job tracking, retry, and resend for external destinations.

Every preset run creates a Job record. Failed sends can be retried,
and successful jobs can be resent to additional destinations.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from streamdoc.db import session_scope
from streamdoc.models.job import Job as JobModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_loads(text: str, default: Any = None) -> Any:
    """Parse a JSON string, returning ``default`` when empty or invalid.

    Args:
        text: JSON-encoded string from a DB column.
        default: Value to return when ``text`` is empty/invalid. If None,
            defaults to ``[]`` (preserves historical behavior for list
            columns). Callers expecting a dict should pass ``{}``.

    Returns:
        Parsed Python object, or ``default``.
    """
    # Reason: the previous logic `{} if text == "{}" else []` was dead code —
    # an empty string is never equal to "{}", so dict columns silently got
    # `[]` and broke Pydantic validation (e.g. JobOut.details).
    fallback = [] if default is None else default
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return fallback


# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------

def create_job(preset_name: str) -> str:
    """Create a new Job record and return its ID."""
    job_id = str(uuid.uuid4())[:8]
    with session_scope() as session:
        job = JobModel(
            id=job_id,
            preset_name=preset_name,
            status="running",
            created_at=_now_iso(),
            artifact_count=0,
            report_paths="[]",
            destinations="{}",
            errors="[]",
        )
        session.add(job)
    logger.info("Created job %s for preset=%s", job_id, preset_name)
    return job_id


def complete_job(
    job_id: str,
    artifacts: list[Any],
    destination_results: dict[str, str],
) -> None:
    """Update a Job record after the run finishes.

    Args:
        job_id: The job to update.
        artifacts: All RunArtifacts produced in this run.
        destination_results: Dict of destination name -> result string.
    """
    report_paths: list[str] = []
    for a in artifacts:
        md = getattr(a, "md_path", None)
        pdf = getattr(a, "pdf_path", None)
        if md:
            report_paths.append(str(md))
        if pdf:
            report_paths.append(str(pdf))

    # Determine status
    # Reason: destination values can be:
    #   - "success" → upload succeeded
    #   - "pending" / "in_progress" → async generation still running
    #   - "error: ..." → actual error
    #   - a file path (e.g. "data\Outputs\...\slide_deck.pdf") → downloaded
    #     content, which is a SUCCESS, not an error
    #   - a list of strings (notebooklm_errors) → actual errors
    # The previous logic treated ANY non-success, non-pending string as an
    # error, which incorrectly classified file paths as errors and caused
    # the job to be marked "partial" even when everything succeeded.
    errors = []
    for msg in destination_results.values():
        # Reason: some values may be lists (e.g. notebooklm_errors) —
        # flatten them into individual error strings.
        if isinstance(msg, list):
            errors.extend(str(m) for m in msg)
        elif isinstance(msg, str):
            # Reason: only treat explicit error messages as errors.
            # File paths, "success", "pending", and "in_progress" are NOT errors.
            if msg.startswith("error"):
                errors.append(msg)
    # Reason: has_success is True when any destination succeeded — either
    # explicitly ("success") or implicitly (a file path means content was
    # downloaded successfully). Artifacts produced during the run also count
    # as a success so a job whose uploads fail but whose reports were built
    # is marked "partial" rather than "failed".
    has_success = any(
        isinstance(msg, str) and (msg.startswith("success") or msg.startswith("pending") or not msg.startswith("error"))
        for msg in destination_results.values()
    ) or (len(artifacts) > 0)
    if not errors:
        status = "completed"
    elif has_success:
        status = "partial"
    else:
        status = "failed"

    # Build rich details from artifacts
    videos = []
    total_duration = 0
    total_frames = 0
    total_words = 0
    for a in artifacts:
        if getattr(a, "error", None):
            continue
        videos.append({
            "video_id": getattr(a, "video_id", ""),
            "title": getattr(a, "title", ""),
            "channel_title": getattr(a, "channel_title", ""),
            "duration_seconds": getattr(a, "duration_seconds", None),
            "frame_count": getattr(a, "frame_count", 0),
            "transcript_word_count": getattr(a, "transcript_word_count", 0),
        })
        total_duration += getattr(a, "duration_seconds", 0) or 0
        total_frames += getattr(a, "frame_count", 0) or 0
        total_words += getattr(a, "transcript_word_count", 0) or 0

    details = {
        "videos": videos,
        "stats": {
            "total_videos": len(videos),
            "total_duration_seconds": total_duration,
            "total_frames": total_frames,
            "total_transcript_words": total_words,
        },
        "artifacts": [
            {
                "video_id": getattr(a, "video_id", ""),
                "title": getattr(a, "title", ""),
                "md_path": str(getattr(a, "md_path", "")) if getattr(a, "md_path", None) else None,
                "pdf_path": str(getattr(a, "pdf_path", "")) if getattr(a, "pdf_path", None) else None,
                "status": getattr(a, "status", ""),
            }
            for a in artifacts
        ],
        "integrations": {
            k: v for k, v in destination_results.items()
        },
    }

    # Reason: attach NotebookLM generation statuses from the DB so the
    # frontend can show pending/completed/failed async generations.
    try:
        from streamdoc.models.generation import Generation as GenModel
        with session_scope() as gen_s:
            gens = gen_s.query(GenModel).filter(GenModel.job_id == job_id).all()
            if gens:
                details["generations"] = [
                    {
                        "id": g.id,
                        "content_type": g.content_type,
                        "status": g.status,
                        "local_path": g.local_path if g.local_path else None,
                        "error": g.error if g.error else None,
                        "notebook_id": g.notebook_id,
                    }
                    for g in gens
                ]
    except Exception as exc:
        logger.debug("Failed to load generations for job %s: %s", job_id, exc)

    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if not job:
            logger.warning("Job %s not found for completion", job_id)
            return
        job.status = status
        job.completed_at = _now_iso()
        job.artifact_count = len(artifacts)
        job.report_paths = _json_dumps(report_paths)
        job.destinations = _json_dumps(destination_results)
        job.errors = _json_dumps(errors)
        job.details = _json_dumps(details)
    logger.info(
        "Completed job %s status=%s artifacts=%s destinations=%s",
        job_id, status, len(artifacts), destination_results,
    )


def fail_job(job_id: str, error: str) -> None:
    """Mark a job as failed with an error message.

    Args:
        job_id: The job to fail.
        error: Error message describing the failure.
    """
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if not job:
            logger.warning("Job %s not found for failure", job_id)
            return
        job.status = "failed"
        job.completed_at = _now_iso()
        job.errors = _json_dumps([error])
    logger.info("Failed job %s: %s", job_id, error)


# ---------------------------------------------------------------------------
# Retry / Resend
# ---------------------------------------------------------------------------

# Destination keys that represent an actual send target. Everything else in
# the destinations dict is metadata produced by a send (share URLs, local
# artifact paths, pending markers, error lists like ``notebooklm_errors`` /
# ``agy_errors``, ``notebooklm_id``) and must never be sent to
# ``_send_to_destination`` — a retry would try "Unknown destination" for each
# metadata key and overwrite the real error, and non-string values (error
# lists) crash ``str.startswith`` outright.
_SEND_DESTINATIONS = ("notebooklm", "agy")

def retry_job(job_id: str) -> dict[str, str]:
    """Retry all destinations that previously failed for a job.

    Returns:
        Dict of destination -> result (success or error message).
    """
    return _execute_job(job_id, new_destinations=None)


def resend_job(job_id: str, destination: str) -> dict[str, str]:
    """Send a job's reports to a new destination.

    Args:
        job_id: Existing job to resend.
        destination: Name of the new destination (e.g. "notebooklm").

    Returns:
        Dict of destination -> result.
    """
    return _execute_job(job_id, new_destinations=[destination])


def _execute_job(
    job_id: str,
    new_destinations: list[str] | None,
) -> dict[str, str]:
    """Internal executor for retry/resend."""
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        report_paths = _json_loads(job.report_paths)
        existing = _json_loads(job.destinations, default={})
        # Reason: read preset_name inside the session — commit() expires all
        # attributes, so accessing job.* afterwards raises DetachedInstanceError.
        preset_name = job.preset_name

    # Verify files still exist
    missing: list[str] = []
    valid_paths: list[Path] = []
    for p in report_paths:
        path = Path(p)
        if path.exists():
            valid_paths.append(path)
        else:
            missing.append(p)

    if missing:
        logger.warning("Job %s: %s report files are missing (retention expired?)", job_id, len(missing))

    if not valid_paths:
        raise RuntimeError(
            f"Job {job_id}: no report files available. They may have been deleted by retention policy."
        )

    # Determine which destinations to attempt
    destinations_to_try: list[str] = []
    if new_destinations:
        destinations_to_try = [
            d for d in new_destinations if d in _SEND_DESTINATIONS
        ]
    else:
        # Retry: only real send destinations that did NOT succeed previously.
        # Metadata keys (urls, paths, *_errors lists) are filtered by the
        # whitelist; non-string values are guarded so a list can't crash the
        # startswith check.
        for dest, result in existing.items():
            if dest not in _SEND_DESTINATIONS:
                continue
            if not isinstance(result, str) or not result.startswith("success"):
                destinations_to_try.append(dest)

    if not destinations_to_try:
        logger.info("Job %s: nothing to retry/resend", job_id)
        return {}

    # Reason: mark the job running + each attempted destination in_progress
    # BEFORE starting. Retried sends run for minutes (NotebookLM upload +
    # generation with internal 300s retry delays); until now the row kept
    # showing the old "failed" status and stale error for the whole window,
    # which is what made retry look dead. The "in_progress" value also
    # triggers the UI's 30s pending-poll.
    def _emit(msg: str, step: str = "upload", status: str = "running",
              progress: float | None = None) -> None:
        try:
            from streamdoc.api.sse import emit_progress
            emit_progress(job_id, step=step, message=msg, progress=progress, status=status)
        except Exception:  # noqa: BLE001
            pass

    verb = "Resending" if new_destinations else "Retrying"
    _emit(f"{verb} job reports to {', '.join(destinations_to_try)}...", progress=90)
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if job:
            job.status = "running"
            # Reason: clear the errors column too — otherwise the previous
            # failure stays displayed next to the new "running" state for
            # the entire retry (potentially minutes), looking like nothing
            # changed.
            job.errors = _json_dumps([])
            # Reason: purge the PREVIOUS run's per-destination metadata for
            # every attempted destination (old notebooklm_url, per-type
            # errors/paths, *_errors lists). Those keys described the failed
            # run — while the retry runs they showed a second, stale error
            # message that contradicted the errors column. notebooklm_id is
            # kept: the send path reads it to resume generation on the same
            # notebook.
            marked = {
                k: v for k, v in existing.items()
                if not any(
                    k.startswith(f"{dest}_") and k != f"{dest}_id"
                    for dest in destinations_to_try
                )
            }
            for dest in destinations_to_try:
                marked[dest] = "in_progress"
            job.destinations = _json_dumps(marked)

    # Attempt sends
    results: dict[str, str] = {}
    extras_merged: dict[str, Any] = {}
    for dest in destinations_to_try:
        _emit(f"Sending to {dest}...", progress=92)
        try:
            extra = _send_to_destination(dest, valid_paths, preset_name=preset_name, job_id=job_id)
            results[dest] = "success"
            if isinstance(extra, dict):
                extras_merged.update(extra)
            _emit(f"{dest}: send succeeded", progress=97)
        except Exception as exc:
            err = f"error: {exc}"
            results[dest] = err
            _emit(f"{dest}: send failed — {exc}", status="running")
            logger.warning("Send to %s failed for job %s: %s", dest, job_id, exc)

    # Merge results over the marked (stale-purged) destinations.
    merged = {**marked, **results, **extras_merged}
    # Reason: only treat explicit error messages as errors — file paths
    # and other non-error strings are successful results.
    errors = [
        msg for msg in merged.values()
        if isinstance(msg, str) and msg.startswith("error")
    ]
    has_success = any(
        isinstance(v, str) and not v.startswith("error")
        for v in merged.values()
    )
    status = "completed" if not errors else ("partial" if has_success else "failed")

    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if job:
            job.destinations = _json_dumps(merged)
            job.errors = _json_dumps(errors)
            job.status = status

    logger.info("Job %s retry/resend results: %s", job_id, results)
    # Terminal event closes the SSE stream → the UI's isDone flips and
    # reloads the job row, showing the updated destinations immediately
    # instead of waiting for the 30s poll.
    _emit(
        f"{verb} finished: {status}",
        step="complete",
        status="completed" if status != "failed" else "failed",
        progress=100,
    )
    try:
        from streamdoc.api.sse import sse_manager
        sse_manager.complete(job_id)
    except Exception:  # noqa: BLE001
        pass
    return results


def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel a running job by marking it as failed.

    Args:
        job_id: The job to cancel.

    Returns:
        Dict with cancellation status.
    """
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")
        if job.status not in ("running",):
            raise ValueError(f"Job '{job_id}' is not running (status={job.status})")
        job.status = "failed"
        job.completed_at = _now_iso()
        job.errors = _json_dumps(["Cancelled by user"])
    logger.info("Cancelled job %s", job_id)
    return {"status": "cancelled", "job_id": job_id}


def cleanup_stale_jobs() -> int:
    """Mark all jobs stuck in 'running' state as failed.

    This should be called on application startup to clean up jobs from
    previous sessions that were interrupted.

    Returns:
        Number of stale jobs cleaned up.
    """
    count = 0
    with session_scope() as session:
        stale = session.query(JobModel).filter(JobModel.status == "running").all()
        for job in stale:
            job.status = "failed"
            job.completed_at = _now_iso()
            job.errors = _json_dumps(["Stale job — interrupted by server restart"])
            count += 1
    if count:
        logger.info("Cleaned up %d stale running jobs", count)
    return count


# ---------------------------------------------------------------------------
# Destination send (placeholder for actual integrations)
# ---------------------------------------------------------------------------

def _progress_cb_for_job(job_id: str):
    """Return a progress callback that relays stage messages to SSE.

    Wired into upload_to_notebooklm → batch_generate → generate_content so
    the multi-minute generation/retry-delay waits show up in the live
    progress bar instead of only in logs.
    """
    def _cb(msg: str) -> None:
        try:
            from streamdoc.api.sse import emit_progress
            emit_progress(job_id, step="upload", message=msg, progress=94, status="running")
        except Exception:  # noqa: BLE001
            pass
    return _cb



def _send_to_destination(destination: str, paths: list[Path], preset_name: str = "", job_id: str = "") -> dict[str, Any]:
    """Send files to an external destination.

    Args:
        destination: Destination identifier (e.g. "notebooklm").
        paths: Report files to send.
        preset_name: Preset name for NotebookLM content generation.
        job_id: Job ID for tracking.

    Raises:
        RuntimeError: If the destination is not configured or the send fails.

    Returns:
        Dict of destination-metadata extras (share URL, artifact paths,
        per-type statuses) produced by a successful send, for the caller to
        merge over the stale keys from the failed run.
    """
    if destination == "notebooklm":
        from streamdoc.core.notebooklm_upload import upload_to_notebooklm
        from streamdoc.integrations.notebooklm import ContentType
        from streamdoc.db import session_scope
        from streamdoc.models.preset import Preset as PresetModel

        # Load preset to get notebooklm_kind, prompt template, and retention settings
        notebooklm_kind = ""
        notebook_retention_hours = None
        retention_enabled = True
        prompt_template = None
        design_prompt_template = None
        # Reason: custom_prompt must be initialized outside the nested
        # `if p:` — a missing preset row used to leave it unbound and crash
        # the send with UnboundLocalError.
        custom_prompt = None
        if preset_name:
            with session_scope() as session:
                p = session.get(PresetModel, preset_name)
                if p:
                    notebooklm_kind = (p.notebooklm_kind or "").lower().strip()
                    notebook_retention_hours = getattr(p, "notebook_retention_hours", None)
                    retention_enabled = getattr(p, "retention_enabled", True)
                    # Reason: use the preset's prompt template if set; otherwise
                    # use the preset's prompt_md as a custom prompt. Only fall
                    # back to settings.notebooklm_default_prompt when neither is
                    # set (handled in upload_to_notebooklm).
                    prompt_template = getattr(p, "notebooklm_prompt_template", None) or None
                    custom_prompt = (getattr(p, "prompt_md", "") or "").strip() or None
                    design_prompt_template = getattr(p, "design_prompt_template", None)

        content_types = []
        if notebooklm_kind:
            try:
                content_types = [ContentType(notebooklm_kind)]
            except ValueError:
                pass

        from streamdoc.core.fetch import _design_prompt_for_preset
        preset_shim = SimpleNamespace(design_prompt_template=design_prompt_template)
        # Reason: lightweight shim to avoid detached-instance attribute access
        # after the DB session closes; _design_prompt_for_preset only reads
        # design_prompt_template.
        design_prompt = _design_prompt_for_preset(
            preset_shim, content_types[0] if content_types else ContentType.REPORT  # type: ignore[arg-type]
        )

        # Reason: when the previous attempt got the notebook created and
        # sources uploaded but generation failed, resume generation on the
        # SAME notebook — re-uploading into a fresh notebook orphans the old
        # one and doubles the source-upload quota. notebooklm_id is stored
        # by _send_reports only when sources made it up, so reuse is safe.
        resume_notebook_id = None
        if job_id:
            try:
                with session_scope() as _s:
                    _j = _s.get(JobModel, job_id)
                    _existing = _json_loads(_j.destinations, default={}) if _j else {}
                if _existing.get("notebooklm_id"):
                    _prev_err = _existing.get("notebooklm", "")
                    if isinstance(_prev_err, str) and "failed to upload" not in _prev_err.lower():
                        resume_notebook_id = _existing["notebooklm_id"]
            except Exception as _e:
                logger.debug("NotebookLM resume lookup failed for job %s: %s", job_id, _e)

        from streamdoc.async_utils import run_async
        # Reason: notebooklm_kind is a content type (e.g. "slide_deck"), NOT a
        # prompt template name. The content type is conveyed via content_types.
        # Prompt resolution: template name > custom prompt (prompt_md) > default.
        # Reason: use run_async for thread safety when multiple jobs run in parallel.
        # Reason: pass the preset's notebook_retention_hours so retried/resent
        # notebooks get the same retention policy as the original run. When
        # retention is disabled, mark as permanent.
        result = run_async(upload_to_notebooklm(
            report_paths=paths,
            preset_name=preset_name or "unknown",
            job_id=job_id or None,
            notebook_id=resume_notebook_id,
            resume=bool(resume_notebook_id),
            prompt_template=prompt_template,
            custom_prompt=custom_prompt,
            design_prompt=design_prompt,
            retention_hours=notebook_retention_hours,
            is_permanent=not retention_enabled,
            progress_cb=_progress_cb_for_job(job_id),
        ))

        # Reason: return the per-content-type metadata the fetch pipeline
        # records (share URL, artifact paths, per-type errors) so the caller
        # can overwrite the stale keys from the failed run — otherwise the
        # destinations cell keeps showing the old error next to a fresh
        # "success" and the two disagree.
        extras: dict[str, Any] = {"notebooklm_id": result.notebook_id or ""}
        if result.notebook_url:
            extras["notebooklm_url"] = result.notebook_url
        for gc in result.generated_content or []:
            ct_name = gc.content_type.value if hasattr(gc, "content_type") else str(gc.content_type)
            gc_status = getattr(gc, "status", "")
            gc_local = getattr(gc, "local_path", None)
            gc_error = getattr(gc, "error", "")
            if gc_local and Path(gc_local).exists():
                extras[f"notebooklm_{ct_name}"] = str(gc_local)
            elif gc_status == "pending":
                extras[f"notebooklm_{ct_name}"] = "pending"
            elif gc_status == "failed":
                extras[f"notebooklm_{ct_name}"] = (
                    f"error: {gc_error}" if gc_error else "error: generation failed"
                )
        if result.errors:
            extras["notebooklm_errors"] = result.errors

        if not result.success:
            err = "; ".join(result.errors) if result.errors else "Upload failed"
            raise RuntimeError(err)
        return extras
    elif destination == "agy":
            # Use the CLI tool registry to run the agy adapter
            from streamdoc.async_utils import run_async
            from streamdoc.db import session_scope
            from streamdoc.models.preset import Preset as PresetModel
            from streamdoc.integrations.cli_tools import registry as cli_tools_registry

            cli_tool = "agy"
            cli_tool_template = None
            if preset_name:
                with session_scope() as session:
                    p = session.get(PresetModel, preset_name)
                    if p:
                        cli_tool = getattr(p, "cli_tool", None) or "agy"
                        cli_tool_template = getattr(p, "cli_tool_template", None)

            # Resolve and instantiate the tool from registry.
            # Reason: get_tool() returns the tool CLASS; calling .run() on it
            # unbound shifts every arg and fails with
            # "missing 1 required positional argument: 'out_dir'".
            tool = cli_tools_registry.instantiate(cli_tool)
            if tool is None:
                raise RuntimeError(f"CLI tool '{cli_tool}' not registered")

            # Reason: job.report_paths stores BOTH the .md and .pdf of each
            # report. Markdown is the preferred input for CLI harnesses, so
            # drop any .pdf that has a sibling .md — feeding both doubles the
            # agent's input and re-triggers the PDF-extraction dance.
            md_stems = {p.stem for p in paths if p.suffix.lower() == ".md"}
            paths = [
                p for p in paths
                if p.suffix.lower() != ".pdf" or p.stem not in md_stems
            ]

            # Output directory for artifacts
            from streamdoc.config import settings
            out_dir = Path(settings.agy_output_dir) / (preset_name or "unknown")

            # Run the tool
            result = run_async(tool.run(paths, cli_tool_template, out_dir))

            if not result.success:
                err = result.error or "agy tool execution failed"
                raise RuntimeError(err)
            # Reason: mirror the metadata fetch._send_to_agy records so the
            # retry's success cell shows the artifact/link just like the
            # original run — without it the purged agy_* keys stay empty.
            agy_extras: dict[str, Any] = {}
            if getattr(result, "artifact_path", None):
                agy_extras["agy_artifact_path"] = str(result.artifact_path)
            if getattr(result, "herenow_url", None):
                agy_extras["agy_herenow_url"] = result.herenow_url
            claim_url = getattr(result, "herenow_claim_url", None)
            if claim_url:
                agy_extras["agy_herenow_claim_url"] = claim_url
            if getattr(result, "errors", None):
                agy_extras["agy_errors"] = "; ".join(result.errors)
            return agy_extras
    else:
        raise RuntimeError(f"Unknown destination: {destination}")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent jobs as plain dicts."""
    with session_scope() as session:
        rows = (
            session.query(JobModel)
            .order_by(JobModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "preset_name": r.preset_name,
                "status": r.status,
                "created_at": r.created_at,
                "completed_at": r.completed_at,
                "artifact_count": r.artifact_count,
                "destinations": _json_loads(r.destinations, default={}),
                "errors": _json_loads(r.errors),
                "details": _json_loads(r.details, default={}),
            }
            for r in rows
        ]
