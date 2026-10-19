"""Tests for job tracking, retry, and resend."""
from __future__ import annotations

import json
import sys
import types
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


def test_resend_job_reads_preset_name_without_detached_instance(tmp_path, monkeypatch):
    """Regression: _execute_job must not touch job.* attributes after the
    session closes — commit() expires them and the detached read raises
    'not bound to a Session; attribute refresh operation cannot proceed'.
    """
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps({"notebooklm": "error: session expired"})

    captured: dict = {}
    import streamdoc.core.jobs as jobs_mod
    monkeypatch.setattr(
        jobs_mod, "_send_to_destination",
        lambda dest, paths, preset_name="", job_id="": captured.update(
            {"dest": dest, "preset_name": preset_name, "paths": paths}
        ),
    )

    results = resend_job(job_id, "notebooklm")

    assert results == {"notebooklm": "success"}
    assert captured["preset_name"] == "test_preset"
    assert captured["paths"] == [report]


def test_retry_job_retries_only_failed_destinations(tmp_path, monkeypatch):
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "partial"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps(
            {"agy": "success", "notebooklm": "error: session expired"}
        )

    attempted: list[str] = []
    import streamdoc.core.jobs as jobs_mod
    monkeypatch.setattr(
        jobs_mod, "_send_to_destination",
        lambda dest, paths, preset_name="", job_id="": attempted.append(dest),
    )

    results = retry_job(job_id)

    assert attempted == ["notebooklm"]
    assert results == {"notebooklm": "success"}

    with session_scope() as session:
        job = session.get(JobModel, job_id)
        assert job.status == "completed"
        merged = json.loads(job.destinations)
        assert merged["notebooklm"] == "success"
        assert merged["agy"] == "success"


def test_retry_job_agy_instantiates_tool_and_prefers_md(tmp_path, monkeypatch):
    """Regression: the agy retry path must call run() on a tool INSTANCE.

    registry.get_tool() returns the tool CLASS; calling .run() on it
    unbound shifts every arg and fails with
    "missing 1 required positional argument: 'out_dir'". Additionally,
    when job.report_paths holds both the .md and .pdf of a report, only
    the .md should be sent — PDFs without an .md sibling are kept.
    """
    from types import SimpleNamespace

    from streamdoc.integrations.cli_tools import registry as cli_tools_registry

    md = tmp_path / "report.md"
    pdf = tmp_path / "report.pdf"
    legacy_pdf = tmp_path / "legacy.pdf"
    md.write_text("# report", encoding="utf-8")
    pdf.write_bytes(b"%PDF-fake")
    legacy_pdf.write_bytes(b"%PDF-legacy")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "partial"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.report_paths = json.dumps([str(md), str(pdf), str(legacy_pdf)])
        job.destinations = json.dumps({"agy": "error: timed out"})

    calls: list[tuple] = []

    class FakeTool:
        name = "agy"

        async def run(self, report_paths, template, out_dir):
            calls.append((list(report_paths), template, out_dir))
            return SimpleNamespace(success=True)

    # Reason: patching get_tool also steers instantiate() (it delegates to
    # get_tool internally). If the code ever regresses to calling .run() on
    # the returned class instead of an instance, FakeTool.run receives an
    # unbound call and raises TypeError — failing this test.
    monkeypatch.setattr(cli_tools_registry, "get_tool", lambda name: FakeTool)

    results = retry_job(job_id)

    assert results == {"agy": "success"}
    assert len(calls) == 1
    paths_arg, _template, _out_dir = calls[0]
    # .md preferred; its sibling .pdf dropped; unpaired .pdf retained
    assert paths_arg == [md, legacy_pdf]


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


def test_retry_job_skips_metadata_destination_keys(tmp_path, monkeypatch):
    """Regression: destinations holds metadata keys alongside real send
    targets (urls, local paths, pending markers, *_errors lists). Retrying
    must only attempt the sendable destinations — previously every key was
    attempted, so "notebooklm_url" etc. produced bogus "Unknown destination"
    results that overwrote the real error, and a list value like
    notebooklm_errors crashed str.startswith outright.
    """
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "failed"
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps({
            "notebooklm": "error: The server rejected this request (unauthenticated).",
            "notebooklm_errors": ["gen failed", "upload failed"],
            "notebooklm_url": "https://notebook.google.com/x",
            "notebooklm_slide_deck": "pending",
            "agy": "success",
        })
    attempted: list[str] = []
    import streamdoc.core.jobs as jobs_mod

    def _fake_send(dest, paths, preset_name="", job_id=""):
        attempted.append(dest)
        # Real sends return fresh metadata extras; return the URL the new
        # run produced so stale-key purging can be verified alongside.
        return {"notebooklm_url": "https://notebook.google.com/new"}

    monkeypatch.setattr(jobs_mod, "_send_to_destination", _fake_send)

    results = retry_job(job_id)

    assert attempted == ["notebooklm"]
    assert results == {"notebooklm": "success"}
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        merged = json.loads(job.destinations)
        assert merged["notebooklm"] == "success"
        # Fresh metadata replaced the stale run's keys; stale keys that the
        # new run didn't produce (old errors list, stale per-type state)
        # are gone rather than contradicting the fresh "success".
        assert merged["notebooklm_url"] == "https://notebook.google.com/new"
        assert "notebooklm_errors" not in merged
        assert "notebooklm_slide_deck" not in merged
        # Untouched destinations keep their metadata.
        assert merged["agy"] == "success"


