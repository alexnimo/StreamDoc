"""Background poller for pending NotebookLM generations.

Checks pending generation records in the database, polls NotebookLM for
their status, and downloads artifacts when they complete.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from typing import TYPE_CHECKING

from streamdoc.config import settings
from streamdoc.db import session_scope
from streamdoc.models.generation import Generation

if TYPE_CHECKING:
    from streamdoc.integrations.notebooklm.content import ContentManager

logger = logging.getLogger(__name__)

# Reason: 30s interval balances responsiveness with API load.
# NotebookLM generation can take 5-15 minutes for large content.
POLL_INTERVAL_SECONDS = 30.0
# Reason: give up after 30 minutes — if it hasn't completed by then,
# something is likely wrong.
MAX_POLL_DURATION_SECONDS = 1800.0


async def poll_pending_generations() -> None:
    """Check all pending generations and download artifacts when ready.

    This function connects to NotebookLM, iterates over all records with
    status='pending', polls their task status, and updates the record
    when the generation completes or fails.
    """
    # Read pending generations from DB
    pending: list[dict] = []
    with session_scope() as s:
        rows = s.query(Generation).filter(
            Generation.status.in_(["pending", "in_progress"])
        ).all()
        for row in rows:
            pending.append({
                "id": row.id,
                "job_id": row.job_id,
                "notebook_id": row.notebook_id,
                "task_id": row.task_id,
                "content_type": row.content_type,
                "created_at": row.created_at,
            })

    if not pending:
        return

    logger.info("Polling %d pending NotebookLM generation(s)", len(pending))

    # Check auth
    from streamdoc.integrations.notebooklm import (
        ContentManager,
        NotebookLMClientWrapper,
        NotebookLMAuthManager,
        PromptManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import (
        NotebookLMAuthRequiredError,
    )

    auth_manager = NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile,
    )

    try:
        await auth_manager.require_auth()
    except NotebookLMAuthRequiredError:
        logger.warning("Cannot poll pending generations — NotebookLM not authenticated")
        return

    prompts = PromptManager(
        settings.notebooklm_templates_dir,
        settings.notebooklm_sample_prompts_dir,
    )

    try:
        async with NotebookLMClientWrapper(auth_manager) as client:
            content_mgr = ContentManager(
                client,
                prompts,
                settings.notebooklm_default_wait_timeout,
            )

            for gen in pending:
                await _poll_single_generation(content_mgr, gen)
    except Exception as exc:
        logger.error("Error polling pending generations: %s", exc, exc_info=True)


async def _poll_single_generation(content_mgr: "ContentManager", gen: dict) -> None:
    """Poll a single pending generation and update its DB record.

    Args:
        content_mgr: ContentManager instance for API calls.
        gen: Generation record dict with id, notebook_id, task_id, content_type.
    """
    gen_id = gen["id"]
    notebook_id = gen["notebook_id"]
    task_id = gen["task_id"]
    content_type_str = gen["content_type"]

    # Reason: check if this generation has been pending too long
    try:
        created = datetime.fromisoformat(gen["created_at"])
    except Exception:
        created = datetime.now(timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
    if age_seconds > MAX_POLL_DURATION_SECONDS:
        logger.warning(
            "Generation %s (task=%s) exceeded max poll duration (%.0fs) — marking as failed",
            gen_id, task_id, age_seconds,
        )
        _update_generation_status(
            gen_id, status="failed",
            error=f"Timed out after {age_seconds:.0f}s",
            job_id=gen.get("job_id", ""),
            content_type=content_type_str,
        )
        return

    try:
        # Poll the task status (non-blocking, just check current status)
        final_status = await content_mgr.client_wrapper.artifacts.wait_for_completion(
            notebook_id,
            task_id,
            timeout=5.0,  # Reason: short timeout — just checking current status
        )

        status_lower = final_status.status.lower()

        if status_lower in ("completed", "ready"):
            # Download the artifact
            from streamdoc.integrations.notebooklm import ContentType

            content_type = ContentType(content_type_str)
            output_dir = Path(settings.output_root) / "notebooklm" / notebook_id
            output_dir.mkdir(parents=True, exist_ok=True)

            local_path = None
            try:
                local_path = await content_mgr.download_content(
                    notebook_id,
                    None,  # Reason: download latest of this type
                    content_type,
                    output_dir,
                )
            except Exception as dl_exc:
                logger.warning("Failed to download artifact for gen %s: %s", gen_id, dl_exc)

            artifact_id = ""
            if final_status.metadata:
                artifact_id = (
                    final_status.metadata.get("artifact_id")
                    or final_status.metadata.get("id")
                    or task_id
                )
            else:
                artifact_id = task_id

            _update_generation_status(
                gen_id,
                status="completed",
                artifact_id=artifact_id,
                local_path=str(local_path) if local_path else "",
                job_id=gen.get("job_id", ""),
                content_type=content_type_str,
            )
            logger.info(
                "Generation %s completed — artifact downloaded to %s",
                gen_id, local_path,
            )

        elif status_lower == "failed":
            error_msg = final_status.error or "Generation failed on NotebookLM"
            _update_generation_status(
                gen_id, status="failed", error=error_msg,
                job_id=gen.get("job_id", ""),
                content_type=content_type_str,
            )
            logger.warning("Generation %s failed: %s", gen_id, error_msg)

        else:
            # Still in progress — update timestamp
            _update_generation_status(gen_id, status="in_progress")
            logger.debug("Generation %s still in progress (status=%s)", gen_id, status_lower)

    except TimeoutError:
        # Reason: expected — the 5s timeout just means it's not done yet
        _update_generation_status(gen_id, status="in_progress")
        logger.debug("Generation %s still in progress (poll timeout)", gen_id)

    except Exception as exc:
        logger.error("Error polling generation %s: %s", gen_id, exc)
        _update_generation_status(gen_id, status="in_progress")


def _update_generation_status(
    gen_id: str,
    status: str,
    artifact_id: str = "",
    local_path: str = "",
    error: str = "",
    job_id: str = "",
    content_type: str = "",
) -> None:
    """Update a generation record in the database.

    Args:
        gen_id: Generation record ID.
        status: New status (pending, in_progress, completed, failed).
        artifact_id: Artifact ID (when completed).
        local_path: Local download path (when completed).
        error: Error message (when failed).
        job_id: Associated job ID (for updating job destinations).
        content_type: Content type string (for building destination key).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with session_scope() as s:
            from streamdoc.models.generation import Generation as GenModel
            row = s.get(GenModel, gen_id)
            if row is None:
                logger.warning("Generation record %s not found in DB", gen_id)
                return
            row.status = status
            row.updated_at = now_iso
            if artifact_id:
                row.artifact_id = artifact_id
            if local_path:
                row.local_path = local_path
            if error:
                row.error = error

            # Reason: also update the job's destinations so the Jobs tab
            # reflects the completed generation. Without this, the job
            # permanently shows "pending" even after the artifact is
            # downloaded.
            if job_id and content_type:
                _update_job_destination(s, job_id, content_type, status, local_path, error)
    except Exception as exc:
        logger.error("Failed to update generation %s status: %s", gen_id, exc)


