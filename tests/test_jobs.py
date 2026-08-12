"""Tests for job tracking, retry, and resend."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from streamdoc.config import Settings
from streamdoc.core.jobs import (
    complete_job,
    create_job,
    list_jobs,
    resend_job,
    retry_job,
)
from streamdoc.db import init_db, session_scope
from streamdoc.models.job import Job as JobModel


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    output_root = tmp_path / "outputs"
    s = Settings(
        db_path=str(db_path),
        output_root=str(output_root),
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    init_db()
    yield


def test_create_job_creates_record():
    job_id = create_job("test_preset")
    assert len(job_id) == 8
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        assert job is not None
        assert job.status == "running"
        assert job.preset_name == "test_preset"


def test_complete_job_updates_status():
    job_id = create_job("test_preset")
    # Fake artifact-like objects
    class FakeArtifact:
        md_path = Path("/tmp/report.md")
        pdf_path = Path("/tmp/report.pdf")

    complete_job(job_id, [FakeArtifact()], {"notebooklm": "success"})
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        assert job.status == "completed"
        assert job.artifact_count == 1
        paths = json.loads(job.report_paths)
        assert str(Path("/tmp/report.md")) in paths


def test_complete_job_partial_status():
    job_id = create_job("test_preset")
    complete_job(job_id, [], {"notebooklm": "error: timeout"})
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        assert job.status == "failed"
        errs = json.loads(job.errors)
        assert "error: timeout" in errs


def test_list_jobs_returns_recent():
    create_job("preset_a")
    create_job("preset_b")
    jobs = list_jobs(limit=10)
    assert len(jobs) == 2
    assert jobs[0]["preset_name"] == "preset_b"  # most recent first


def test_retry_job_raises_when_not_found():
    with pytest.raises(ValueError, match="not found"):
        retry_job("nonexistent")


def test_resend_job_raises_when_not_found():
    with pytest.raises(ValueError, match="not found"):
        resend_job("nonexistent", "notebooklm")


def test_list_jobs_handles_legacy_empty_details():
    """Old rows created before the `details` column existed have empty strings.

    Reason: SQLAlchemy create_all doesn't backfill columns; a lightweight
    ALTER TABLE adds `details TEXT DEFAULT ''`. list_jobs must coerce that
    empty string into a dict so JobOut pydantic validation doesn't fail
    with "Input should be a valid dictionary".
    """
    from streamdoc.api.schemas import JobOut

    # Insert a legacy row with empty details/destinations (as ALTER TABLE would)
    with session_scope() as session:
        session.add(JobModel(
            id="legacy01",
            preset_name="old_preset",
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            artifact_count=0,
            report_paths="",
            destinations="",
            errors="",
            details="",
        ))

    jobs = list_jobs(limit=10)
    legacy = next(j for j in jobs if j["id"] == "legacy01")
    # Must be dicts, not lists — this is what broke the dashboard
    assert legacy["details"] == {}
    assert legacy["destinations"] == {}
    assert legacy["errors"] == []
    # And it must round-trip through the pydantic schema the dashboard uses
    JobOut(**legacy)
