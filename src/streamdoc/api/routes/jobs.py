"""Job tracking routes — list, retry, resend."""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException, Query

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import JobOut, JobResendRequest, JobRetryResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

# Job ids with a retry/resend currently running in the background. Prevents
# a double-click (or a second tab) from racing two uploads for the same job.
_IN_FLIGHT: set[str] = set()


def _run_execute(job_id: str, new_destinations: list[str] | None) -> None:
    """Background executor for retry/resend.

    Errors are written back into the job row so the UI surfaces them on the
    next poll — a synchronous swallow here is what made retry look dead.
    """
    from streamdoc.core.jobs import _execute_job

    try:
        _execute_job(job_id, new_destinations)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Background retry/resend failed for job %s: %s", job_id, exc)
        try:
            from streamdoc.db import session_scope
            from streamdoc.models.job import Job as JobModel
            from streamdoc.core.jobs import _json_dumps, _json_loads

            with session_scope() as session:
                job = session.get(JobModel, job_id)
                if job:
                    errs = _json_loads(job.errors, default=[])
                    errs = errs if isinstance(errs, list) else []
                    errs.append(f"error: retry/resend failed: {exc}")
                    job.errors = _json_dumps(errs)
                    if job.status not in ("running",):
                        job.status = "failed"
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record retry/resend error for job %s", job_id)
    finally:
        _IN_FLIGHT.discard(job_id)
router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_exists(job_id: str) -> bool:
    """Return True when the job row exists (cheap 404 pre-check)."""
    from streamdoc.db import session_scope
    from streamdoc.models.job import Job as JobModel

    with session_scope() as session:
        return session.get(JobModel, job_id) is not None


@router.get("", response_model=list[JobOut])
def list_jobs(
    limit: int = Query(20, ge=1, le=200),
    status: str | None = Query(None),
):
    """List recent jobs."""
    ensure_db()
    from streamdoc.core.jobs import list_jobs as _list
    jobs = _list(limit=limit)
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    return jobs


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    """Get a single job's details."""
    ensure_db()
    from streamdoc.core.jobs import list_jobs as _list
    jobs = _list(limit=200)
    for j in jobs:
        if j["id"] == job_id:
            return j
    raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


@router.post("/{job_id}/retry", response_model=JobRetryResponse)
def retry_job(job_id: str):
    """Retry failed destinations for a job (runs in background).

    Sends can take minutes (NotebookLM upload + generation). Running them
    synchronously held the HTTP request open with zero UI feedback, which
    made retry look dead. The job row updates as sends complete — the Jobs
    page polls and surfaces the new destination states.
    """
    ensure_db()
    if not _job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job_id in _IN_FLIGHT:
        return JobRetryResponse(results={}, status="already_running")
    _IN_FLIGHT.add(job_id)
    threading.Thread(
        target=_run_execute, args=(job_id, None), daemon=True
    ).start()
    return JobRetryResponse(results={}, status="started")


@router.post("/{job_id}/resend", response_model=JobRetryResponse)
def resend_job(job_id: str, body: JobResendRequest):
    """Resend a job's reports to a destination (runs in background)."""
    ensure_db()
    from streamdoc.core.jobs import _SEND_DESTINATIONS
    if body.destination not in _SEND_DESTINATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown destination '{body.destination}'. "
                   f"Valid: {', '.join(_SEND_DESTINATIONS)}",
        )
    if not _job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job_id in _IN_FLIGHT:
        return JobRetryResponse(results={}, status="already_running")
    _IN_FLIGHT.add(job_id)
    threading.Thread(
        target=_run_execute, args=(job_id, [body.destination]), daemon=True
    ).start()
    return JobRetryResponse(results={}, status="started")


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a running job."""
    ensure_db()
    from streamdoc.core.jobs import cancel_job as _cancel
    try:
        result = _cancel(job_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
