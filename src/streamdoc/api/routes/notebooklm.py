"""NotebookLM integration routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import (
    NotebookLMAuthStatus,
    NotebookLMBatchRequest,
    NotebookLMCleanupRequest,
    NotebookLMCleanupResponse,
    NotebookLMContentGenerateRequest,
    NotebookLMContentOut,
    NotebookLMCookieLoginRequest,
    NotebookLMLoginRequest,
    NotebookLMLoginResponse,
    NotebookLMNotebookCreate,
    NotebookLMNotebookOut,
    NotebookLMRetentionExtendRequest,
    NotebookLMShareResponse,
    NotebookLMUploadRequest,
)
from streamdoc.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notebooklm", tags=["notebooklm"])


def _check_available():
    """Check if NotebookLM integration is available."""
    try:
        from streamdoc.integrations.notebooklm import NOTEBOOKLM_AVAILABLE
        if not NOTEBOOKLM_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="NotebookLM integration not available. Install with: pip install notebooklm-py",
            )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="NotebookLM integration not available.",
        )


def _get_auth_manager():
    from streamdoc.integrations.notebooklm import NotebookLMAuthManager
    return NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@router.get("/auth/status", response_model=NotebookLMAuthStatus)
async def auth_status():
    """Check NotebookLM authentication status."""
    _check_available()
    auth = _get_auth_manager()
    # Reason: the status endpoint is read-only; do not auto-launch a headless
    # browser here. Operations that actually need a client will trigger the
    # automatic re-capture through ``require_auth`` / ``check_session_freshness``.
    status = await auth.check_session_freshness(auto_refresh=False)
    return NotebookLMAuthStatus(
        profile=status.profile,
        storage_path=status.storage_path or "",
        configured=auth.is_configured(),
        is_valid=status.is_valid,
        is_fresh=status.is_fresh,
        message=status.message or "",
    )


@router.post("/auth/logout")
def auth_logout():
    """Clear stored NotebookLM credentials."""
    _check_available()
    auth = _get_auth_manager()
    deleted = auth.logout()
    return {"deleted": deleted}


@router.post("/auth/login", response_model=NotebookLMLoginResponse)
async def auth_login(body: NotebookLMLoginRequest):
    """Start interactive NotebookLM authentication.

    Opens a browser window for the user to log in to Google.
    Saves the session state for future API calls.
    """
    _check_available()

    try:

        auth = _get_auth_manager()
        success = await auth.login(headless=body.headless)

        if success:
            return NotebookLMLoginResponse(
                success=True,
                message="Authentication successful. Session saved.",
                storage_path=settings.notebooklm_storage_state_path,
            )
        else:
            return NotebookLMLoginResponse(
                success=False,
                message="Authentication failed or was cancelled.",
            )
    except Exception as exc:
        logger.exception("NotebookLM login failed")
        return NotebookLMLoginResponse(
            success=False,
            message=f"Login error: {exc}",
        )


@router.post("/auth/login-cookie", response_model=NotebookLMLoginResponse)
async def auth_login_cookie(body: NotebookLMCookieLoginRequest):
    """Authenticate NotebookLM using a Cookie header from the browser.

    Accepts a raw Cookie header string (e.g. copied from browser DevTools
    Network tab) and saves it as the NotebookLM session state.
    """
    _check_available()

    try:
        auth = _get_auth_manager()
        success = await auth.login_from_cookie_header(body.cookie_header)

        if success:
            return NotebookLMLoginResponse(
                success=True,
                message="Authentication successful. Session saved from cookies.",
                storage_path=settings.notebooklm_storage_state_path,
            )
        else:
            return NotebookLMLoginResponse(
                success=False,
                message="Cookie authentication failed.",
            )
    except Exception as exc:
        logger.exception("NotebookLM cookie login failed")
        return NotebookLMLoginResponse(
            success=False,
            message=f"Login error: {exc}",
        )


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------
@router.get("/notebooks", response_model=list[NotebookLMNotebookOut])
async def list_notebooks():
    """List all NotebookLM notebooks."""
    _check_available()
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        NotebookManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = NotebookManager(client)
            nbs = await mgr.list_notebooks()
            return [
                NotebookLMNotebookOut(id=nb.id, title=nb.title, sources_count=nb.sources_count)
                for nb in nbs
            ]
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/notebooks", response_model=NotebookLMNotebookOut)
async def create_notebook(body: NotebookLMNotebookCreate):
    """Create a new notebook."""
    _check_available()
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        NotebookManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = NotebookManager(client)
            nb = await mgr.create_notebook(body.title)
            return NotebookLMNotebookOut(id=nb.id, title=nb.title)
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """Delete a notebook."""
    _check_available()
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        NotebookManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = NotebookManager(client)
            await mgr.delete_notebook(notebook_id)
            return {"deleted": notebook_id}
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/notebooks/{notebook_id}/share", response_model=NotebookLMShareResponse)
async def share_notebook(notebook_id: str):
    """Enable sharing and get the share URL for a notebook."""
    _check_available()
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        NotebookManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = NotebookManager(client)
            url = await mgr.enable_sharing(notebook_id, public=True)
            return NotebookLMShareResponse(url=url)
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------
@router.post("/content/generate")
async def generate_content(body: NotebookLMContentGenerateRequest):
    """Generate content in a notebook."""
    _check_available()
    from pathlib import Path

    from streamdoc.integrations.notebooklm import (
        ContentManager,
        ContentType,
        NotebookLMClientWrapper,
        PromptManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    prompts = PromptManager(
        settings.notebooklm_templates_dir,
        settings.notebooklm_sample_prompts_dir,
    )
    # Reason: prompt resolution priority — template name > custom prompt > default
    prompt_name = body.prompt_template or None
    custom_prompt = body.custom_prompt or None
    if not prompt_name and not custom_prompt:
        prompt_name = settings.notebooklm_default_prompt

    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = ContentManager(client, prompts)
            ct = ContentType(body.content_type)

            if body.download:
                result = await mgr.generate_and_download(
                    body.notebook_id,
                    ct,
                    Path(body.output_dir),
                    prompt_name,
                    custom_prompt=custom_prompt,
                    title=body.title,
                )
                return {
                    "artifact_id": result.artifact_id,
                    "status": result.status,
                    "local_path": str(result.local_path) if result.local_path else None,
                }
            else:
                result = await mgr.generate_content(
                    body.notebook_id, ct, title=body.title, wait=body.wait,
                )
                return {
                    "task_id": result.task_id,
                    "status": result.status,
                    "artifact_id": result.artifact_id,
                }
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/batch")
async def batch_generate(body: NotebookLMBatchRequest):
    """Batch generate multiple content types."""
    _check_available()
    from pathlib import Path

    from streamdoc.integrations.notebooklm import (
        ContentManager,
        ContentType,
        NotebookLMClientWrapper,
        NotebookManager,
        PromptManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    prompts = PromptManager(
        settings.notebooklm_templates_dir,
        settings.notebooklm_sample_prompts_dir,
    )
    # Reason: prompt resolution priority — template name > custom prompt > default
    prompt_name = body.prompt_template or None
    custom_prompt = body.custom_prompt or None
    if not prompt_name and not custom_prompt:
        prompt_name = settings.notebooklm_default_prompt

    content_types = []
    for t in body.types.split(","):
        try:
            content_types.append(ContentType(t.strip()))
        except ValueError:
            pass

    if not content_types:
        raise HTTPException(status_code=400, detail="No valid content types specified")

    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = ContentManager(client, prompts)
            notebooks = NotebookManager(client)
            notebook_url = await notebooks.get_share_url(body.notebook_id) or ""

            result = await mgr.batch_generate(
                body.notebook_id,
                content_types,
                Path(body.output_dir),
                prompt_name,
                custom_prompt=custom_prompt,
                notebook_url=notebook_url,
            )
            return {
                "notebook_url": result.notebook_url,
                "results": [
                    {
                        "content_type": r.content_type.value,
                        "status": r.status,
                        "local_path": str(r.local_path) if r.local_path else None,
                    }
                    for r in result.results
                ],
                "errors": result.errors,
            }
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/upload")
async def upload_content(body: NotebookLMUploadRequest):
    """Upload a file as a source to a notebook."""
    _check_available()
    from pathlib import Path

    from streamdoc.integrations.notebooklm import (
        ContentManager,
        NotebookLMClientWrapper,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            mgr = ContentManager(client)
            source = await mgr.upload_report(
                body.notebook_id,
                Path(body.file_path),
                title=body.title,
            )
            return {
                "source_id": source.id,
                "title": source.title,
                "status": source.status,
            }
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
@router.get("/retention", response_model=list[NotebookLMContentOut])
def list_retention():
    """List tracked NotebookLM content with retention info."""
    _check_available()
    ensure_db()
    from streamdoc.db import session_scope
    from streamdoc.integrations.notebooklm.retention import NotebookLMContent

    with session_scope() as s:
        rows = s.query(NotebookLMContent).all()
        return [
            NotebookLMContentOut(
                id=r.id,
                notebook_id=r.notebook_id,
                notebook_title=r.notebook_title or "",
                preset_name=r.preset_name or "",
                status=r.status or "active",
                is_permanent=r.is_permanent,
                expires_at=r.expires_at.isoformat() if r.expires_at else None,
                artifacts=r.get_artifacts() if hasattr(r, "get_artifacts") else [],
            )
            for r in rows
        ]


@router.post("/retention/cleanup", response_model=NotebookLMCleanupResponse)
async def retention_cleanup(body: NotebookLMCleanupRequest):
    """Clean up expired NotebookLM content."""
    _check_available()
    ensure_db()
    from streamdoc.db import session_scope
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        RetentionManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            with session_scope() as s:
                mgr = RetentionManager(
                    client, s, settings.notebooklm_default_retention_hours,
                )
                report = await mgr.cleanup_expired(
                    dry_run=body.dry_run,
                    delete_remote=not body.skip_remote,
                )
                return NotebookLMCleanupResponse(
                    total_checked=report.total_checked,
                    deleted_notebooks=report.deleted_notebooks,
                    deleted_artifacts=report.deleted_artifacts,
                    deleted_local_files=report.deleted_local_files,
                    errors=report.errors,
                )
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/retention/{content_id}/extend")
async def extend_retention(content_id: str, body: NotebookLMRetentionExtendRequest):
    """Extend retention period for content."""
    _check_available()
    ensure_db()
    from streamdoc.db import session_scope
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        RetentionManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            with session_scope() as s:
                mgr = RetentionManager(
                    client, s, settings.notebooklm_default_retention_hours,
                )
                content = mgr.extend_retention(content_id, body.hours)
                return {
                    "id": content.id,
                    "expires_at": content.expires_at.isoformat() if content.expires_at else None,
                }
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/retention/{content_id}/permanent")
async def make_permanent(content_id: str):
    """Mark content as permanent (no retention)."""
    _check_available()
    ensure_db()
    from streamdoc.db import session_scope
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        RetentionManager,
    )
    from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError

    auth = _get_auth_manager()
    try:
        async with NotebookLMClientWrapper(auth) as client:
            with session_scope() as s:
                mgr = RetentionManager(
                    client, s, settings.notebooklm_default_retention_hours,
                )
                content = mgr.mark_permanent(content_id)
                return {
                    "id": content.id,
                    "notebook_title": content.notebook_title,
                    "is_permanent": True,
                }
    except NotebookLMIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/generations")
def list_generations(status: str | None = None, limit: int = 50):
    """List NotebookLM generation tasks and their statuses.

    Args:
        status: Optional filter (pending, in_progress, completed, failed).
        limit: Max records to return.

    Returns:
        List of generation records with status, task_id, content_type, etc.
    """
    ensure_db()

    from streamdoc.db import session_scope
    from streamdoc.models.generation import Generation

    with session_scope() as s:
        query = s.query(Generation)
        if status:
            query = query.filter(Generation.status == status)
        rows = query.order_by(Generation.created_at.desc()).limit(limit).all()

        # Reason: copy to dicts before session closes to avoid DetachedInstanceError
        return [
            {
                "id": r.id,
                "job_id": r.job_id,
                "notebook_id": r.notebook_id,
                "task_id": r.task_id,
                "content_type": r.content_type,
                "status": r.status,
                "artifact_id": r.artifact_id,
                "local_path": r.local_path,
                "error": r.error,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]


@router.post("/generations/poll")
async def poll_generations_now():
    """Manually trigger a poll of pending generations.

    Useful for testing or when the user wants to check immediately
    without waiting for the 30s background interval.
    """
    ensure_db()

    from streamdoc.integrations.notebooklm.poller import poll_pending_generations

    try:
        await poll_pending_generations()
        return {"message": "Poll completed"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
