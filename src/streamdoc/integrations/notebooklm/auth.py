"""Authentication and session management for NotebookLM."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from streamdoc.config import settings
from streamdoc.integrations.notebooklm.exceptions import NotebookLMAuthRequiredError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from notebooklm import AuthTokens

# Reason: Playwright cannot safely run two logins against the same
# persistent browser profile at the same time. A process-wide lock
# prevents concurrent interactive/refresh attempts from clobbering
# the same Chrome profile.
_LOGIN_LOCK = threading.Lock()


def _env_without_cdp() -> dict[str, str]:
    """Return a copy of ``os.environ`` with the NotebookLM CDP URL removed.

    Used during the fallback to the dedicated browser profile so
    ``resolve_cdp_url`` does not re-read ``NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL``.
    """
    return {
        key: value
        for key, value in os.environ.items()
        if key != "NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL"
    }


@dataclass
class SessionStatus:
    """Session status information."""
    is_valid: bool
    is_fresh: bool
    message: str
    profile: str
    storage_path: str


def _is_auth_error(exc: BaseException) -> bool:
    """Check if an exception signals an expired or invalid NotebookLM session.

    These substrings match the user-facing messages notebooklm-py raises when
    the stored cookies no longer authenticate and the upstream flow redirects to
    ``accounts.google.com``.

    Args:
        exc: The exception to inspect.

    Returns:
        True when the exception looks auth-shaped.
    """
    msg = str(exc).lower()
    return any(
        sig in msg
        for sig in [
            "authentication",
            "redirected to",
            "run 'notebooklm login'",
            "session expired",
            "session invalid",
            "unauthorized",
        ]
    )


class NotebookLMAuthManager:
    """Manages NotebookLM authentication lifecycle.
    
    This class wraps the notebooklm-py authentication system and provides
    session freshness checking and re-authentication flows.
    
    Args:
        storage_path: Path to the storage_state.json file
        profile: Profile name for multi-account support
    """
    
    def __init__(self, storage_path: str, profile: str = "default"):
        self.storage_path = Path(storage_path)
        self.profile = profile
        self._storage_path_for_profile = self._resolve_storage_path()
    
    def _resolve_storage_path(self) -> Path:
        """Resolve the actual storage path based on profile."""
        if self.profile == "default":
            return self.storage_path
        # For named profiles, use subdirectory
        return self.storage_path.parent / "profiles" / self.profile / "storage_state.json"
    
    def is_configured(self) -> bool:
        """Check if authentication storage exists.
        
        Returns:
            True if storage_state.json exists
        """
        return self._storage_path_for_profile.exists()
    
    async def is_authenticated(self) -> bool:
        """Check if valid authentication exists.
        
        This checks both file existence and attempts a lightweight
        validation by loading the auth tokens.
        
        Returns:
            True if authentication appears valid
        """
        if not self.is_configured():
            return False
        
        try:
            # Try to load auth tokens
            tokens = await self.get_auth_tokens()
            return tokens is not None
        except Exception:  # noqa: BLE001
            return False

    async def _probe_session(self) -> None:
        """Open a client and list notebooks as a lightweight session probe.

        Wraps the upstream ``from_storage`` path so the same exception handling
        can be reused for the initial check and the post-refresh retry.

        Raises:
            Exception: Any exception raised by ``from_storage`` or ``notebooks.list()``.
        """
        from notebooklm import NotebookLMClient

        # Reason: allow_headless=True lets the probe benefit from mid-RPC
        # headless re-auth if cookies are expired but the profile is valid.
        async with NotebookLMClient.from_storage(
            str(self._storage_path_for_profile), allow_headless=True,
        ) as client:
            await client.notebooks.list()

    async def check_session_freshness(self, auto_refresh: bool = True) -> SessionStatus:
        """Check session freshness by attempting a lightweight operation.

        When ``auto_refresh`` is enabled and the probe fails with an auth-shaped
        error, attempts a one-shot headless re-capture from the browser profile.

        Args:
            auto_refresh: If True, attempt to re-capture cookies when expired.

        Returns:
            SessionStatus with validity and freshness information
        """
        from streamdoc.integrations.notebooklm.keepalive import configure_refresh_cmd

        # Opt in to upstream layer-3 headless re-auth gating as early as possible.
        configure_refresh_cmd(self)

        if not self.is_configured():
            return SessionStatus(
                is_valid=False,
                is_fresh=False,
                message="No authentication configured. Click 'Login' to authenticate.",
                profile=self.profile,
                storage_path=str(self._storage_path_for_profile)
            )

        try:
            await self._probe_session()
            return SessionStatus(
                is_valid=True,
                is_fresh=True,
                message="Session is valid and fresh",
                profile=self.profile,
                storage_path=str(self._storage_path_for_profile)
            )
        except ImportError:
            return SessionStatus(
                is_valid=False,
                is_fresh=False,
                message="notebooklm-py not installed. Run: uv sync --extra notebooklm-cookies",
                profile=self.profile,
                storage_path=str(self._storage_path_for_profile)
            )
        except Exception as exc:  # noqa: BLE001
            if auto_refresh and _is_auth_error(exc):
                logger.warning(
                    "NotebookLM session stale; attempting automatic re-capture: %s", exc
                )
                if await self.refresh_session():
                    try:
                        await self._probe_session()
                        return SessionStatus(
                            is_valid=True,
                            is_fresh=True,
                            message="Session refreshed and is now valid",
                            profile=self.profile,
                            storage_path=str(self._storage_path_for_profile)
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        return SessionStatus(
                            is_valid=False,
                            is_fresh=False,
                            message=f"Session invalid or expired after re-capture: {retry_exc}",
                            profile=self.profile,
                            storage_path=str(self._storage_path_for_profile)
                        )
            return SessionStatus(
                is_valid=False,
                is_fresh=False,
                message=f"Session invalid or expired: {exc}",
                profile=self.profile,
                storage_path=str(self._storage_path_for_profile)
            )

    async def require_auth(self) -> None:
        """Require valid authentication, raise if not available.

        Raises:
            NotebookLMAuthRequiredError: If authentication is not valid
        """
        status = await self.check_session_freshness(auto_refresh=True)
        if not status.is_valid:
            raise NotebookLMAuthRequiredError(status.message)

    async def refresh_session(self, headless: bool = True) -> bool:
        """Refresh the stored session via a headless browser re-capture.

        This drives the same Playwright capture path that ``login()`` uses, but
        unattended and with the operator's configured ``notebooklm_browser``
        (``chromium`` / ``chrome`` / ``msedge``). If the dedicated
        ``browser_profile`` still holds a live Google session, fresh NotebookLM
        cookies are written to ``storage_state.json`` without human interaction.
        When ``STREAMDOC_NOTEBOOKLM_CDP_URL`` / ``NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL``
        is set, the capture attaches to the running Chrome instead of the
        dedicated profile.

        Using the dedicated headless capture directly is more robust than
        routing through ``NotebookLMClient.refresh_auth`` for this layer,
        because the upstream client does not pass the configured browser
        channel to its L3 re-auth and defaults to bundled Chromium. That
        default cannot read a profile created by Chrome or Edge, which is why
        the pre-change ``login()``-based refresh used to work with those
        browsers.

        Args:
            headless: Whether to allow the unattended headless re-auth layer.
                This should be True for automatic recovery; interactive logins
                should use ``login(headless=False)`` instead.

        Returns:
            True when fresh cookies were captured and persisted.
        """
        from streamdoc.integrations.notebooklm._auth_capture import (
            run_headless_reauth_capture,
        )
        from streamdoc.integrations.notebooklm.keepalive import (
            configure_refresh_cmd,
        )

        configure_refresh_cmd(self)
        if not self.is_configured():
            return False

        storage_path = self._storage_path_for_profile
        browser_profile = storage_path.parent / "browser_profile"
        cdp_url = settings.notebooklm_cdp_url

        if cdp_url:
            logger.info("NotebookLM refresh using CDP endpoint: %s", cdp_url)
        else:
            logger.info(
                "NotebookLM refresh using dedicated browser profile (browser=%s)",
                settings.notebooklm_browser,
            )

        # Reason: if the operator configured CDP, try it first (their live
        # Chrome is the freshest credential source). If that fails, fall back
        # to the dedicated browser_profile rather than giving up, because a
        # CDP endpoint may point at a Chrome that is not signed into the
        # Google account used by the Playwright profile. The no-CDP attempt
        # passes an env mapping with the CDP key removed so
        # ``resolve_cdp_url`` cannot pick it up again.
        attempts: list[tuple[str | None, dict[str, str] | None]] = [
            (cdp_url, None),
            (None, _env_without_cdp()),
        ]
        if cdp_url is None:
            attempts = [(None, None)]

        for attempt_url, attempt_env in attempts:
            if attempt_url is None and cdp_url:
                logger.info(
                    "CDP re-auth failed; retrying with dedicated browser profile (browser=%s)",
                    settings.notebooklm_browser,
                )
            try:
                result = await run_headless_reauth_capture(
                    storage_path=storage_path,
                    browser_profile=browser_profile,
                    browser=settings.notebooklm_browser,
                    cdp_url=attempt_url,
                    headless=headless,
                    env=attempt_env,
                )
            except Exception:
                logger.exception("NotebookLM re-auth capture raised")
                return False

            if result:
                return True

        return False
    
    async def get_auth_tokens(self) -> "AuthTokens | None":
        """Get authentication tokens from storage.
        
        Returns:
            AuthTokens if available, None otherwise
        """
        if not self.is_configured():
            return None
        
        try:
            from notebooklm import AuthTokens
            return await AuthTokens.from_storage(self._storage_path_for_profile)
        except Exception:  # noqa: BLE001
            return None
    
    def get_storage_path(self) -> str:
        """Get the resolved storage path for the current profile.
        
        Returns:
            Path to storage_state.json
        """
        return str(self._storage_path_for_profile)
    
    def ensure_directory_exists(self) -> None:
        """Ensure the storage directory exists."""
        self._storage_path_for_profile.parent.mkdir(parents=True, exist_ok=True)

    async def login_from_cookie_header(self, cookie_header: str) -> bool:
        """Authenticate using a raw Cookie header string from the browser.

        Parses a Cookie header (e.g. from browser DevTools Network tab)
        and saves it in Playwright storage_state format.

        Args:
            cookie_header: Raw Cookie header value, e.g.
                "SID=xxx; __Secure-1PSIDTS=yyy; HSID=zzz"

        Returns:
            True if authentication was successful.

        Raises:
            RuntimeError: If required cookies are missing.
        """
        self.ensure_directory_exists()

        cookies = []
        for pair in cookie_header.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".google.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": name.startswith("__Secure"),
                "sameSite": "Lax",
            })

        cookie_names: set[str] = {str(c["name"]) for c in cookies}
        required = {"SID", "__Secure-1PSIDTS"}
        missing = required - cookie_names
        if missing:
            raise RuntimeError(
                f"Missing required cookies: {missing}. "
                f"Make sure to copy the Cookie header from a request to "
                f"notebooklm.google.com while logged in."
            )

        state = {"cookies": cookies, "origins": []}
        with open(self._storage_path_for_profile, "w") as f:  # noqa: ASYNC230
            json.dump(state, f, indent=2)

        return True

    async def login(self, headless: bool = True) -> bool:
        """Authenticate with NotebookLM using Playwright persistent profile.

        Uses a persistent browser profile so the Google login session is
        preserved across restarts. First login requires interactive Google
        sign-in; subsequent logins reuse the saved session automatically.

        Args:
            headless: If True, run browser in headless mode. Should be False
                for first-time login so user can enter credentials.

        Returns:
            True if authentication was successful.

        Raises:
            RuntimeError: If Playwright is not installed or login fails.
        """
        self.ensure_directory_exists()

        script = self._login_script(headless=headless)

        def _run() -> subprocess.CompletedProcess[str]:
            with _LOGIN_LOCK:
                return subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )

        # Reason: Windows asyncio event loop doesn't support subprocesses,
        # so run the locked subprocess call in a thread via asyncio.to_thread.
        result = await asyncio.to_thread(_run)

        if result.returncode == 0:
            return True
        err = result.stderr.strip() if result.stderr else "Unknown error"
        raise RuntimeError(f"Login failed: {err}")

    def _login_script(
        self,
        headless: bool = True,
        browser: str | None = None,
    ) -> str:
        """Generate a standalone Playwright login script.

        The generated script imports the shared ``playwright_login`` module so
        the browser-automation logic is not duplicated as an inline string.

        Args:
            headless: If True, run browser in headless mode.
            browser: Browser channel (``"chromium"``, ``"chrome"``, ``"msedge"``).
                Defaults to ``settings.notebooklm_browser``.

        Returns:
            Python script source code as a string.
        """
        if browser is None:
            browser = settings.notebooklm_browser
        storage_path = str(self._storage_path_for_profile).replace("\\", "/")
        profile_dir = str(
            self._storage_path_for_profile.parent / "browser_profile"
        ).replace("\\", "/")
        return f'''
import sys
try:
    from streamdoc.integrations.notebooklm.playwright_login import run_playwright_login
    run_playwright_login(
        storage_path=r"{storage_path}",
        browser_profile=r"{profile_dir}",
        headless={headless},
        browser="{browser}",
    )
    sys.exit(0)
except Exception as exc:
    print(exc, file=sys.stderr, flush=True)
    sys.exit(1)
'''

    def logout(self) -> bool:
        """Clear stored credentials and browser profile.

        Returns:
            True if credentials were deleted, False if they didn't exist
        """
        deleted = False
        if self._storage_path_for_profile.exists():
            self._storage_path_for_profile.unlink()
            deleted = True

        # Reason: Also remove the persistent browser profile so the next
        # login starts fresh without stale Google sessions
        import shutil
        profile_dir = self._storage_path_for_profile.parent / "browser_profile"
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)

        return deleted
