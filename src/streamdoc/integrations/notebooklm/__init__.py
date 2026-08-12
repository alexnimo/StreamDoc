"""NotebookLM integration for StreamDoc.

This package provides integration with NotebookLM via the notebooklm-py library,
enabling AI-powered content generation from processed YouTube videos.

Example:
    ```python
    from streamdoc.integrations.notebooklm import (
        NotebookLMClientWrapper,
        NotebookLMAuthManager,
        NotebookManager,
        ContentManager,
        RetentionManager,
        PromptManager,
    )
    from streamdoc.config import settings
    
    # Setup auth
    auth_manager = NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile
    )
    
    # Use client
    async with NotebookLMClientWrapper(auth_manager) as client:
        notebooks = NotebookManager(client)
        content = ContentManager(client)
        
        # List notebooks
        nb_list = await notebooks.list_notebooks()
        
        # Generate content
        result = await content.generate_and_download(
            notebook_id="abc123",
            content_type=ContentType.SLIDE_DECK,
            output_dir=Path("./output")
        )
    ```

External Library:
    This integration uses the notebooklm-py library:
    https://github.com/teng-lin/notebooklm-py
    
    Documentation:
    - Python API: https://github.com/teng-lin/notebooklm-py/blob/main/docs/python-api.md
    - CLI Reference: https://github.com/teng-lin/notebooklm-py/blob/main/docs/cli-reference.md
"""

from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager, SessionStatus
from streamdoc.integrations.notebooklm.client import NotebookLMClientWrapper
from streamdoc.integrations.notebooklm.content import (
    BatchContentResult,
    ContentManager,
    ContentResult,
    GenerationResult,
    SourceInfo,
)
from streamdoc.integrations.notebooklm.exceptions import (
    NotebookLMAuthRequiredError,
    NotebookLMContentNotFoundError,
    NotebookLMGenerationError,
    NotebookLMIntegrationError,
    NotebookLMNotebookNotFoundError,
    NotebookLMRateLimitError,
    NotebookLMRetentionError,
    NotebookLMSourceError,
)
from streamdoc.integrations.notebooklm.notebooks import NotebookInfo, NotebookManager
from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager, PromptTemplate
from streamdoc.integrations.notebooklm.retention import (
    CleanupReport,
    NotebookLMContent,
    NotebookLMRetentionLog,
    RetentionManager,
)

# Flag to indicate NotebookLM integration is available
NOTEBOOKLM_AVAILABLE = True

__all__ = [
    # Availability flag
    "NOTEBOOKLM_AVAILABLE",
    # Client and Auth
    "NotebookLMClientWrapper",
    "NotebookLMAuthManager",
    "SessionStatus",
    # Managers
    "NotebookManager",
    "ContentManager",
    "RetentionManager",
    "PromptManager",
    # Data classes
    "NotebookInfo",
    "SourceInfo",
    "GenerationResult",
    "ContentResult",
    "BatchContentResult",
    "PromptTemplate",
    "CleanupReport",
    # Enums
    "ContentType",
    # Database models
    "NotebookLMContent",
    "NotebookLMRetentionLog",
    # Exceptions
    "NotebookLMIntegrationError",
    "NotebookLMAuthRequiredError",
    "NotebookLMNotebookNotFoundError",
    "NotebookLMGenerationError",
    "NotebookLMRateLimitError",
    "NotebookLMContentNotFoundError",
    "NotebookLMSourceError",
    "NotebookLMRetentionError",
]
