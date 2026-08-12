"""Integrations package for StreamDoc.

This package contains integrations with external services.
"""

# NotebookLM integration (installed by default)
try:
    from streamdoc.integrations.notebooklm import (
        NotebookLMAuthManager,
        NotebookLMClientWrapper,
        NotebookManager,
        ContentManager,
        RetentionManager,
        PromptManager,
        ContentType,
    )
    NOTEBOOKLM_AVAILABLE = True
except ImportError:
    NOTEBOOKLM_AVAILABLE = False

__all__ = [
    "NOTEBOOKLM_AVAILABLE",
]

if NOTEBOOKLM_AVAILABLE:
    __all__.extend([
        "NotebookLMAuthManager",
        "NotebookLMClientWrapper",
        "NotebookManager",
        "ContentManager",
        "RetentionManager",
        "PromptManager",
        "ContentType",
    ])
