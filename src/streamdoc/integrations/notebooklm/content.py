"""Content generation and download for NotebookLM integration."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMContentNotFoundError,
    NotebookLMGenerationError,
    NotebookLMIntegrationError,
    NotebookLMSourceError,
)
from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

if TYPE_CHECKING:
    from notebooklm.types import Source
    from streamdoc.integrations.notebooklm.client import NotebookLMClientWrapper

logger = logging.getLogger(__name__)


def _artifact_type_name(type_code: int) -> str:
    """Convert an artifact type int code to a readable name.

    Args:
        type_code: Integer artifact type code from notebooklm-py's
            ArtifactTypeCode enum (e.g. 1=AUDIO, 2=REPORT, 8=SLIDE_DECK).

    Returns:
        Human-readable type name (e.g. "SLIDE_DECK", "AUDIO").
    """
    try:
        from notebooklm._artifact.polling import _get_artifact_type_name as _lookup
        return _lookup(type_code)
    except Exception:
        return str(type_code)


def _artifact_status_name(status_code: int) -> str:
    """Convert an artifact status int code to a readable name.

    Args:
        status_code: Integer status code from notebooklm-py.

    Returns:
        Human-readable status name (e.g. "completed", "in_progress").
    """
    try:
        from notebooklm._types import artifacts as _artifact_mod

        _to_str = getattr(_artifact_mod, "artifact_status_to_str", None)
        if callable(_to_str):
            return _to_str(status_code)  # type: ignore[no-any-return]
    except Exception:
        pass
    return str(status_code)



@dataclass
class SourceInfo:
    """Source (uploaded document) information.
    
    Attributes:
        id: Source ID in NotebookLM
        title: Source title
        status: Processing status (e.g., "READY", "PROCESSING")
        notebook_id: Parent notebook ID
    """
    id: str
    title: str
    status: str
    notebook_id: str


@dataclass
class GenerationResult:
    """Result of content generation request.
    
    Attributes:
        task_id: Generation task ID for polling
        artifact_id: Artifact ID (available after completion)
        status: Current generation status
        content_type: Type of content being generated
        notebook_id: Parent notebook ID
        error: Error message if status is "failed"
    """
    task_id: str
    artifact_id: str | None
    status: str  # "pending", "in_progress", "completed", "failed"
    content_type: ContentType
    notebook_id: str
    error: str = ""


@dataclass
class ContentResult:
    """Complete content result with local download.
    
    Attributes:
        content_type: Type of content
        artifact_id: Artifact ID in NotebookLM
        notebook_id: Parent notebook ID
        notebook_url: URL to view in NotebookLM
        local_path: Local file path if downloaded
        title: Content title
        status: Final status
        error: Error message if status is "failed"
    """
    content_type: ContentType
    artifact_id: str
    notebook_id: str
    notebook_url: str
    local_path: Path | None
    title: str
    status: str = "completed"
    error: str = ""


@dataclass
class BatchContentResult:
    """Result of batch content generation.
    
    Attributes:
        notebook_id: Parent notebook ID
        notebook_url: URL to view notebook
        results: List of individual content results
        errors: List of any errors that occurred
    """
    notebook_id: str
    notebook_url: str
    results: list[ContentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ContentManager:
    """Manages content generation and download.
    
    This class handles uploading sources, generating content artifacts
    (slide decks, podcasts, infographics, reports), and downloading
    the generated content locally.
    
    Args:
        client_wrapper: NotebookLM client wrapper
        prompts: Prompt template manager
        default_wait_timeout: Default timeout for generation waiting
    """
    
    def __init__(
        self,
        client_wrapper: "NotebookLMClientWrapper",
        prompts: PromptManager | None = None,
        default_wait_timeout: float = 300.0
    ):
        self.client_wrapper = client_wrapper
        self.prompts = prompts or PromptManager()
        self.default_wait_timeout = default_wait_timeout
    
    async def generate_content(
        self,
        notebook_id: str,
        content_type: ContentType,
        prompt: str | None = None,
        title: str | None = None,
        wait: bool = True,
        retry_generation: bool = True,
        retry_attempts: int = 1,
        retry_delay: float = 300.0,
    ) -> GenerationResult:
        """Generate content artifact with optional retry on failure.

        Args:
            notebook_id: Target notebook ID
            content_type: Type of content to generate
            prompt: Custom prompt (uses default if not provided)
            title: Custom title for the artifact (unused by notebooklm-py API)
            wait: Whether to wait for completion
            retry_generation: Whether to retry if generation fails
            retry_attempts: Number of extra attempts after the first failure
            retry_delay: Seconds to wait between retries

        Returns:
            GenerationResult with task/artifact info

        Raises:
            NotebookLMGenerationError: If generation fails after all retries
        """
        attempts = 1 + retry_attempts if retry_generation else 1
        last_error = ""
        for attempt in range(attempts):
            try:
                result = await self._attempt_generation(
                    notebook_id, content_type, prompt=prompt, title=title, wait=wait
                )
            except NotebookLMGenerationError as exc:
                last_error = str(exc)
                if attempt < attempts - 1:
                    logger.warning(
                        "Generation failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, attempts, last_error, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise

            if result.status == "failed":
                last_error = result.error or "Generation failed"
                if attempt < attempts - 1:
                    logger.warning(
                        "Generation failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, attempts, last_error, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    continue

            return result

        # All attempts exhausted
        return GenerationResult(
            task_id="",
            artifact_id=None,
            status="failed",
            content_type=content_type,
            notebook_id=notebook_id,
            error=last_error,
        )

    def _source_to_info(self, source: "Source", notebook_id: str) -> SourceInfo:
        """Convert NotebookLM Source to SourceInfo."""
        # Reason: source.status is a SourceStatus enum (int), not a string.
        # Convert to a readable name for display/tracking.
        status = getattr(source, "status", None)
        if status is not None:
            try:
                status = status.name  # enum member name like "READY"
            except AttributeError:
                status = str(status)
        else:
            status = "UNKNOWN"
        return SourceInfo(
            id=source.id,
            title=source.title or source.id,
            status=status,
            notebook_id=notebook_id
        )
    
    async def upload_report(
        self,
        notebook_id: str,
        report_path: Path,
        title: str | None = None
    ) -> SourceInfo:
        """Upload a report file as a source to a notebook.
        
        Args:
            notebook_id: Target notebook ID
            report_path: Path to report file (.md, .pdf, etc.)
            title: Source title (defaults to filename)
            
        Returns:
            SourceInfo for the uploaded source
            
        Raises:
            NotebookLMSourceError: If upload fails
        """
        if not report_path.exists():
            raise NotebookLMSourceError(f"Report file not found: {report_path}")
        
        title = title or report_path.stem
        
        try:
            source = await self.client_wrapper.sources.add_file(
                notebook_id,
                str(report_path),
                title=title,
                wait=True,  # Wait for processing
                wait_timeout=120.0
            )
            return self._source_to_info(source, notebook_id)
        except Exception as exc:
            raise NotebookLMSourceError(
                f"Failed to upload report '{report_path}': {exc}"
            ) from exc
    
    async def upload_text(
        self,
        notebook_id: str,
        content: str,
        title: str
    ) -> SourceInfo:
        """Upload text content as a source.
        
        Args:
            notebook_id: Target notebook ID
            content: Text content to upload
            title: Source title
            
        Returns:
            SourceInfo for the uploaded source
        """
        try:
            source = await self.client_wrapper.sources.add_text(
                notebook_id,
                title,
                content,
                wait=True,
                wait_timeout=120.0
            )
            return self._source_to_info(source, notebook_id)
        except Exception as exc:
            raise NotebookLMSourceError(
                f"Failed to upload text content: {exc}"
            ) from exc
    
    async def upload_url(
        self,
        notebook_id: str,
        url: str
    ) -> SourceInfo:
        """Add a URL as a source.
        
        Args:
            notebook_id: Target notebook ID
            url: URL to add (e.g., YouTube URL)
            
        Returns:
            SourceInfo for the added source
        """
        try:
            source = await self.client_wrapper.sources.add_url(
                notebook_id,
                url,
                wait=True,
                wait_timeout=120.0
            )
            return self._source_to_info(source, notebook_id)
        except Exception as exc:
            raise NotebookLMSourceError(
                f"Failed to add URL '{url}': {exc}"
            ) from exc
    
    async def upload_multiple_reports(
        self,
        notebook_id: str,
        report_paths: list[Path]
    ) -> list[SourceInfo]:
        """Upload multiple reports in parallel.
        
        Args:
            notebook_id: Target notebook ID
            report_paths: List of report file paths
            
        Returns:
            List of SourceInfo for uploaded sources
        """
        tasks = [
            self.upload_report(notebook_id, path)
            for path in report_paths
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        sources = []
        for result in results:
            if isinstance(result, Exception):
                # Log error but continue with other uploads
                continue
            sources.append(result)
        
        return sources
    
    async def _attempt_generation(
        self,
        notebook_id: str,
        content_type: ContentType,
        prompt: str | None = None,
        title: str | None = None,
        wait: bool = True
    ) -> GenerationResult:
        """Single attempt to generate content artifact.
        
        Args:
            notebook_id: Target notebook ID
            content_type: Type of content to generate
            prompt: Custom prompt (uses default if not provided)
            title: Custom title for the artifact (unused by notebooklm-py API;
                kept for interface compatibility)
            wait: Whether to wait for completion
            
        Returns:
            GenerationResult with task/artifact info
            
        Raises:
            NotebookLMGenerationError: If generation fails
        """
        try:
            # Reason: log the prompt that will be sent to NotebookLM so the
            # user can verify injection. Without this, prompt delivery is a
            # black box — there's no way to confirm what was actually sent.
            # Truncate to 500 chars for readability; full prompt is available
            # at DEBUG level.
            if prompt:
                logger.info(
                    "Generating %s for notebook %s with prompt (%d chars)",
                    content_type.value, notebook_id, len(prompt),
                )
                logger.debug("Full prompt for %s:\n%s", content_type.value, prompt)
            else:
                logger.info(
                    "Generating %s for notebook %s with NO prompt (default)",
                    content_type.value, notebook_id,
                )

            # Reason: notebooklm-py's generate_* methods use `instructions=`
            # (not `custom_instructions=`) and have no `title` parameter.
            # generate_report uses `custom_prompt=` for the full prompt and
            # `extra_instructions=` for appended text.
            #
            # Reason: NotebookLM can rate-limit artifact creation
            # (RateLimitError, rpc_code=USER_DISPLAYABLE_ERROR) when
            # multiple content types are generated in parallel or when
            # the same notebook is used repeatedly. We retry with
            # exponential backoff to handle transient rate limits.
            max_retries = 3
            for attempt in range(max_retries + 1):
                try:
                    if content_type == ContentType.SLIDE_DECK:
                        result = await self.client_wrapper.artifacts.generate_slide_deck(
                            notebook_id,
                            instructions=prompt
                        )
                    elif content_type == ContentType.PODCAST:
                        result = await self.client_wrapper.artifacts.generate_audio(
                            notebook_id,
                            instructions=prompt
                        )
                    elif content_type == ContentType.INFOGRAPHIC:
                        result = await self.client_wrapper.artifacts.generate_infographic(
                            notebook_id,
                            instructions=prompt
                        )
                    elif content_type == ContentType.REPORT:
                        result = await self.client_wrapper.artifacts.generate_report(
                            notebook_id,
                            custom_prompt=prompt
                        )
                    else:
                        raise NotebookLMGenerationError(f"Unsupported content type: {content_type}")
                    break  # Reason: success — exit retry loop
                except Exception as gen_exc:
                    exc_msg = str(gen_exc).lower()
                    exc_type = type(gen_exc).__name__
                    is_rate_limit = "RateLimit" in exc_type or "rate" in exc_msg
                    # Reason: "daily limit" is NOT a transient rate limit —
                    # it won't reset in seconds. Detect it by checking for
                    # "daily" or "limit" + "slides"/"come back" in the message.
                    is_daily_limit = (
                        "daily" in exc_msg
                        or ("limit" in exc_msg and "slide" in exc_msg)
                        or "come back later" in exc_msg
                    )
                    if is_daily_limit:
                        logger.warning(
                            "Daily limit reached for %s generation: %s",
                            content_type.value, gen_exc,
                        )
                        # Reason: return a failed result instead of raising
                        # so the caller can mark the job as "partial" rather
                        # than failing the entire job.
                        return GenerationResult(
                            task_id="",
                            artifact_id="",
                            status="failed",
                            content_type=content_type,
                            notebook_id=notebook_id,
                            error=f"Daily limit reached for {content_type.value}. Try again later.",
                        )
                    if attempt < max_retries and is_rate_limit:
                        wait_sec = (2 ** attempt) * 5  # Reason: 5s, 10s, 20s
                        logger.warning(
                            "RateLimitError on %s generation (attempt %d/%d), retrying in %ds: %s",
                            content_type.value, attempt + 1, max_retries + 1, wait_sec, gen_exc,
                        )
                        await asyncio.sleep(wait_sec)
                        continue
                    raise  # Reason: non-retryable or max retries exceeded

            # Reason: if the server already rejected the generation, don't
            # try to wait or download. Return the real error immediately so
            # callers see the actual reason (e.g. "Generation failed on
            # NotebookLM") instead of a generic "Generation failed". Use
            # status string as fallback for objects without the is_failed
            # / is_removed helpers.
            if (
                getattr(result, "is_failed", False)
                or getattr(result, "is_removed", False)
                or result.status in ("failed", "removed")
            ):
                return GenerationResult(
                    task_id=result.task_id,
                    artifact_id=getattr(result, "artifact_id", None),
                    status="failed",
                    content_type=content_type,
                    notebook_id=notebook_id,
                    error=getattr(result, "error", None) or "Generation failed",
                )

            gen_result = GenerationResult(
                task_id=result.task_id,
                artifact_id=getattr(result, "artifact_id", None),
                status="in_progress",
                content_type=content_type,
                notebook_id=notebook_id,
            )

            if wait and result.task_id:
                # Wait for completion
                # Reason: on timeout, don't fail — return "pending" status
                # with the task_id so a background poller can check later.
                # Long generations (e.g., 10 videos × 20 min) can exceed
                # any reasonable blocking timeout.
                try:
                    final_status = await self.client_wrapper.artifacts.wait_for_completion(
                        notebook_id,
                        result.task_id,
                        timeout=self.default_wait_timeout
                    )
                    # Reason: propagate NotebookLM's final status and error.
                    # 'removed' means the artifact was delisted (often a quota
                    # rejection), so treat it as a failed generation.
                    if (
                        getattr(final_status, "is_failed", False)
                        or getattr(final_status, "is_removed", False)
                        or final_status.status in ("failed", "removed")
                    ):
                        gen_result.status = "failed"
                        gen_result.error = getattr(final_status, "error", None) or "Generation failed on NotebookLM"
                    else:
                        gen_result.status = final_status.status.lower()
                        gen_result.error = getattr(final_status, "error", None) or ""
                    # Reason: after completion, the artifact_id may be available
                    # in metadata, or we can use the task_id as a fallback
                    # identifier for listing/download operations.
                    if final_status.metadata:
                        gen_result.artifact_id = (
                            final_status.metadata.get("artifact_id")
                            or final_status.metadata.get("id")
                            or gen_result.artifact_id
                        )
                    # If still no artifact_id, use task_id — notebooklm-py
                    # download methods accept artifact_id=None and will find
                    # the latest artifact of that type.
                    if not gen_result.artifact_id:
                        gen_result.artifact_id = final_status.task_id
                except TimeoutError:
                    # Reason: generation is still running on NotebookLM's side.
                    # Return "pending" so the caller can save the task_id and
                    # a background poller can check status later.
                    gen_result.status = "pending"
                    gen_result.artifact_id = result.task_id

            return gen_result
            
        except Exception as exc:
            raise NotebookLMGenerationError(
                f"Failed to generate {content_type}: {exc}"
            ) from exc
    
    async def download_content(
        self,
        notebook_id: str,
        artifact_id: str,
        content_type: ContentType,
        output_dir: Path,
        filename: str | None = None
    ) -> Path:
        """Download generated content to local storage.
        
        Args:
            notebook_id: Parent notebook ID
            artifact_id: Artifact ID to download
            content_type: Type of content
            output_dir: Directory to save file
            filename: Custom filename (auto-generated if not provided)
            
        Returns:
            Path to downloaded file
            
        Raises:
            NotebookLMContentNotFoundError: If artifact not found
            NotebookLMIntegrationError: If download fails
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine file extension
        # Reason: notebooklm-py defaults to PDF for slide decks; PPTX
        # requires output_format='pptx'. We use PDF as the default to
        # match the API's default behavior.
        extensions = {
            ContentType.SLIDE_DECK: ".pdf",
            ContentType.PODCAST: ".mp3",
            ContentType.INFOGRAPHIC: ".png",
            ContentType.REPORT: ".md"
        }
        ext = extensions.get(content_type, ".bin")
        
        if not filename:
            # Reason: artifact_id may be None (download latest of type);
            # use "latest" as a readable fallback in the filename.
            id_part = artifact_id or "latest"
            filename = f"{content_type.value}_{id_part}{ext}"
        
        output_path = output_dir / filename
        
        try:
            # Reason: notebooklm-py download methods take args as
            # (notebook_id, output_path, artifact_id=None) — NOT
            # (notebook_id, artifact_id, output_path). artifact_id is
            # optional; if None, the latest artifact of that type is used.
            if content_type == ContentType.SLIDE_DECK:
                await self.client_wrapper.artifacts.download_slide_deck(
                    notebook_id, str(output_path), artifact_id=artifact_id
                )
            elif content_type == ContentType.PODCAST:
                await self.client_wrapper.artifacts.download_audio(
                    notebook_id, str(output_path), artifact_id=artifact_id
                )
            elif content_type == ContentType.INFOGRAPHIC:
                await self.client_wrapper.artifacts.download_infographic(
                    notebook_id, str(output_path), artifact_id=artifact_id
                )
            elif content_type == ContentType.REPORT:
                await self.client_wrapper.artifacts.download_report(
                    notebook_id, str(output_path), artifact_id=artifact_id
                )
            else:
                raise NotebookLMContentNotFoundError(
                    f"Download not supported for content type: {content_type}"
                )
            
            # Reason: notebooklm-py may return without raising even when
            # the download silently fails (e.g., artifact not yet ready).
            # Verify the file actually exists and is non-empty before
            # returning the path — otherwise callers store a phantom path
            # that doesn't point to a real file.
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise NotebookLMIntegrationError(
                    f"Download completed but file is missing or empty: {output_path}"
                )
            return output_path
            
        except Exception as exc:
            if "not found" in str(exc).lower():
                raise NotebookLMContentNotFoundError(
                    f"Artifact '{artifact_id}' not found"
                ) from exc
            raise NotebookLMIntegrationError(
                f"Failed to download content: {exc}"
            ) from exc
    
    async def generate_and_download(
        self,
        notebook_id: str,
        content_type: ContentType,
        output_dir: Path,
        prompt_template: str | None = None,
        prompt_variables: dict | None = None,
        custom_prompt: str | None = None,
        title: str | None = None,
        notebook_url: str | None = None,
        retry_generation: bool = True,
        retry_attempts: int = 1,
        retry_delay: float = 300.0,
    ) -> ContentResult:
        """Generate content and download it locally.
        
        This is a convenience method that combines generation and download.
        
        Reason: prompt resolution priority:
        1. prompt_template (template name) — rendered via PromptManager
        2. custom_prompt (raw text) — passed directly as the prompt string
        3. None — NotebookLM uses its built-in default
        
        Args:
            notebook_id: Target notebook ID
            content_type: Type of content
            output_dir: Directory to save downloaded file
            prompt_template: Name of prompt template to use (highest priority)
            prompt_variables: Variables for prompt template
            custom_prompt: Raw prompt text (second priority, used when
                prompt_template is None)
            title: Custom title
            notebook_url: Pre-computed notebook URL
            retry_generation: Whether to retry if generation fails
            retry_attempts: Number of extra attempts after the first failure
            retry_delay: Seconds to wait between retries

        Returns:
            ContentResult with local path and URLs
        """
        # Render prompt if template specified
        prompt = None
        if prompt_template:
            logger.info(
                "Rendering prompt template '%s' for %s generation",
                prompt_template, content_type.value,
            )
            prompt = self.prompts.render_prompt(
                prompt_template,
                content_type,
                **(prompt_variables or {})
            )
        elif custom_prompt:
            # Reason: use the raw prompt text from the preset's prompt_md
            # field. This is passed directly to NotebookLM as instructions.
            logger.info(
                "Using custom prompt (%d chars) for %s generation",
                len(custom_prompt), content_type.value,
            )
            prompt = custom_prompt
        else:
            logger.info(
                "No prompt specified for %s — NotebookLM will use its default",
                content_type.value,
            )
        
        # Generate content
        gen_result = await self.generate_content(
            notebook_id,
            content_type,
            prompt=prompt,
            title=title,
            wait=True,
            retry_generation=retry_generation,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
        )
        
        if gen_result.status == "failed":
            return ContentResult(
                content_type=content_type,
                artifact_id=gen_result.artifact_id or "",
                notebook_id=notebook_id,
                notebook_url=notebook_url or "",
                local_path=None,
                title=title or f"{content_type.value}",
                status="failed",
                error=gen_result.error or "Generation failed",
            )

        # Reason: if generation timed out, return "pending" status with
        # the task_id. The background poller will check and download later.
        if gen_result.status == "pending":
            return ContentResult(
                content_type=content_type,
                artifact_id=gen_result.artifact_id or "",
                notebook_id=notebook_id,
                notebook_url=notebook_url or "",
                local_path=None,
                title=title or f"{content_type.value}",
                status="pending"
            )
        
        # Download content
        # Reason: gen_result.artifact_id may be a task_id fallback (not a
        # real artifact ID) if metadata didn't contain one. Try with the
        # ID first; if that fails, retry with artifact_id=None which tells
        # notebooklm-py to download the latest artifact of that type.
        local_path = None
        download_error = ""
        try:
            local_path = await self.download_content(
                notebook_id,
                gen_result.artifact_id,
                content_type,
                output_dir
            )
        except Exception as exc1:
            download_error = str(exc1)
            try:
                local_path = await self.download_content(
                    notebook_id,
                    None,
                    content_type,
                    output_dir
                )
                download_error = ""  # Reason: retry succeeded
            except Exception as exc2:
                local_path = None
                download_error = str(exc2)
        
        # Reason: if download failed, return "failed" status (not "completed")
        # so the caller knows the content was not saved locally. The previous
        # code always returned "completed" even when local_path was None,
        # causing the job to show a phantom success.
        if local_path is None:
            return ContentResult(
                content_type=content_type,
                artifact_id=gen_result.artifact_id or "",
                notebook_id=notebook_id,
                notebook_url=notebook_url or "",
                local_path=None,
                title=title or f"{content_type.value}",
                status="failed",
                error=f"Generation succeeded but download failed: {download_error}",
            )
        
        return ContentResult(
            content_type=content_type,
            artifact_id=gen_result.artifact_id,
            notebook_id=notebook_id,
            notebook_url=notebook_url or "",
            local_path=local_path,
            title=title or f"{content_type.value}",
            status="completed"
        )
    
    async def batch_generate(
        self,
        notebook_id: str,
        content_types: list[ContentType],
        output_dir: Path,
        prompt_template: str | None = None,
        custom_prompt: str | None = None,
        notebook_url: str | None = None,
        retry_generation: bool = True,
        retry_attempts: int = 1,
        retry_delay: float = 300.0,
    ) -> BatchContentResult:
        """Generate multiple content types sequentially.

        Reason: generating in parallel triggers NotebookLM's rate
        limiting (RateLimitError, rpc_code=USER_DISPLAYABLE_ERROR).
        Sequential generation with a small delay between requests
        avoids this.

        Args:
            notebook_id: Target notebook ID
            content_types: List of content types to generate
            output_dir: Directory for downloads
            prompt_template: Prompt template name (highest priority)
            custom_prompt: Raw prompt text (second priority)
            notebook_url: Pre-computed notebook URL
            retry_generation: Whether to retry if a generation fails
            retry_attempts: Number of extra attempts after the first failure
            retry_delay: Seconds to wait between retries

        Returns:
            BatchContentResult with all results
        """
        content_results = []
        errors = []

        for i, content_type in enumerate(content_types):
            # Reason: small delay between generation requests to avoid
            # hitting NotebookLM's rate limit.
            if i > 0:
                await asyncio.sleep(3)
            try:
                result = await self.generate_and_download(
                    notebook_id,
                    content_type,
                    output_dir,
                    prompt_template,
                    custom_prompt=custom_prompt,
                    notebook_url=notebook_url,
                    retry_generation=retry_generation,
                    retry_attempts=retry_attempts,
                    retry_delay=retry_delay,
                )
                content_results.append(result)
            except Exception as exc:
                errors.append(str(exc))

        return BatchContentResult(
            notebook_id=notebook_id,
            notebook_url=notebook_url or "",
            results=content_results,
            errors=errors
        )
    
    async def delete_content(self, notebook_id: str, artifact_id: str) -> bool:
        """Delete generated content.
        
        Args:
            notebook_id: Parent notebook ID
            artifact_id: Artifact ID to delete
            
        Returns:
            True if deleted or not found
        """
        try:
            await self.client_wrapper.artifacts.delete(notebook_id, artifact_id)
            return True
        except Exception as exc:
            if "not found" in str(exc).lower():
                return True
            raise NotebookLMIntegrationError(
                f"Failed to delete artifact: {exc}"
            ) from exc
    
    async def list_content(
        self,
        notebook_id: str,
        content_type: ContentType | None = None
    ) -> list[dict]:
        """List generated content in a notebook.
        
        Args:
            notebook_id: Notebook ID
            content_type: Optional filter by type
            
        Returns:
            List of artifact info dictionaries
        """
        try:
            if content_type:
                type_methods = {
                    ContentType.SLIDE_DECK: self.client_wrapper.artifacts.list_slide_decks,
                    ContentType.PODCAST: self.client_wrapper.artifacts.list_audio,
                    ContentType.INFOGRAPHIC: self.client_wrapper.artifacts.list_infographics,
                    ContentType.REPORT: self.client_wrapper.artifacts.list_reports,
                }
                method = type_methods.get(content_type)
                if method:
                    artifacts = await method(notebook_id)
                else:
                    artifacts = []
            else:
                artifacts = await self.client_wrapper.artifacts.list(notebook_id)
            
            return [
                {
                    "id": a.id,
                    "title": getattr(a, "title", "Untitled"),
                    # Reason: Artifact stores type/status as int codes, not
                    # strings. Use the library's helper for status, and
                    # ArtifactType enum for type name.
                    "type": _artifact_type_name(getattr(a, "_artifact_type", 0)),
                    "status": _artifact_status_name(getattr(a, "status", 0)),
                }
                for a in artifacts
            ]
        except Exception as exc:
            raise NotebookLMIntegrationError(
                f"Failed to list content: {exc}"
            ) from exc
