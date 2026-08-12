"""Playwright-based Google login for NotebookLM.

Thin wrapper around the upstream ``notebooklm._auth.browser_capture`` core so
StreamDoc's interactive and headless login paths reuse the same battle-tested
launch -> navigate -> capture -> filter -> persist sequence that ships with the
installed ``notebooklm-py`` package. The wrapper only translates StreamDoc's
``run_playwright_login`` call signature into the upstream
:class:`notebooklm._auth.browser_capture.BrowserCapturePlan` and a simple
:class:`BrowserCaptureIO` sink.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


def run_playwright_login(
    storage_path: str,
    browser_profile: str,
    headless: bool = True,
    browser: str = "chromium",
    login_timeout_ms: int = 300_000,
    goto_timeout_ms: int = 30_000,
) -> bool:
    """Authenticate with NotebookLM via Playwright.

    Args:
        storage_path: Path to the ``storage_state.json`` file to write.
        browser_profile: Path to the persistent Chromium/Chrome profile dir.
        headless: If True, run without a visible window. First-time logins
            must use ``headless=False`` so the user can enter credentials.
        browser: Browser channel to launch. ``"chromium"`` uses the bundled
            Playwright browser (default and most reliable); ``"chrome"`` or
            ``"msedge"`` use a system-installed browser. System browsers can
            conflict with an already-running browser instance, so use them
            only when the bundled browser fails.
        login_timeout_ms: Ignored for upstream compatibility; upstream uses
            its own 300 s wait for interactive login.
        goto_timeout_ms: Ignored for upstream compatibility; navigation retries
            are handled by the upstream capture core.

    Returns:
        True when cookies were extracted and saved.

    Raises:
        RuntimeError: If Playwright is not installed, the browser cannot be
            launched, or login fails.
    """
    del login_timeout_ms, goto_timeout_ms  # legacy signature compatibility

    from notebooklm._auth.browser_capture import (
        BrowserCapturePlan,
        run_browser_capture,
    )

    storage_file = Path(storage_path)
    profile_dir = Path(browser_profile)
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    plan = BrowserCapturePlan(
        browser=browser,
        browser_profile=profile_dir,
        storage_path=storage_file,
        include_domains=None,
    )

    io = _PrintCaptureIO()
    run_browser_capture(
        plan,
        io,
        headless=headless,
        interactive=not headless,
    )
    # Headless re-auth emits a CaptureResult only on success; the upstream core
    # raises on any non-success path, so reaching here means cookies were saved.
    print("Login successful!" if headless else "Cookies captured.", flush=True)
    return True


class _PrintCaptureIO:
    """Minimal BrowserCaptureIO sink for non-interactive / stream callers.

    Forwards human-readable upstream messages to stdout/stderr. ``fail`` maps to
    a :class:`RuntimeError` rather than ``sys.exit`` so the function can be called
    from a worker thread or subprocess without killing the parent process.
    """

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Print an upstream presentation line to stdout."""
        if not args:
            return
        # Rich markup may contain formatting tags; strip them for plain output.
        text = " ".join(str(a) for a in args)
        print(text, flush=True)

    def fail(self, code: int) -> Any:
        """Map an upstream abort to a Python exception."""
        raise RuntimeError(f"NotebookLM login aborted (exit code {code})")

    def run_async(self, coro: Any) -> Any:
        """Run an async coroutine synchronously.

        The neutral capture core only invokes this in its interactive adapter;
        headless calls never reach it. If it is reached, run it in a temporary
        event loop to keep the sink self-contained.
        """
        try:
            return asyncio.get_running_loop().run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)