def test_resend_job_rejects_unknown_destination(tmp_path, monkeypatch):
    """Resend to a non-sendable name (e.g. a free-text typo or a metadata
    key like "notebooklm_url") must not attempt a send."""
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps({"notebooklm": "success"})

    attempted: list[str] = []
    import streamdoc.core.jobs as jobs_mod
    monkeypatch.setattr(
        jobs_mod, "_send_to_destination",
        lambda dest, paths, preset_name="", job_id="": attempted.append(dest),
    )

    results = resend_job(job_id, "notebooklm_url")

    assert attempted == []
    assert results == {}


def _stub_upload_module(monkeypatch, captured: dict, success: bool = True):
    """Inject a fake streamdoc.core.notebooklm_upload into sys.modules.

    Reason: importing the real module inside a test binds its module-level
    ``from streamdoc.config import settings`` to the _isolated_db fixture's
    fake Settings permanently — poisoning prompt-dir settings for every
    later test in the session. A sys.modules stub avoids the import while
    still letting _send_to_destination's local import resolve.
    """
    class _FakeResult:
        def __init__(self, ok):
            self.success = ok
            self.errors = []
            self.notebook_id = "nb-fake"
            self.notebook_url = ""
            self.generated_content = []
    async def _fake_upload(**kwargs):
        captured.update(kwargs)
        return _FakeResult(success)

    fake = types.ModuleType("streamdoc.core.notebooklm_upload")
    fake.upload_to_notebooklm = _fake_upload
    monkeypatch.setitem(sys.modules, "streamdoc.core.notebooklm_upload", fake)


def test_send_to_notebooklm_resumes_failed_notebook(tmp_path, monkeypatch):
    """Regression: a job whose generation failed AFTER sources uploaded
    stores notebooklm_id; the retry must resume generation on that notebook
    (notebook_id + resume=True) instead of re-uploading into an orphan.
    """
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "failed"
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps({
            "notebooklm": "error: Failed to generate ContentType.SLIDE_DECK: quota",
            "notebooklm_id": "nb-123",
        })

    captured: dict = {}
    _stub_upload_module(monkeypatch, captured)

    import streamdoc.core.jobs as jobs_mod
    monkeypatch.setattr(
        "streamdoc.async_utils.run_async",
        lambda coro: __import__("asyncio").run(coro),
    )

    jobs_mod._send_to_destination(
        "notebooklm", [report], preset_name="test_preset", job_id=job_id,
    )

    assert captured["notebook_id"] == "nb-123"
    assert captured["resume"] is True


def test_send_to_notebooklm_no_resume_on_upload_failure(tmp_path, monkeypatch):
    """When the stored error is an UPLOAD failure, the notebook's sources are
    unreliable — retry must start a fresh notebook (no notebook_id/resume)."""
    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")

    job_id = create_job("test_preset")
    with session_scope() as session:
        job = session.get(JobModel, job_id)
        job.status = "failed"
        job.report_paths = json.dumps([str(report)])
        job.destinations = json.dumps({
            "notebooklm": "error: Failed to upload report 'x.md': Source failed to process",
            "notebooklm_id": "nb-999",
        })

    captured: dict = {}
    _stub_upload_module(monkeypatch, captured)

    import streamdoc.core.jobs as jobs_mod
    monkeypatch.setattr(
        "streamdoc.async_utils.run_async",
        lambda coro: __import__("asyncio").run(coro),
    )

    jobs_mod._send_to_destination(
        "notebooklm", [report], preset_name="test_preset", job_id=job_id,
    )

    assert captured["notebook_id"] is None
    assert captured["resume"] is False


def test_is_auth_error_matches_unauthenticated_rpc():
    """Regression: 'The server rejected this request (unauthenticated).' is
    a wire-decoder UNAUTHENTICATED status — the signature must be treated as
    auth-shaped so check_session_freshness triggers browser re-capture."""
    from streamdoc.integrations.notebooklm.auth import _is_auth_error

    exc = Exception("The server rejected this request (unauthenticated).")
    assert _is_auth_error(exc) is True
    # And the upstream wording embedded inside our wrapper message too
    exc2 = Exception(
        "Failed to generate ContentType.SLIDE_DECK: "
        "The server rejected this request (unauthenticated)."
    )
    assert _is_auth_error(exc2) is True
    # Non-auth errors still rejected
    assert _is_auth_error(Exception("Resource exhausted")) is False
    assert _is_auth_error(Exception("File not found: report.md")) is False
