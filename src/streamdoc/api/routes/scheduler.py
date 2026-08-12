"""Scheduler routes — list, add, remove, run-once."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import ScheduleAddRequest, ScheduleJobOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[ScheduleJobOut])
def list_scheduled_jobs():
    """List all scheduled jobs."""
    from streamdoc.scheduler import list_jobs
    return list_jobs()


@router.post("/jobs", response_model=ScheduleJobOut)
def add_scheduled_job(body: ScheduleAddRequest):
    """Add a scheduled job."""
    from streamdoc.scheduler import add_job
    try:
        job = add_job(body.preset, body.schedule)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job


@router.delete("/jobs/{preset}")
def remove_scheduled_job(preset: str):
    """Remove a scheduled job."""
    from streamdoc.scheduler import remove_job
    try:
        remove_job(preset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"removed": preset}


@router.post("/run/{preset}")
def run_once(preset: str):
    """Run a preset once immediately."""
    from streamdoc.scheduler import run_once as _run
    try:
        _run(preset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"preset": preset, "status": "completed"}
