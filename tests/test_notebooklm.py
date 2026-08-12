"""Tests for NotebookLM integration.

These tests verify the NotebookLM integration modules without requiring
the notebooklm-py library to be installed or authentication to be configured.

For live integration tests, use the `notebooklm` pytest marker.
"""

import pytest

# Skip all tests if notebooklm is not available
notebooklm = pytest.importorskip("streamdoc.integrations.notebooklm")

from streamdoc.integrations.notebooklm import (
    NOTEBOOKLM_AVAILABLE,
    ContentManager,
    ContentType,
    NotebookLMAuthManager,
    NotebookLMClientWrapper,
    PromptManager,
    SessionStatus,
)
from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMAuthRequiredError,
    NotebookLMIntegrationError,
)
from streamdoc.integrations.notebooklm.prompts import PromptTemplate
from streamdoc.integrations.notebooklm.retention import (
    NotebookLMContent,
    NotebookLMRetentionLog,
)


def test_notebooklm_available():
    """Test that NOTEBOOKLM_AVAILABLE flag is True."""
    assert NOTEBOOKLM_AVAILABLE is True


def test_session_status_dataclass():
    """Test SessionStatus dataclass creation."""
    status = SessionStatus(
        is_valid=True,
        is_fresh=True,
        message="Test",
        profile="default",
        storage_path="/test/path"
    )
    assert status.is_valid is True
    assert status.profile == "default"


def test_content_type_enum():
    """Test ContentType enum values."""
    assert ContentType.SLIDE_DECK.value == "slide_deck"
    assert ContentType.PODCAST.value == "podcast"
    assert ContentType.INFOGRAPHIC.value == "infographic"
    assert ContentType.REPORT.value == "report"


def test_prompt_template_render():
    """Test PromptTemplate rendering."""
    template = PromptTemplate(
        name="test",
        description="Test template",
        target_types=[ContentType.REPORT],
        prompt="Create a {content_type} about {topic}",
        variables={"topic": "default topic"}
    )
    
    rendered = template.render(ContentType.REPORT, topic="AI")
    assert "report" in rendered
    assert "AI" in rendered


def test_prompt_template_invalid_content_type():
    """Test that rendering with invalid content type raises error."""
    template = PromptTemplate(
        name="test",
        description="Test template",
        target_types=[ContentType.REPORT],
        prompt="Create a {content_type}"
    )
    
    with pytest.raises(ValueError):
        template.render(ContentType.PODCAST)  # Not in target_types


def test_prompt_manager_default_templates():
    """Test that PromptManager loads default templates."""
    pm = PromptManager()
    
    # Should have default templates
    templates = pm.list_templates()
    assert len(templates) >= 3  # At least default, financial_extraction, design_guidelines
    
    # Should be able to load default template
    default = pm.load_template("default")
    assert default.name == "default"


def test_prompt_manager_list_by_content_type():
    """Test listing templates filtered by content type."""
    pm = PromptManager()
    
    # Should have templates for each content type
    report_templates = pm.list_templates(ContentType.REPORT)
    assert len(report_templates) > 0
    
    podcast_templates = pm.list_templates(ContentType.PODCAST)
    assert len(podcast_templates) > 0


def test_notebooklm_content_model():
    """Test NotebookLMContent database model."""
    from datetime import datetime, timedelta
    
    content = NotebookLMContent(
        id="test-id",
        notebook_id="nb-123",
        notebook_title="Test Notebook",
        preset_name="test-preset",
        is_permanent=False,
        retention_hours=24.0,
        created_at=datetime.utcnow(),  # noqa: DTZ003
        status="active"
    )
    
    # Set expires_at based on retention
    content.expires_at = content.created_at + timedelta(hours=content.retention_hours)
    
    assert content.notebook_id == "nb-123"
    assert content.is_expired() is False
    
    # Test permanent content never expires
    content.is_permanent = True
    assert content.is_expired() is False


def test_notebooklm_content_artifacts():
    """Test NotebookLMContent artifact serialization."""
    content = NotebookLMContent(
        id="test-id",
        notebook_id="nb-123",
        notebook_title="Test",
        preset_name="test"
    )
    
    # Test setting artifacts
    artifacts = [
        {"type": "slide_deck", "id": "art-1", "local_path": "/tmp/test.pptx"}
    ]
    content.set_artifacts(artifacts)
    
    # Test getting artifacts
    retrieved = content.get_artifacts()
    assert len(retrieved) == 1
    assert retrieved[0]["type"] == "slide_deck"


def test_retention_log_model():
    """Test NotebookLMRetentionLog database model."""
    from datetime import datetime
    
    log = NotebookLMRetentionLog(
        id="log-1",
        content_id="content-1",
        action="deleted",
        timestamp=datetime.utcnow(),  # noqa: DTZ003
        details="Test deletion"
    )
    
    assert log.action == "deleted"
    assert log.content_id == "content-1"


