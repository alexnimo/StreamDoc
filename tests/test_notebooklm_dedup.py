"""Regression tests for NotebookLM generation deduplication.

Quota-exhaustion bug: every retry path (with_auth_check replay, the outer
retry loop, wait-phase failures, job-level resume) submitted a brand-new
generate_* call, so one logical deck became 4-5 parallel server-side
generations. The fix lists artifacts before every submit and adopts /
reuses / in-place-retries existing rows instead of duplicating them.
"""

import pytest
from types import SimpleNamespace

pytest.importorskip("streamdoc.integrations.notebooklm")

from streamdoc.integrations.notebooklm import ContentManager, ContentType
from streamdoc.integrations.notebooklm.prompts import PromptManager


class _MockGenerationStatus:
    def __init__(self, task_id="task-123", status="in_progress", error=None, metadata=None):
        self.task_id = task_id
        self.status = status
        self.error = error
        self.metadata = metadata or {}
        self.artifact_id = "art-456"


class _MockArtifact:
    """Stand-in for notebooklm.types.Artifact."""

    def __init__(self, id, status):
        self.id = id
        self._status = status

    @property
    def is_pending(self):
        return self._status == "pending"

    @property
    def is_processing(self):
        return self._status == "processing"

    @property
    def is_completed(self):
        return self._status == "completed"

    @property
    def is_failed(self):
        return self._status == "failed"


class _MockArtifactsAPI:
    """Artifacts API with list + generate + retry_failed hooks."""

    def __init__(self, listed=None, submit_side_effects=None):
        self._listed = listed if listed is not None else []
        self._submit_side_effects = list(submit_side_effects or [])
        self.generate_calls = []
        self.retry_calls = []
        self.wait_calls = []

    async def list_slide_decks(self, notebook_id):
        return list(self._listed)

    async def generate_slide_deck(self, notebook_id, instructions=None, **kw):
        self.generate_calls.append({"instructions": instructions})
        if self._submit_side_effects:
            effect = self._submit_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return _MockGenerationStatus()

    async def retry_failed(self, notebook_id, artifact_id):
        self.retry_calls.append(artifact_id)
        return _MockGenerationStatus(task_id=artifact_id)

    async def wait_for_completion(self, notebook_id, task_id, timeout=None):
        self.wait_calls.append(task_id)
        return _MockGenerationStatus(
            task_id=task_id,
            status="completed",
            metadata={"artifact_id": "art-789"},
        )


class _MockSourcesAPI:
    def __init__(self, add_side_effects=None, listed=None):
        self._add_side_effects = list(add_side_effects or [])
        self._listed = list(listed or [])
        self.add_calls = []
        self.list_calls = 0

    async def add_file(self, notebook_id, path, title=None, wait=True, wait_timeout=None):
        self.add_calls.append({"title": title})
        if self._add_side_effects:
            effect = self._add_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return SimpleNamespace(id="src-new", title=title, status=None)

    async def list(self, notebook_id):
        self.list_calls += 1
        return list(self._listed)


class _MockInnerClient:
    """Inner notebooklm client with a refresh_auth hook."""

    def __init__(self):
        self.refresh_calls = 0

    async def refresh_auth(self, allow_headless=False):
        self.refresh_calls += 1


class _MockClientWrapper:
    def __init__(self, artifacts=None, sources=None):
        self._artifacts = artifacts or _MockArtifactsAPI()
        self._sources = sources or _MockSourcesAPI()
        self._inner = _MockInnerClient()
        self.auto_refresh = True

    @property
    def artifacts(self):
        return self._artifacts

    @property
    def sources(self):
        return self._sources

    def _ensure_client(self):
        return self._inner

    async def with_auth_check(self, operation):
        """Mirror NotebookLMClientWrapper.with_auth_check — pass-through."""
        return await operation()


def _make(artifacts=None, sources=None):
    return ContentManager(
        _MockClientWrapper(artifacts=artifacts, sources=sources),
        PromptManager(),
        default_wait_timeout=5.0,
    )


@pytest.mark.asyncio
async def test_inflight_artifact_adopted_no_duplicate_submit():
    """An in-flight slide deck must be adopted — no second generate call."""
    artifacts = _MockArtifactsAPI(listed=[_MockArtifact("art-running", "processing")])
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1", ContentType.SLIDE_DECK, prompt="p", wait=True
    )

    assert result.status == "completed"
    assert artifacts.generate_calls == []
    # wait_for_completion polls the adopted artifact id (task id).
    assert artifacts.wait_calls == ["art-running"]


