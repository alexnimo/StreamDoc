"""Regression tests for NotebookLM generation failure handling."""

import pytest

pytest.importorskip("streamdoc.integrations.notebooklm")

from streamdoc.integrations.notebooklm import ContentManager, ContentType
from streamdoc.integrations.notebooklm.prompts import PromptManager


class _MockGenerationStatus:
    """Minimal stand-in for notebooklm.types.GenerationStatus."""
    def __init__(self, task_id="task-123", status="completed", error=None, metadata=None):
        self.task_id = task_id
        self.status = status
        self.error = error
        self.metadata = metadata or {}
        self.artifact_id = "art-456"


class _FailingArtifactsAPI:
    """Mock artifacts API where generate_slide_deck returns a failed status."""
    def __init__(self, task_id="", status="failed", error="server failed"):
        self._task_id = task_id
        self._status = status
        self._error = error
        self.calls = []

    async def generate_slide_deck(self, notebook_id, instructions=None, **kw):
        self.calls.append({"notebook_id": notebook_id, "instructions": instructions})
        return _MockGenerationStatus(
            task_id=self._task_id,
            status=self._status,
            error=self._error,
        )

    async def wait_for_completion(self, notebook_id, task_id, timeout=None):
        # This should not be reached when the initial status is failed.
        return _MockGenerationStatus(status="completed")


class _TransientArtifactsAPI:
    """Mock artifacts API that fails once then succeeds."""
    def __init__(self):
        self.calls = []
        self._attempts = 0

    async def generate_slide_deck(self, notebook_id, instructions=None, **kw):
        self._attempts += 1
        self.calls.append({"notebook_id": notebook_id, "instructions": instructions})
        if self._attempts == 1:
            return _MockGenerationStatus(
                task_id="",
                status="failed",
                error="Generation failed on NotebookLM",
            )
        return _MockGenerationStatus(
            task_id="task-123",
            status="completed",
            metadata={"artifact_id": "art-789"},
        )

    async def wait_for_completion(self, notebook_id, task_id, timeout=None):
        return _MockGenerationStatus(
            task_id=task_id,
            status="completed",
            metadata={"artifact_id": "art-789"},
        )


class _MockClientWrapper:
    def __init__(self, artifacts_api):
        self._artifacts = artifacts_api

    @property
    def artifacts(self):
        return self._artifacts


@pytest.mark.asyncio
async def test_generate_content_propagates_failed_status_with_no_task_id():
    """If generate_slide_deck returns failed with no task_id, fail immediately.

    Regression: ContentManager.generate_content previously ignored
    result.status and returned status='in_progress', then generate_and_download
    attempted to download a non-existent artifact. This swallowed the real
    NotebookLM error message.
    """
    artifacts_api = _FailingArtifactsAPI(
        task_id="",
        status="failed",
        error="Generation failed on NotebookLM",
    )
    content_mgr = ContentManager(_MockClientWrapper(artifacts_api), PromptManager(), default_wait_timeout=5.0)

    result = await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.SLIDE_DECK,
        prompt="Some prompt",
        wait=True,
        retry_delay=0.0,
    )

    assert result.status == "failed"
    assert result.error == "Generation failed on NotebookLM"


@pytest.mark.asyncio
async def test_generate_and_download_propagates_failed_error():
    """generate_and_download must return a failed ContentResult with the real error."""
    artifacts_api = _FailingArtifactsAPI(
        task_id="",
        status="failed",
        error="Generation failed on NotebookLM",
    )
    content_mgr = ContentManager(_MockClientWrapper(artifacts_api), PromptManager(), default_wait_timeout=5.0)

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await content_mgr.generate_and_download(
            notebook_id="nb-test",
            content_type=ContentType.SLIDE_DECK,
            output_dir=Path(tmpdir),
            prompt_template="financial_extraction",
            retry_delay=0.0,
        )

    assert result.status == "failed"
    assert result.error == "Generation failed on NotebookLM"


@pytest.mark.asyncio
async def test_generate_content_retries_on_failure_and_succeeds():
    """A failed first attempt should be retried and can succeed."""
    artifacts_api = _TransientArtifactsAPI()
    content_mgr = ContentManager(_MockClientWrapper(artifacts_api), PromptManager(), default_wait_timeout=5.0)

    result = await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.SLIDE_DECK,
        prompt="Some prompt",
        wait=True,
        retry_delay=0.0,
    )

    assert result.status == "completed"
    assert result.artifact_id == "art-789"
    assert len(artifacts_api.calls) == 2


@pytest.mark.asyncio
async def test_generate_content_retry_disabled():
    """When retry is disabled, a failed first attempt is returned immediately."""
    artifacts_api = _TransientArtifactsAPI()
    content_mgr = ContentManager(_MockClientWrapper(artifacts_api), PromptManager(), default_wait_timeout=5.0)

    result = await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.SLIDE_DECK,
        prompt="Some prompt",
        wait=True,
        retry_generation=False,
        retry_delay=0.0,
    )

    assert result.status == "failed"
    assert len(artifacts_api.calls) == 1
