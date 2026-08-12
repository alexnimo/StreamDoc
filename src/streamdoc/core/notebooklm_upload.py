"""NotebookLM upload integration for the fetch pipeline.

This module provides the integration point between the StreamDoc fetch pipeline
and NotebookLM, handling upload, content generation, and retention management.
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from streamdoc.config import settings
from streamdoc.integrations.notebooklm import (
    ContentManager,
    ContentType,
    NotebookLMClientWrapper,
    NotebookLMAuthManager,
    NotebookManager,
    PromptManager,
    RetentionManager,
)
from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMAuthRequiredError,
    NotebookLMIntegrationError,
)

if TYPE_CHECKING:
    from streamdoc.db import Session

logger = logging.getLogger(__name__)


class NotebookLMUploadResult:
    """Result of NotebookLM upload and content generation.
    
    Attributes:
        success: Whether the overall operation succeeded
        notebook_id: NotebookLM notebook ID
        notebook_url: URL to view the notebook
        sources: List of uploaded source IDs
        generated_content: List of generated content results
        errors: List of any errors encountered
    """
    def __init__(
        self,
        success: bool,
        notebook_id: str | None = None,
        notebook_url: str | None = None,
        sources: list | None = None,
        generated_content: list | None = None,
        errors: list | None = None
    ):
        self.success = success
        self.notebook_id = notebook_id
        self.notebook_url = notebook_url
        self.sources = sources or []
        self.generated_content = generated_content or []
        self.errors = errors or []
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "notebook_id": self.notebook_id,
            "notebook_url": self.notebook_url,
            "sources": self.sources,
            "generated_content": [
                {
                    "type": c.content_type.value,
                    "artifact_id": c.artifact_id,
                    "local_path": str(c.local_path) if c.local_path else None,
                    "status": c.status
                }
                for c in self.generated_content
            ],
            "errors": self.errors
        }


async def upload_to_notebooklm(
    report_paths: list[Path],
    preset_name: str,
    job_id: str | None = None,
    notebook_id: str | None = None,
    content_types: list[ContentType] | None = None,
    prompt_template: str | None = None,
    custom_prompt: str | None = None,
    is_permanent: bool = False,
    retention_hours: float | None = None,
    db_session: "Session | None" = None,
    retry_generation: bool = True,
    retry_attempts: int = 1,
    retry_delay: float = 300.0,
) -> NotebookLMUploadResult:
    """Upload reports to NotebookLM and optionally generate content.
    
    This is the main integration function for the fetch pipeline. It handles:
    - Authentication checking
    - Notebook creation or reuse
    - Report upload as sources
    - Content generation (slide deck, podcast, infographic, report)
    - Local download of generated content
    - Retention tracking
    
    Reason: the prompt resolution priority is:
    1. prompt_template (template name, e.g. "financial_extraction") —
       rendered via PromptManager.render_prompt()
    2. custom_prompt (raw text from preset.prompt_md) — passed directly
       to NotebookLM as the instructions string
    3. settings.notebooklm_default_prompt (system default template name) —
       only used when neither of the above is provided
    
    Args:
        report_paths: List of report files (.md, .pdf) to upload
        preset_name: Name of the preset being processed
        job_id: Optional job ID for tracking
        notebook_id: Existing notebook ID (creates new if None)
        content_types: List of content types to generate
        prompt_template: Name of prompt template to use (highest priority)
        custom_prompt: Raw prompt text to use (second priority)
        is_permanent: Whether to skip retention cleanup
        retention_hours: Custom retention period
        db_session: Database session for retention tracking
        retry_generation: Whether to retry if NotebookLM generation fails
        retry_attempts: Number of extra generation attempts after the first failure
        retry_delay: Seconds to wait between retries

    Returns:
        NotebookLMUploadResult with operation results
    """
    # Check if integration is enabled
    if not settings.notebooklm_enabled:
        return NotebookLMUploadResult(
            success=False,
            errors=["NotebookLM integration is disabled"]
        )
    
    # Setup
    auth_manager = NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile
    )
    
    # Check authentication
    try:
        await auth_manager.require_auth()
    except NotebookLMAuthRequiredError as e:
        return NotebookLMUploadResult(
            success=False,
            errors=[f"Authentication required: {e}"]
        )

    # Reason: proactively check session freshness before starting the
    # upload. If the session is stale, configure the refresh command so
    # notebooklm-py auto-refreshes via Playwright during the API call.
    try:
        from streamdoc.integrations.notebooklm.keepalive import configure_refresh_cmd
        status = await auth_manager.check_session_freshness()
        if not status.is_valid:
            logger.warning("Session stale before upload — configuring refresh: %s", status.message)
            configure_refresh_cmd(auth_manager)
    except Exception as exc:
        logger.debug("Pre-upload session check failed: %s", exc)
    
    # Use default content types if not specified
    if content_types is None:
        content_types = [
            ContentType(t.strip())
            for t in settings.notebooklm_default_content_types.split(",")
            if t.strip()
        ]
    
    # Reason: prompt resolution priority:
    # 1. prompt_template (template name) — highest priority
    # 2. custom_prompt (raw text from preset.prompt_md) — second priority
    # 3. settings.notebooklm_default_prompt — only when neither is set
    # This fixes the bug where the system default was ALWAYS injected even
    # when the user configured a custom prompt in the preset.
    logger.info(
        "NotebookLM prompt resolution: prompt_template=%r custom_prompt=%r chars",
        prompt_template, len(custom_prompt) if custom_prompt else 0,
    )
    if not prompt_template and not custom_prompt:
        prompt_template = settings.notebooklm_default_prompt
        logger.info("NotebookLM prompt fallback: using default template %r", prompt_template)
    elif prompt_template:
        logger.info("NotebookLM prompt using template: %r", prompt_template)
    else:
        logger.info(
            "NotebookLM prompt using custom_prompt (%d chars)",
            len(custom_prompt) if custom_prompt else 0,
        )
    
    prompts = PromptManager(
        settings.notebooklm_templates_dir,
        settings.notebooklm_sample_prompts_dir,
    )
    
    try:
        async with NotebookLMClientWrapper(auth_manager) as client:
            notebooks = NotebookManager(client)
            content_mgr = ContentManager(
                client,
                prompts,
                settings.notebooklm_default_wait_timeout
            )
            
            # Create or get notebook
            if notebook_id:
                # Use existing notebook
                try:
                    nb = await notebooks.get_notebook(notebook_id)
                except NotebookLMIntegrationError as e:
                    return NotebookLMUploadResult(
                        success=False,
                        errors=[f"Failed to get notebook '{notebook_id}': {e}"]
                    )
            else:
                # Create new notebook
                # Reason: each run creates a new dedicated notebook with a
                # new slide deck — this is the intended behavior. Different
                # runs produce different content and should NOT share a
                # notebook.
                timestamp = asyncio.get_event_loop().time()
                title = f"{preset_name} - {timestamp:.0f}"
                try:
                    nb = await notebooks.create_notebook(title)
                except NotebookLMIntegrationError as e:
                    return NotebookLMUploadResult(
                        success=False,
                        errors=[f"Failed to create notebook: {e}"]
                    )
            
            # Upload reports as sources
            sources = []
            upload_errors = []

            for i, report_path in enumerate(report_paths):
                # Reason: small delay between uploads to avoid hitting
                # NotebookLM's rate limit on source creation.
                if i > 0:
                    await asyncio.sleep(2)
                try:
                    source = await content_mgr.upload_report(
                        nb.id,
                        report_path,
                        title=report_path.stem
                    )
                    sources.append({
                        "id": source.id,
                        "title": source.title
                    })
                except Exception as e:
                    upload_errors.append(f"Failed to upload {report_path}: {e}")
            
            if not sources:
                return NotebookLMUploadResult(
                    success=False,
                    notebook_id=nb.id,
                    errors=["No reports uploaded"] + upload_errors
                )
            
            # Enable sharing to get URL
            # Reason: log failures so the user knows why the notebook link
            # is missing, instead of silently setting it to None.
            try:
                notebook_url = await notebooks.enable_sharing(nb.id, public=True)
            except Exception as exc:
                logger.warning("Failed to enable sharing for notebook %s: %s", nb.id, exc)
                notebook_url = None

            # Reason: wait for NotebookLM to process the uploaded sources
            # before starting content generation. Without this delay, the
            # generation can fail because the sources aren't indexed yet.
            if sources:
                logger.info("Waiting 5s for source indexing before generation...")
                await asyncio.sleep(5)

            # Generate content
            output_dir = Path(settings.output_root) / "notebooklm" / nb.id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            batch_result = await content_mgr.batch_generate(
                nb.id,
                content_types,
                output_dir,
                prompt_template,
                custom_prompt=custom_prompt,
                notebook_url=notebook_url or "",
                retry_generation=retry_generation,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
            )
            
            # Register for retention tracking.
            # Reason: always track notebooks for retention so the cleanup
            # task can delete them when they expire. When the caller does not
            # provide a db_session (the common case from the fetch pipeline),
            # open a short-lived session here.
            if not is_permanent:
                try:
                    from streamdoc.db import session_scope as _session_scope
                    effective_hours = retention_hours or settings.notebooklm_default_retention_hours

                    # Reason: use the provided session or open a new one.
                    # When opening our own session we must NOT commit inside
                    # the `async with` block because the session_scope context
                    # manager handles commit/rollback on exit.
                    if db_session is not None:
                        retention = RetentionManager(client, db_session, effective_hours)
                        content_record = retention.register_notebook(
                            notebook_id=nb.id,
                            title=nb.title,
                            preset_name=preset_name,
                            job_id=job_id,
                            is_permanent=is_permanent,
                            retention_hours=effective_hours,
                            share_url=notebook_url,
                        )
                        for result in batch_result.results:
                            if result.status == "completed":
                                retention.register_artifact(
                                    content_id=content_record.id,
                                    artifact_type=result.content_type.value,
                                    artifact_id=result.artifact_id,
                                    local_path=result.local_path,
                                )
                    else:
                        with _session_scope() as _ret_session:
                            retention = RetentionManager(client, _ret_session, effective_hours)
                            content_record = retention.register_notebook(
                                notebook_id=nb.id,
                                title=nb.title,
                                preset_name=preset_name,
                                job_id=job_id,
                                is_permanent=is_permanent,
                                retention_hours=effective_hours,
                                share_url=notebook_url,
                            )
                            for result in batch_result.results:
                                if result.status == "completed":
                                    retention.register_artifact(
                                        content_id=content_record.id,
                                        artifact_type=result.content_type.value,
                                        artifact_id=result.artifact_id,
                                        local_path=result.local_path,
                                    )
                except Exception as e:
                    batch_result.errors.append(f"Retention tracking failed: {e}")
            
            all_errors = upload_errors + batch_result.errors

            # Reason: save pending generations to DB so the background poller
            # can check their status and download artifacts when ready.
            # This handles the case where generation times out but is still
            # running on NotebookLM's side.
            from datetime import datetime, timezone
            from streamdoc.db import session_scope
            from streamdoc.models.generation import Generation
            import uuid

            for result in batch_result.results:
                if result.status == "pending":
                    try:
                        gen_id = str(uuid.uuid4())
                        now_iso = datetime.now(timezone.utc).isoformat()
                        with session_scope() as db_s:
                            db_s.add(Generation(
                                id=gen_id,
                                job_id=job_id or "",
                                notebook_id=nb.id,
                                task_id=result.artifact_id or "",
                                content_type=result.content_type.value,
                                status="pending",
                                artifact_id="",
                                local_path="",
                                error="",
                                created_at=now_iso,
                                updated_at=now_iso,
                            ))
                        logger.info(
                            "Saved pending generation %s (task=%s, type=%s) for background polling",
                            gen_id, result.artifact_id, result.content_type.value,
                        )
                    except Exception as e:
                        logger.warning("Failed to save pending generation: %s", e)

            return NotebookLMUploadResult(
                success=len(batch_result.results) > 0 or not content_types,
                notebook_id=nb.id,
                notebook_url=notebook_url,
                sources=sources,
                generated_content=batch_result.results,
                errors=all_errors if all_errors else []
            )
            
    except NotebookLMIntegrationError as e:
        return NotebookLMUploadResult(
            success=False,
            errors=[str(e)]
        )
    except Exception as e:
        return NotebookLMUploadResult(
            success=False,
            errors=[f"Unexpected error: {e}"]
        )


async def upload_reports_simple(
    report_paths: list[Path],
    preset_name: str,
) -> NotebookLMUploadResult:
    """Simple upload function with default settings.
    
    This is a convenience wrapper for the most common use case:
    - Create new notebook
    - Upload reports
    - Generate default content types
    - Apply default retention
    
    Args:
        report_paths: List of report files to upload
        preset_name: Name of the preset
        
    Returns:
        NotebookLMUploadResult
    """
    return await upload_to_notebooklm(
        report_paths=report_paths,
        preset_name=preset_name,
        notebook_id=None,  # Create new
        content_types=None,  # Use defaults
        prompt_template=None,  # Use default
        is_permanent=False,
        retention_hours=None,  # Use default
    )
