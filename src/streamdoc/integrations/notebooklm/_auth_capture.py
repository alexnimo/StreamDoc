"""Direct headless re-auth capture for NotebookLM.

This module mirrors the upstream ``attempt_headless_reauth`` entry point but
surfaces the complete Playwright exception when a capture fails, so StreamDoc
can diagnose launch/attach/navigation problems instead of receiving the generic
``headless capture failed: Error`` reason.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from notebooklm.exceptions import HeadlessLoginRequiredError

logger = logging.getLogger(__name__)


class _HeadlessCaptureIO:
    """Silent IO sink for unattended browser capture.

    The capture core calls ``emit`` for presentation lines, ``fail`` to abort,
    and ``run_async`` for async repair. In the unattended re-auth path we drop
    presentation output and translate ``fail`` into a ``HeadlessLoginRequiredError``
    so the caller can distinguish "landed off-host" from a genuine Playwright
    launch/attach/navigation failure.
    """

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Swallow presentation output."""
        return

    def fail(self, code: int) -> None:
        """Raise the same exception used by the upstream headless path."""
        raise HeadlessLoginRequiredError(
            f"Headless capture aborted by the capture core (exit code {code})."
        )

    def run_async(self, coro: Any) -> Any:
        """Async repair is not used in the headless re-auth path."""
        raise NotImplementedError("run_async is not used for headless re-auth")


async def run_headless_reauth_capture(
    *,
    storage_path: Path,
    browser_profile: Path,
    browser: str,
    cdp_url: str | None,
    headless: bool = True,
    env: dict[str, str] | None = None,
) -> bool:
    """Run one headless capture attempt and log the real exception on failure.

    This is the StreamDoc wrapper around ``notebooklm._browser.headless_reauth``.
    The upstream ``attempt_headless_reauth`` intentionally swallows Playwright
    errors and returns ``headless capture failed: <type>`` for security, which
    makes diagnosing launch/attach problems impossible. This wrapper performs
    the same capture but uses ``logger.exception`` so the full traceback and
    message are visible.

    Args:
        storage_path: Destination ``storage_state.json`` to (re)write.
        browser_profile: Dedicated persistent profile directory.
        browser: Playwright browser channel (``chromium``, ``chrome``, ``msedge``).
        cdp_url: Optional CDP endpoint; ``None`` uses ``NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL``.
        headless: Whether to launch the browser headless.
        env: Environment mapping for CDP resolution; defaults to ``os.environ``.

    Returns:
        ``True`` when fresh cookies were captured and persisted.
    """
    from notebooklm._browser.browser_capture import (  # type: ignore[import-untyped]
        BrowserCapturePlan,
        run_browser_capture,
        run_cdp_capture,
    )
    from notebooklm._browser.headless_reauth import (  # type: ignore[import-untyped]
        _playwright_installed,
        _resolve_reusable_profile,
        resolve_cdp_url,
    )

    if not _playwright_installed():
        logger.warning("Playwright not installed; cannot run headless re-auth")
        return False

    resolved_cdp_url = resolve_cdp_url(cdp_url, env=env or os.environ)

    def _capture() -> None:
        if resolved_cdp_url is not None:
            plan = BrowserCapturePlan(
                browser=browser,
                browser_profile=storage_path.parent,
                storage_path=storage_path,
            )
            run_cdp_capture(plan, _HeadlessCaptureIO(), cdp_url=resolved_cdp_url)
            return

        resolved_profile = _resolve_reusable_profile(
            browser_profile=browser_profile,
            profile=None,
        )
        if resolved_profile is None:
            raise FileNotFoundError(
                "no reusable browser profile on disk (run 'notebooklm login' once)"
            )

        plan = BrowserCapturePlan(
            browser=browser,
            browser_profile=resolved_profile,
            storage_path=storage_path,
        )
        run_browser_capture(
            plan, _HeadlessCaptureIO(), headless=headless, interactive=False
        )

    try:
        await asyncio.to_thread(_capture)
    except HeadlessLoginRequiredError as exc:
        logger.warning("NotebookLM headless re-auth landed off-host: %s", exc)
        return False
    except Exception:
        logger.exception("NotebookLM headless re-auth capture failed")
        return False

    logger.info("NotebookLM headless re-auth succeeded")
    return True
