"""Exceptions for NotebookLM integration."""


class NotebookLMIntegrationError(Exception):
    """Base exception for NotebookLM integration."""
    pass


class NotebookLMAuthRequiredError(NotebookLMIntegrationError):
    """Raised when valid authentication is required but not available."""
    pass


class NotebookLMNotebookNotFoundError(NotebookLMIntegrationError):
    """Raised when a notebook ID is not found."""
    pass


class NotebookLMGenerationError(NotebookLMIntegrationError):
    """Raised when content generation fails."""
    pass


class NotebookLMRateLimitError(NotebookLMIntegrationError):
    """Raised when rate limits are hit."""
    pass


class NotebookLMSourceError(NotebookLMIntegrationError):
    """Raised when source upload fails."""
    pass


class NotebookLMContentNotFoundError(NotebookLMIntegrationError):
    """Raised when content/artifact is not found."""
    pass


class NotebookLMRetentionError(NotebookLMIntegrationError):
    """Raised when retention policy operation fails."""
    pass