def _update_job_destination(
    session,
    job_id: str,
    content_type: str,
    status: str,
    local_path: str,
    error: str,
) -> None:
    """Update a job's destinations JSON with the generation result.

    Args:
        session: Active SQLAlchemy session.
        job_id: Job ID to update.
        content_type: Content type (e.g. "slide_deck").
        status: Generation status (completed, failed).
        local_path: Path to downloaded artifact (if completed).
        error: Error message (if failed).
    """
    import json
    from streamdoc.models.job import Job as JobModel

    job = session.get(JobModel, job_id)
    if job is None:
        return

    try:
        dests = json.loads(job.destinations) if job.destinations else {}
    except Exception:
        dests = {}

    dest_key = f"notebooklm_{content_type}"
    if status == "completed" and local_path:
        from pathlib import Path as P
        if P(local_path).exists():
            dests[dest_key] = local_path
        else:
            dests[dest_key] = f"error: downloaded file not found at {local_path}"
    elif status == "failed":
        dests[dest_key] = f"error: {error}" if error else "error: generation failed"
    # Reason: don't overwrite "pending" with "in_progress" — the job
    # tab already shows pending status from the Generation table.

    job.destinations = json.dumps(dests)

    # Reason: also update job details to include latest generation info
    try:
        details = json.loads(job.details) if job.details else {}
        # Reason: refresh generations list from DB
        from streamdoc.models.generation import Generation as GenModel
        gens = session.query(GenModel).filter(GenModel.job_id == job_id).all()
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
            job.details = json.dumps(details)
    except Exception:
        pass


async def generation_poller_loop() -> None:
    """Background loop that polls pending generations periodically.

    Intended to be run as a FastAPI background task on startup.
    """
    logger.info("NotebookLM generation poller started (interval: %.1fs)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            await poll_pending_generations()
        except Exception as exc:
            logger.error("Generation poller error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
