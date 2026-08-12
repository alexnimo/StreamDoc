"""Notebook operations for NotebookLM integration."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMIntegrationError,
    NotebookLMNotebookNotFoundError,
)

if TYPE_CHECKING:
    from notebooklm.types import Notebook
    from streamdoc.integrations.notebooklm.client import NotebookLMClientWrapper


@dataclass
class NotebookInfo:
    """Notebook information for display and tracking.
    
    Attributes:
        id: NotebookLM notebook ID
        title: Notebook title
        sources_count: Number of sources in the notebook
        artifacts_count: Number of artifacts (approximate)
        created_at: Creation timestamp (if available)
        share_url: Public share URL (if enabled)
    """
    id: str
    title: str
    sources_count: int = 0
    artifacts_count: int = 0
    created_at: datetime | None = None
    share_url: str | None = None


class NotebookManager:
    """High-level notebook operations.
    
    This class provides operations for creating, listing, and managing
    NotebookLM notebooks with proper error handling.
    
    Args:
        client_wrapper: NotebookLM client wrapper instance
    """
    
    def __init__(self, client_wrapper: "NotebookLMClientWrapper"):
        self.client_wrapper = client_wrapper
    
    def _notebook_to_info(self, notebook: "Notebook") -> NotebookInfo:
        """Convert NotebookLM Notebook to NotebookInfo."""
        return NotebookInfo(
            id=notebook.id,
            title=notebook.title,
            sources_count=getattr(notebook, "sources_count", 0),
            artifacts_count=getattr(notebook, "artifacts_count", 0),
            created_at=None,  # NotebookLM doesn't expose this directly
            share_url=None  # Must be fetched separately
        )
    
    async def list_notebooks(self) -> list[NotebookInfo]:
        """List all notebooks.
        
        Returns:
            List of NotebookInfo objects
            
        Raises:
            NotebookLMIntegrationError: If operation fails
        """
        try:
            notebooks = await self.client_wrapper.notebooks.list()
            return [self._notebook_to_info(nb) for nb in notebooks]
        except Exception as exc:
            raise NotebookLMIntegrationError(f"Failed to list notebooks: {exc}") from exc
    
    async def create_notebook(self, title: str) -> NotebookInfo:
        """Create a new notebook.
        
        Args:
            title: Notebook title
            
        Returns:
            NotebookInfo for the created notebook
            
        Raises:
            NotebookLMIntegrationError: If creation fails
        """
        try:
            notebook = await self.client_wrapper.notebooks.create(title)
            return self._notebook_to_info(notebook)
        except Exception as exc:
            raise NotebookLMIntegrationError(
                f"Failed to create notebook '{title}': {exc}"
            ) from exc
    
    async def get_notebook(self, notebook_id: str) -> NotebookInfo:
        """Get notebook details.
        
        Args:
            notebook_id: NotebookLM notebook ID
            
        Returns:
            NotebookInfo for the notebook
            
        Raises:
            NotebookLMNotebookNotFoundError: If notebook not found
            NotebookLMIntegrationError: For other errors
        """
        try:
            notebook = await self.client_wrapper.notebooks.get(notebook_id)
            return self._notebook_to_info(notebook)
        except Exception as exc:
            if "not found" in str(exc).lower() or "404" in str(exc):
                raise NotebookLMNotebookNotFoundError(
                    f"Notebook '{notebook_id}' not found"
                ) from exc
            raise NotebookLMIntegrationError(
                f"Failed to get notebook '{notebook_id}': {exc}"
            ) from exc
    
    async def delete_notebook(self, notebook_id: str) -> bool:
        """Delete a notebook.
        
        This is idempotent - returns True even if notebook didn't exist.
        
        Args:
            notebook_id: NotebookLM notebook ID
            
        Returns:
            True if notebook was deleted or didn't exist
            
        Raises:
            NotebookLMIntegrationError: If deletion fails for other reasons
        """
        try:
            await self.client_wrapper.notebooks.delete(notebook_id)
            return True
        except Exception as exc:
            if "not found" in str(exc).lower() or "404" in str(exc):
                return True  # Already deleted
            raise NotebookLMIntegrationError(
                f"Failed to delete notebook '{notebook_id}': {exc}"
            ) from exc
    
    async def rename_notebook(self, notebook_id: str, new_title: str) -> NotebookInfo:
        """Rename a notebook.
        
        Args:
            notebook_id: NotebookLM notebook ID
            new_title: New title for the notebook
            
        Returns:
            Updated NotebookInfo
            
        Raises:
            NotebookLMNotebookNotFoundError: If notebook not found
            NotebookLMIntegrationError: For other errors
        """
        try:
            notebook = await self.client_wrapper.notebooks.rename(notebook_id, new_title)
            return self._notebook_to_info(notebook)
        except Exception as exc:
            if "not found" in str(exc).lower() or "404" in str(exc):
                raise NotebookLMNotebookNotFoundError(
                    f"Notebook '{notebook_id}' not found"
                ) from exc
            raise NotebookLMIntegrationError(
                f"Failed to rename notebook '{notebook_id}': {exc}"
            ) from exc
    
    async def get_share_url(self, notebook_id: str) -> str | None:
        """Get share URL for a notebook.
        
        Note: This requires the notebook to have sharing enabled.
        
        Args:
            notebook_id: NotebookLM notebook ID
            
        Returns:
            Share URL if available, None otherwise
            
        Raises:
            NotebookLMIntegrationError: If operation fails
        """
        try:
            # Reason: get_share_url is sync (not a coroutine) — see
            # enable_sharing for details.
            url = self.client_wrapper.notebooks.get_share_url(notebook_id)
            return url
        except Exception as exc:
            # Sharing might not be enabled, return None rather than error
            if "share" in str(exc).lower() or "public" in str(exc).lower():
                return None
            raise NotebookLMIntegrationError(
                f"Failed to get share URL for '{notebook_id}': {exc}"
            ) from exc
    
    async def enable_sharing(self, notebook_id: str, public: bool = True) -> str:
        """Enable sharing for a notebook and return share URL.
        
        Args:
            notebook_id: NotebookLM notebook ID
            public: Whether to make publicly accessible
            
        Returns:
            Share URL
            
        Raises:
            NotebookLMIntegrationError: If sharing setup fails
        """
        try:
            # Reason: sharing.set_public() is async — enables public
            # sharing for the notebook.
            await self.client_wrapper.sharing.set_public(notebook_id, public=public)
            # Reason: get_share_url is a SYNC method (not a coroutine) —
            # it builds the URL from the notebook ID without an API call.
            # The previous code awaited it, causing
            # "TypeError: object str can't be used in 'await' expression".
            url = self.client_wrapper.notebooks.get_share_url(notebook_id)
            return url or ""
        except Exception as exc:
            raise NotebookLMIntegrationError(
                f"Failed to enable sharing for '{notebook_id}': {exc}"
            ) from exc
    
    async def search_notebooks(
        self,
        query: str,
        limit: int = 20
    ) -> list[NotebookInfo]:
        """Search notebooks by title (client-side filtering).
        
        Args:
            query: Search query string
            limit: Maximum results to return
            
        Returns:
            List of matching NotebookInfo objects
        """
        all_notebooks = await self.list_notebooks()
        query_lower = query.lower()
        
        matching = [
            nb for nb in all_notebooks
            if query_lower in nb.title.lower()
        ]
        
        return matching[:limit]
    
    async def get_or_create_notebook(
        self,
        notebook_id: str | None,
        title: str | None = None
    ) -> NotebookInfo:
        """Get existing notebook or create new one.
        
        This is a convenience method for the common pattern of:
        - If notebook_id provided, get that notebook
        - Otherwise, create a new notebook with the given title
        
        Args:
            notebook_id: Existing notebook ID (optional)
            title: Title for new notebook (required if notebook_id is None)
            
        Returns:
            NotebookInfo for existing or new notebook
            
        Raises:
            ValueError: If notebook_id is None and title is not provided
            NotebookLMNotebookNotFoundError: If notebook_id provided but not found
        """
        if notebook_id:
            return await self.get_notebook(notebook_id)
        
        if not title:
            raise ValueError("Either notebook_id or title must be provided")
        
        return await self.create_notebook(title)
