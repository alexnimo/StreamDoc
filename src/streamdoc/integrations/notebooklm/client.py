"""Client wrapper for NotebookLM integration."""

import os
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from streamdoc.config import settings
from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager, SessionStatus
from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMAuthRequiredError,
    NotebookLMIntegrationError,
)

if TYPE_CHECKING:
    from notebooklm.client import (  # type: ignore[attr-defined]
        ArtifactsAPI,
        ChatAPI,
        LabelsAPI,
        MindMapsAPI,
        NotebookLMClient,
        NotebooksAPI,
        NotesAPI,
        ResearchAPI,
        SettingsAPI,
        SharingAPI,
        SourcesAPI,
    )

T = TypeVar("T")


class NotebookLMClientWrapper:
    """Wrapper around notebooklm-py client with StreamDoc integration.
    
    This wrapper provides:
    - Automatic authentication checking
    - Session freshness validation
    - Centralized error handling
    - Async context manager support
    
    Args:
        auth_manager: Authentication manager instance
        timeout: Request timeout in seconds
        auto_refresh: Whether to auto-refresh auth on expiry
    """
    
    def __init__(
        self,
        auth_manager: NotebookLMAuthManager,
        timeout: float = 30.0,
        auto_refresh: bool = True
    ):
        self.auth_manager = auth_manager
        self.timeout = timeout
        self.auto_refresh = auto_refresh
        self._client: "NotebookLMClient | None" = None
    
    async def __aenter__(self) -> "NotebookLMClientWrapper":
        """Enter async context, ensuring auth is valid."""
        await self.auth_manager.require_auth()

        # Opt in to notebooklm-py's built-in layer-3 headless re-auth so the
        # mid-RPC auth cascade can silently re-mint cookies when they expire.
        os.environ["NOTEBOOKLM_HEADLESS_REAUTH"] = "1"

        from notebooklm import NotebookLMClient

        storage_path = self.auth_manager.get_storage_path()
        keepalive_seconds = settings.notebooklm_keepalive_interval_minutes * 60
        # Reason: allow_headless=True is required in notebooklm-py 0.8.2+ for
        # the transport layer to permit mid-RPC headless re-auth when cookies
        # expire mid-operation (e.g. during a long upload). The env var alone
        # is not sufficient — the transport layer gates on this parameter first.
        self._client = await NotebookLMClient.from_storage(
            storage_path,
            timeout=self.timeout,
            keepalive=keepalive_seconds,
            keepalive_min_interval=60.0,
            allow_headless=True,
        ).__aenter__()
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context, cleaning up client."""
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
    
    def _ensure_client(self) -> "NotebookLMClient":
        """Ensure client is available.
        
        Raises:
            NotebookLMIntegrationError: If client not initialized
        """
        if self._client is None:
            raise NotebookLMIntegrationError(
                "Client not initialized. Use async context manager (async with)."
            )
        return self._client
    
    @property
    def notebooks(self) -> "NotebooksAPI":
        """Access notebooks API."""
        return self._ensure_client().notebooks
    
    @property
    def sources(self) -> "SourcesAPI":
        """Access sources API."""
        return self._ensure_client().sources
    
    @property
    def artifacts(self) -> "ArtifactsAPI":
        """Access artifacts API."""
        return self._ensure_client().artifacts
    
    @property
    def chat(self) -> "ChatAPI":
        """Access chat API."""
        return self._ensure_client().chat
    
    @property
    def research(self) -> "ResearchAPI":
        """Access research API."""
        return self._ensure_client().research
    
    @property
    def notes(self) -> "NotesAPI":
        """Access notes API."""
        return self._ensure_client().notes
    
    @property
    def mind_maps(self) -> "MindMapsAPI":
        """Access mind maps API."""
        return self._ensure_client().mind_maps
    
    @property
    def settings(self) -> "SettingsAPI":
        """Access settings API."""
        return self._ensure_client().settings
    
    @property
    def sharing(self) -> "SharingAPI":
        """Access sharing API."""
        return self._ensure_client().sharing
    
    @property
    def labels(self) -> "LabelsAPI":
        """Access labels API."""
        return self._ensure_client().labels
    
    async def with_auth_check(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Execute operation with authentication check and retry logic.
        
        This method:
        1. Checks authentication before operation
        2. Executes the operation
        3. Handles auth errors with optional refresh and retry
        
        Args:
            operation: Async callable to execute
            
        Returns:
            Result of operation
            
        Raises:
            NotebookLMAuthRequiredError: If auth fails and can't be refreshed
            NotebookLMIntegrationError: For other errors
        """
        try:
            return await operation()
        except Exception as exc:
            # Check if it's an auth error
            error_str = str(exc).lower()
            if any(x in error_str for x in ["auth", "token", "session", "unauthorized", "401"]):
                if self.auto_refresh:
                    client = self._client
                    if client is None:
                        raise NotebookLMIntegrationError(
                            "Client not initialized. Use async context manager (async with)."
                        ) from exc
                    # Try to refresh auth, explicitly allowing layer-3
                    # headless re-auth to re-mint cookies from the persistent
                    # browser profile when the session has expired.
                    try:
                        await client.refresh_auth(allow_headless=True)
                        return await operation()
                    except Exception as refresh_exc:
                        raise NotebookLMAuthRequiredError(
                            f"Authentication failed and refresh failed: {refresh_exc}"
                        ) from refresh_exc
                else:
                    raise NotebookLMAuthRequiredError(
                        f"Authentication required: {exc}"
                    ) from exc
            raise NotebookLMIntegrationError(f"Operation failed: {exc}") from exc
    
    async def check_health(self) -> SessionStatus:
        """Check client health and session status.
        
        Returns:
            SessionStatus with current session information
        """
        return await self.auth_manager.check_session_freshness()
