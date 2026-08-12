"""Job tracking routes — list, retry, resend."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import JobOut, JobResendRequest, JobRetryResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    """Retry failed destinations for a job."""
    ensure_db()
    from streamdoc.core.jobs import retry_job as _retry
    try:
        results = _retry(job_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobRetryResponse(results=results)


@router.post("/{job_id}/resend", response_model=JobRetryResponse)
def resend_job(job_id: str, body: JobResendRequest):
    """Resend a job's reports to a new destination."""
    ensure_db()
    from streamdoc.core.jobs import resend_job as _resend
    try:
        results = _resend(job_id, body.destination)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobRetryResponse(results=results)


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
