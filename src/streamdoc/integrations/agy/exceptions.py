"""Exceptions for the Antigravity (agy) integration.

Mirrors the shape of :mod:`streamdoc.integrations.notebooklm.exceptions` so
callers can catch either backend with a common ``*IntegrationError`` handler
when they need to.

All agy errors derive from :class:`AGYIntegrationError` so the orchestrator
in :mod:`streamdoc.core.agy_upload` can wrap them in a single ``try/except``
without leaking subprocess / parse exceptions to the fetch pipeline.
"""


class AGYIntegrationError(Exception):
    """Base exception for the agy integration."""


class AGYNotInstalledError(AGYIntegrationError):
    """Raised when the agy binary (or its npx fallback) cannot be located.

    ``find_agy_binary()`` returns ``None`` in that case; the orchestrator
    in :func:`streamdoc.core.agy_upload.upload_to_agy` translates that into
    a non-raising ``AgyUploadResult(success=False, errors=[...])`` so the
    fetch pipeline degrades gracefully when the operator has not installed
    agy.
    """


class AGYInvocationError(AGYIntegrationError):
    """Raised when the agy subprocess fails to start, times out, or exits non-zero.

    Used for both the content-generation skill invocation and the herenow
    publish invocation. The runner itself does NOT raise on non-zero exit
    (it returns an :class:`AgyRunResult` so the orchestrator can decide);
    this exception is reserved for hard pre-flight failures (no binary,
    empty report list, etc.).
    """


class AGYPublishError(AGYIntegrationError):
    """Raised when the herenow publish skill cannot produce a parseable URL.

    Surfaced from :func:`streamdoc.integrations.agy.herenow.publish` when
    either the skill exited non-zero or its stdout did not contain a
    ``Published: <url>`` line. The orchestrator appends the message to
    ``AgyUploadResult.errors`` but does not fail the overall upload — the
    artifact is still produced.
    """


__all__ = [
    "AGYIntegrationError",
    "AGYNotInstalledError",
    "AGYInvocationError",
    "AGYPublishError",
]