def test_exceptions():
    """Test custom exception classes."""
    # Test that all exceptions inherit from base
    assert issubclass(NotebookLMAuthRequiredError, NotebookLMIntegrationError)
    assert issubclass(NotebookLMIntegrationError, Exception)
    
    # Test exception raising
    with pytest.raises(NotebookLMAuthRequiredError):
        raise NotebookLMAuthRequiredError("Test auth error")


@pytest.mark.asyncio
async def test_auth_manager_not_configured():
    """Test auth manager when not configured."""
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_manager = NotebookLMAuthManager(
            storage_path=f"{tmpdir}/nonexistent/storage_state.json",
            profile="default"
        )
        
        # Should not be configured
        assert auth_manager.is_configured() is False
        
        # Session freshness should show not configured
        status = await auth_manager.check_session_freshness()
        assert status.is_valid is False


class TestIntegrationPlaceholders:
    """Placeholder tests for integration that require actual notebooklm-py.

    These tests are skipped when notebooklm-py is not properly installed
    or when no authentication is configured.
    """

    @pytest.mark.notebooklm
    @pytest.mark.asyncio
    async def test_client_wrapper_requires_auth(self):
        """Test that client wrapper requires authentication."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_manager = NotebookLMAuthManager(
                storage_path=f"{tmpdir}/storage_state.json"
            )

            # Without valid auth, should raise when entering context
            with pytest.raises(NotebookLMAuthRequiredError):
                async with NotebookLMClientWrapper(auth_manager):
                    pass  # Should not reach here


# ---------------------------------------------------------------------------
# Prompt injection tests — verify the rendered prompt reaches the notebooklm-py API
# ---------------------------------------------------------------------------

class _MockGenerationStatus:
    """Minimal stand-in for notebooklm.types.GenerationStatus."""
    def __init__(self, task_id="task-123", status="completed", metadata=None):
        self.task_id = task_id
        self.status = status
        self.metadata = metadata or {}
        self.artifact_id = "art-456"


class _MockArtifactsAPI:
    """Mock artifacts API that records the instructions passed to generate_*."""
    def __init__(self):
        self.slide_deck_calls: list[dict] = []
        self.audio_calls: list[dict] = []
        self.infographic_calls: list[dict] = []
        self.report_calls: list[dict] = []

    async def generate_slide_deck(self, notebook_id, instructions=None, **kw):
        self.slide_deck_calls.append({
            "notebook_id": notebook_id,
            "instructions": instructions,
            "kwargs": kw,
        })
        return _MockGenerationStatus()

    async def generate_audio(self, notebook_id, instructions=None, **kw):
        self.audio_calls.append({
            "notebook_id": notebook_id,
            "instructions": instructions,
        })
        return _MockGenerationStatus()

    async def generate_infographic(self, notebook_id, instructions=None, **kw):
        self.infographic_calls.append({
            "notebook_id": notebook_id,
            "instructions": instructions,
        })
        return _MockGenerationStatus()

    async def generate_report(self, notebook_id, custom_prompt=None, **kw):
        self.report_calls.append({
            "notebook_id": notebook_id,
            "custom_prompt": custom_prompt,
        })
        return _MockGenerationStatus()

    async def wait_for_completion(self, notebook_id, task_id, timeout=None):
        return _MockGenerationStatus(status="completed", metadata={"artifact_id": "art-789"})


class _MockClientWrapper:
    """Mock client wrapper exposing the artifacts API."""
    def __init__(self):
        self._artifacts = _MockArtifactsAPI()

    @property
    def artifacts(self):
        return self._artifacts


@pytest.mark.asyncio
async def test_prompt_injected_into_slide_deck_generation():
    """Verify the rendered prompt is passed as `instructions=` to generate_slide_deck.

    This is the core end-to-end prompt-injection test: it proves that a
    prompt template is rendered and the resulting string reaches the
    notebooklm-py API call.
    """
    prompts = PromptManager()
    content_mgr = ContentManager(_MockClientWrapper(), prompts, default_wait_timeout=5.0)

    await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.SLIDE_DECK,
        prompt="Create a slide deck about Bitcoin with 10 slides.",
        wait=True,
    )

    assert len(content_mgr.client_wrapper.artifacts.slide_deck_calls) == 1
    call = content_mgr.client_wrapper.artifacts.slide_deck_calls[0]
    assert call["notebook_id"] == "nb-test"
    # Reason: the prompt must be passed verbatim as `instructions=`
    assert call["instructions"] == "Create a slide deck about Bitcoin with 10 slides."
    assert call["instructions"] is not None


@pytest.mark.asyncio
async def test_prompt_template_rendered_and_injected():
    """Verify a named prompt template is rendered and injected into the API call."""
    prompts = PromptManager()
    content_mgr = ContentManager(_MockClientWrapper(), prompts, default_wait_timeout=5.0)

    # Use generate_and_download which renders the template then calls generate_content
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        from pathlib import Path
        await content_mgr.generate_and_download(
            notebook_id="nb-test",
            content_type=ContentType.SLIDE_DECK,
            output_dir=Path(tmpdir),
            prompt_template="financial_extraction",
        )

    assert len(content_mgr.client_wrapper.artifacts.slide_deck_calls) == 1
    call = content_mgr.client_wrapper.artifacts.slide_deck_calls[0]
    # Reason: the rendered prompt must contain the content_type substitution
    # and the financial_extraction template's key phrases
    assert call["instructions"] is not None
    assert "slide_deck" in call["instructions"]
    assert "financial" in call["instructions"].lower()


@pytest.mark.asyncio
async def test_no_prompt_passes_none():
    """Verify that when no prompt is provided, None is passed (NotebookLM default)."""
    content_mgr = ContentManager(_MockClientWrapper(), PromptManager(), default_wait_timeout=5.0)

    await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.SLIDE_DECK,
        prompt=None,
        wait=True,
    )

    assert len(content_mgr.client_wrapper.artifacts.slide_deck_calls) == 1
    call = content_mgr.client_wrapper.artifacts.slide_deck_calls[0]
    assert call["instructions"] is None


@pytest.mark.asyncio
async def test_report_uses_custom_prompt_param():
    """Verify report generation uses `custom_prompt=` not `instructions=`."""
    content_mgr = ContentManager(_MockClientWrapper(), PromptManager(), default_wait_timeout=5.0)

    await content_mgr.generate_content(
        notebook_id="nb-test",
        content_type=ContentType.REPORT,
        prompt="Summarize the key financial metrics.",
        wait=True,
    )

    assert len(content_mgr.client_wrapper.artifacts.report_calls) == 1
    call = content_mgr.client_wrapper.artifacts.report_calls[0]
    assert call["custom_prompt"] == "Summarize the key financial metrics."


def test_preset_model_has_prompt_template_field():
    """Verify the Preset model has the notebooklm_prompt_template column."""
    from streamdoc.models.preset import Preset

    # Reason: the column must exist on the model so presets can carry a
    # per-preset NotebookLM prompt template override.
    assert hasattr(Preset, "notebooklm_prompt_template")


def test_preset_schema_includes_prompt_template():
    """Verify the API schemas include notebooklm_prompt_template."""
    from streamdoc.api.schemas import PresetCreate, PresetOut, PresetUpdate

    assert "notebooklm_prompt_template" in PresetOut.model_fields
    assert "notebooklm_prompt_template" in PresetCreate.model_fields
    assert "notebooklm_prompt_template" in PresetUpdate.model_fields


@pytest.mark.asyncio
async def test_generate_and_download_uses_custom_prompt_when_no_template():
    """When prompt_template is None but custom_prompt is set, use custom_prompt."""
    content_mgr = ContentManager(_MockClientWrapper(), PromptManager(), default_wait_timeout=5.0)

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        await content_mgr.generate_and_download(
            notebook_id="nb-test",
            content_type=ContentType.SLIDE_DECK,
            output_dir=Path(tmpdir),
            prompt_template=None,
            custom_prompt="My custom prompt from prompt_md",
        )

    assert len(content_mgr.client_wrapper.artifacts.slide_deck_calls) == 1
    call = content_mgr.client_wrapper.artifacts.slide_deck_calls[0]
    assert call["instructions"] == "My custom prompt from prompt_md"


@pytest.mark.asyncio
async def test_generate_and_download_prioritizes_template_over_custom_prompt():
    """When both template and custom_prompt are set, template wins."""
    content_mgr = ContentManager(_MockClientWrapper(), PromptManager(), default_wait_timeout=5.0)

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        await content_mgr.generate_and_download(
            notebook_id="nb-test",
            content_type=ContentType.SLIDE_DECK,
            output_dir=Path(tmpdir),
            prompt_template="financial_extraction",
            custom_prompt="This should be ignored",
        )

    assert len(content_mgr.client_wrapper.artifacts.slide_deck_calls) == 1
    call = content_mgr.client_wrapper.artifacts.slide_deck_calls[0]
    assert call["instructions"] is not None
    assert "financial" in call["instructions"].lower()
    assert "ignored" not in call["instructions"].lower()


def test_auth_manager_login_script_uses_robust_playwright_module(monkeypatch: pytest.MonkeyPatch):
    """The login script must invoke the shared playwright_login module.

    This guards against regressing back to an inline, fragile script.
    """
    import tempfile

    import streamdoc.config as config_mod
    from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(config_mod.settings, "notebooklm_browser", "chromium")
        auth_manager = NotebookLMAuthManager(f"{tmpdir}/storage_state.json")
        script = auth_manager._login_script()

        assert "streamdoc.integrations.notebooklm.playwright_login" in script
        assert "run_playwright_login(" in script
        assert 'browser="chromium"' in script


@pytest.mark.asyncio
async def test_auth_manager_login_is_reusable_without_playwright():
    """login() must raise a clean RuntimeError from the subprocess stderr."""
    import tempfile

    from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_manager = NotebookLMAuthManager(f"{tmpdir}/storage_state.json")

        with pytest.raises(RuntimeError) as exc_info:
            # headless=True with no stored session exits immediately
            await auth_manager.login(headless=True)

        assert "Run 'notebooklm login' to re-authenticate" in str(exc_info.value)