@pytest.mark.asyncio
async def test_auth_error_refresh_adopts_committed_artifact():
    """A submit that errors after committing server-side must not be replayed.

    First generate_slide_deck raises UNAUTHENTICATED; after refresh the
    re-list finds the artifact that actually committed → adopted, and
    generate_slide_deck is never called again.
    """
    artifacts = _MockArtifactsAPI(
        submit_side_effects=[
            Exception("The server rejected this request (unauthenticated).")
        ],
    )
    # The errored submit committed server-side: the artifact shows up in
    # the re-list that happens after the auth refresh.
    original_generate = artifacts.generate_slide_deck

    async def _committing_generate(notebook_id, instructions=None, **kw):
        artifacts._listed.append(_MockArtifact("art-committed", "processing"))
        return await original_generate(notebook_id, instructions=instructions, **kw)

    artifacts.generate_slide_deck = _committing_generate
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1", ContentType.SLIDE_DECK, prompt="p", wait=True
    )

    assert result.status == "completed"
    # Exactly ONE submit happened — the auth-failed attempt was adopted,
    # not replayed.
    assert len(artifacts.generate_calls) == 1
    assert mgr.client_wrapper._ensure_client().refresh_calls == 1
    assert artifacts.wait_calls == ["art-committed"]

@pytest.mark.asyncio
async def test_auth_error_no_committed_artifact_resubmits_after_refresh():
    """When nothing committed server-side, a refreshed resubmit is allowed."""
    artifacts = _MockArtifactsAPI(
        listed=[],
        submit_side_effects=[
            Exception("The server rejected this request (unauthenticated)."),
            _MockGenerationStatus(),
        ],
    )
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1", ContentType.SLIDE_DECK, prompt="p", wait=True
    )

    assert result.status == "completed"
    assert len(artifacts.generate_calls) == 2  # retry after refresh, no artifact to adopt
    assert mgr.client_wrapper._ensure_client().refresh_calls == 1


@pytest.mark.asyncio
async def test_failed_artifact_retried_in_place():
    """A failed artifact is retried via retry_failed — no duplicate row."""
    artifacts = _MockArtifactsAPI(listed=[_MockArtifact("art-dead", "failed")])
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1", ContentType.SLIDE_DECK, prompt="p", wait=True
    )

    assert result.status == "completed"
    assert artifacts.retry_calls == ["art-dead"]
    assert artifacts.generate_calls == []
    assert artifacts.wait_calls == ["art-dead"]


@pytest.mark.asyncio
async def test_completed_artifact_reused():
    """A completed artifact is reused — zero regeneration quota spent."""
    artifacts = _MockArtifactsAPI(listed=[_MockArtifact("art-done", "completed")])
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1", ContentType.SLIDE_DECK, prompt="p", wait=True
    )

    assert result.status == "completed"
    assert artifacts.generate_calls == []


@pytest.mark.asyncio
async def test_wait_phase_error_returns_pending_no_resubmit():
    """A non-auth wait_for_completion failure must degrade to pending —
    the task is still registered server-side; resubmitting would duplicate."""

    class _BadWaitArtifacts(_MockArtifactsAPI):
        async def wait_for_completion(self, notebook_id, task_id, timeout=None):
            raise RuntimeError("transient poll error")

    artifacts = _BadWaitArtifacts()
    mgr = _make(artifacts=artifacts)

    result = await mgr.generate_content(
        "nb-1",
        ContentType.SLIDE_DECK,
        prompt="p",
        wait=True,
        retry_generation=True,
        retry_attempts=2,
        retry_delay=0.01,
    )

    assert result.status == "pending"
    assert result.task_id == "task-123"
    # One submit only — the wait error never triggered a resubmit.
    assert len(artifacts.generate_calls) == 1


@pytest.mark.asyncio
async def test_upload_auth_recovery_adopts_committed_source(tmp_path):
    """An upload that errors after committing is adopted by title, not duplicated."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 fake")

    sources = _MockSourcesAPI(
        add_side_effects=[
            Exception("The server rejected this request (unauthenticated)."),
        ],
        listed=[SimpleNamespace(id="src-committed", title="report", status=None)],
    )
    mgr = _make(sources=sources)

    info = await mgr.upload_report("nb-1", report, title="report")

    assert info.id == "src-committed"
    assert len(sources.add_calls) == 1  # never re-added after refresh
    assert mgr.client_wrapper._ensure_client().refresh_calls == 1


@pytest.mark.asyncio
async def test_upload_auth_recovery_reuploads_when_nothing_committed(tmp_path):
    """When the errored upload truly didn't commit, it retries after refresh."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 fake")

    sources = _MockSourcesAPI(
        add_side_effects=[
            Exception("The server rejected this request (unauthenticated)."),
        ],
        listed=[],  # nothing committed server-side
    )
    mgr = _make(sources=sources)

    info = await mgr.upload_report("nb-1", report, title="report")

    assert info.id == "src-new"
    assert len(sources.add_calls) == 2
    assert mgr.client_wrapper._ensure_client().refresh_calls == 1


@pytest.mark.asyncio
async def test_upload_non_auth_error_not_recovered(tmp_path):
    """Non-auth upload failures must NOT trigger a refresh or retry."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 fake")

    sources = _MockSourcesAPI(
        add_side_effects=[RuntimeError("disk full")],
    )
    mgr = _make(sources=sources)

    with pytest.raises(Exception, match="Failed to upload report"):
        await mgr.upload_report("nb-1", report, title="report")

    assert len(sources.add_calls) == 1
    assert mgr.client_wrapper._ensure_client().refresh_calls == 0
