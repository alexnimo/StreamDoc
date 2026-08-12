"""Playwright-based social authentication and session refresh.

Mirrors the NotebookLM auth lifecycle for X and Reddit: a persistent browser
profile for the first interactive login, then headless re-captures of cookies
that are written into the CLI credential files used by ``twitter-cli`` and
``rdt-cli``.  An optional CDP-attach mode can reuse the operator's already
running Chrome/Edge instead of the dedicated profile.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from streamdoc.config import settings

logger = logging.getLogger(__name__)

_X_LOGIN_URL = "https://x.com/i/flow/login"
_X_HOME_URL = "https://x.com/home"
_X_DOMAINS = {".x.com", "x.com", ".twitter.com", "twitter.com"}
_X_REQUIRED = {"auth_token", "ct0"}
_X_STORAGE_NAME = "cookies.json"

_REDDIT_LOGIN_URL = "https://www.reddit.com/login/"
_REDDIT_HOME_URL = "https://www.reddit.com/"
_REDDIT_DOMAINS = {".reddit.com", "reddit.com"}
_REDDIT_REQUIRED = {"reddit_session"}
_REDDIT_STORAGE_NAME = "cookies.json"
_RDT_CREDENTIAL_PATH = Path.home() / ".config" / "rdt-cli" / "credential.json"

# Map platform short names to the functions that persist captured cookies.
_CookieWriter = Callable[[Path, dict[str, str]], None]


def _write_x_cookies(storage: Path, cookies: dict[str, str]) -> None:
    """Persist X cookies to the storage file used by the API layer."""
    storage.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookies": cookies,
        "saved_at": time.time(),
    }
    storage.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(storage, 0o600)


def _write_reddit_cookies(storage: Path, cookies: dict[str, str]) -> None:
    """Persist Reddit cookies to storage and to the rdt-cli credential file."""
    storage.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookies": cookies,
        "saved_at": time.time(),
    }
    storage.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(storage, 0o600)

    # rdt-cli expects its own credential format under ~/.config/rdt-cli
    cred_dir = _RDT_CREDENTIAL_PATH.parent
    cred_dir.mkdir(parents=True, exist_ok=True)
    cred_payload = {
        "cookies": cookies,
        "source": "streamdoc",
        "username": None,
        "modhash": None,
        "saved_at": time.time(),
        "last_verified_at": None,
    }
    _RDT_CREDENTIAL_PATH.write_text(
        json.dumps(cred_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.chmod(_RDT_CREDENTIAL_PATH, 0o600)


_WRITERS: dict[str, _CookieWriter] = {
    "x": _write_x_cookies,
    "reddit": _write_reddit_cookies,
}


def _cookie_domain_matches(domain: str, allowed: set[str]) -> bool:
    """Check whether ``domain`` belongs to one of the allowed cookie domains."""
    domain = domain.lstrip(".")
    for allowed_domain in allowed:
        allowed_domain = allowed_domain.lstrip(".")
        if domain == allowed_domain or domain.endswith(f".{allowed_domain}"):
            return True
    return False


def _filter_cookies(
    cookies: list[Any],
    domains: set[str],
) -> dict[str, str]:
    """Return name/value pairs for cookies whose domains match ``domains``."""
    result: dict[str, str] = {}
    for cookie in cookies:
        if _cookie_domain_matches(str(cookie.get("domain", "")), domains):
            name = str(cookie.get("name", ""))
            value = str(cookie.get("value", ""))
            if name:
                result[name] = value
    return result


def _capture(
    platform: str,
    profile: str,
    storage: str,
    login_url: str,
    required: list[str],
    domains: list[str],
    headless: bool,
    cdp_url: str | None,
    timeout: float,
    writer: str,
) -> None:
    """Playwright cookie capture used by the social auth managers.

    This function is intentionally self-contained so it can be launched via
    ``python -c`` from a route.  It imports Playwright, navigates to the
    target URL, and polls the browser context until the required cookies are
    present or the timeout expires.
    """
    from playwright.sync_api import sync_playwright

    storage_path = Path(storage)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(profile)
    profile_dir.mkdir(parents=True, exist_ok=True)

    domain_set = set(domains)
    required_set = set(required)
    deadline = time.monotonic() + float(timeout)

    with sync_playwright() as p:
        if cdp_url:
            logger.info("[%s] Connecting over CDP: %s", platform, cdp_url)
            browser = p.chromium.connect_over_cdp(cdp_url)
            cookies = {}
            for context in browser.contexts:
                cookies.update(_filter_cookies(context.cookies(), domain_set))
            browser.close()
            if not required_set.issubset(cookies.keys()):
                missing = required_set - cookies.keys()
                raise RuntimeError(f"Missing cookies from CDP context: {missing}")
            _WRITERS[writer](storage_path, cookies)
            return

        channel = None
        if settings.social_browser in ("chrome", "msedge"):
            channel = settings.social_browser

        launch_args = [
            "--disable-blink-features=AutomationControlled",
        ]
        if sys.platform == "linux":
            launch_args.append("--no-sandbox")

        logger.info(
            "[%s] Launching %s persistent browser (headless=%s)",
            platform,
            channel or "chromium",
            headless,
        )
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile,
            channel=channel,
            headless=headless,
            args=launch_args,
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
        )

        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")

        cookies = _filter_cookies(context.cookies(), domain_set)
        while time.monotonic() < deadline:
            cookies = _filter_cookies(context.cookies(), domain_set)
            if required_set.issubset(cookies.keys()):
                break
            time.sleep(0.5)
        else:
            context.close()
            missing = required_set - cookies.keys()
            raise RuntimeError(f"Timeout waiting for cookies: {missing}")

        context.close()
        _WRITERS[writer](storage_path, cookies)


def _python_path_env() -> dict[str, str]:
    """Return ``os.environ`` with the project ``src`` directory on ``PYTHONPATH``.

    This makes ``import streamdoc`` work for the ``python -c`` capture
    subprocess even when it is not started through ``uv run``.
    """
    env = os.environ.copy()
    src_dir = Path(__file__).resolve().parents[3]
    existing = env.get("PYTHONPATH", "")
    if existing:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}"
    else:
        env["PYTHONPATH"] = str(src_dir)
    # Reason: Windows console code pages default to cp1252; force the child
    # process to read/write UTF-8 on stdio and use UTF-8 as the default
    # encoding for file system operations so it does not crash on non-ASCII
    # characters or output bytes that the parent then mis-decodes.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class SocialAuthManager:
    """Persistent-profile social auth for a single platform.

    Handles the first interactive login (a visible browser), subsequent
    headless re-captures, and credential cleanup.  Platform specifics are
    expressed through a few attributes and writer callbacks.
    """

    def __init__(
        self,
        platform: str,
        login_url: str,
        home_url: str,
        required: set[str],
        domains: set[str],
        writer: str,
    ):
        """Initialize a manager for a platform.

        Args:
            platform: Short platform key (e.g. ``x`` or ``reddit``).
            login_url: URL to open for an interactive first login.
            home_url: URL to open for a headless refresh.
            required: Cookie names required to consider the session usable.
            domains: Cookie domains to collect.
            writer: Key in ``_WRITERS`` that persists captured cookies.
        """
        self.platform = platform
        self.login_url = login_url
        self.home_url = home_url
        self.required = required
        self.domains = domains
        self.writer = writer
        self.storage_dir = Path(settings.social_auth_storage_root) / platform
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage = self.storage_dir / "cookies.json"
        self.profile_dir = self.storage_dir / "profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def _capture_script(
        self,
        url: str,
        headless: bool,
        cdp_url: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Return a Python one-liner that runs ``_capture`` in a subprocess."""
        if timeout is None:
            timeout = (
                settings.social_login_timeout_seconds
                if not headless
                else settings.social_refresh_timeout_seconds
            )
        parts = [
            "from streamdoc.integrations.social.auth import _capture",
            "_capture(",
            f"    platform={self.platform!r},",
            f"    profile={str(self.profile_dir)!r},",
            f"    storage={str(self.storage)!r},",
            f"    login_url={url!r},",
            f"    required={sorted(self.required)!r},",
            f"    domains={sorted(self.domains)!r},",
            f"    headless={headless},",
            f"    cdp_url={cdp_url!r},",
            f"    timeout={timeout},",
            f"    writer={self.writer!r},",
            ")",
        ]
        return "\n".join(parts)

    def _start_subprocess(self, script: str) -> subprocess.Popen[str]:
        """Spawn the capture in a standalone process."""
        return subprocess.Popen(
            [sys.executable, "-c", script],
            env=_python_path_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def start_login(self, cdp_url: str | None = None) -> str:
        """Open the interactive login browser and return immediately.

        The operator completes login in the opened window; the capture process
        polls for the required cookies, writes them, and exits automatically.
        """
        script = self._capture_script(
            self.login_url,
            headless=False,
            cdp_url=cdp_url,
            timeout=settings.social_login_timeout_seconds,
        )
        process = self._start_subprocess(script)
        logger.info(
            "[%s] Started interactive login capture (pid=%s)",
            self.platform,
            process.pid,
        )
        return f"Login browser opened for {self.platform} (pid {process.pid})."

    def refresh(self, cdp_url: str | None = None) -> bool:
        """Run a headless refresh and block until it finishes.

        Returns:
            True when the required cookies were captured.
        """
        script = self._capture_script(
            self.home_url,
            headless=True,
            cdp_url=cdp_url,
            timeout=settings.social_refresh_timeout_seconds,
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                env=_python_path_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.social_refresh_timeout_seconds + 10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[%s] Headless refresh timed out", self.platform)
            return False

        if result.returncode != 0:
            logger.warning(
                "[%s] Headless refresh failed: %s",
                self.platform,
                result.stderr.strip()[-500:],
            )
            return False

        logger.info("[%s] Headless refresh succeeded", self.platform)
        return True

    def is_authenticated(self) -> bool:
        """Check whether captured cookies are present locally."""
        if not self.storage.exists():
            return False
        try:
            data = json.loads(self.storage.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        cookies = data.get("cookies", {})
        return self.required.issubset(cookies.keys())

    def logout(self) -> bool:
        """Delete captured cookies and the persistent browser profile."""
        deleted = False
        if self.storage.exists():
            self.storage.unlink()
            deleted = True
        if self.profile_dir.exists():
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            deleted = True
        return deleted

    def get_cookies(self) -> dict[str, str] | None:
        """Return the captured cookies, or None if not available."""
        if not self.storage.exists():
            return None
        try:
            data = json.loads(self.storage.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        cookies = data.get("cookies")
        if not isinstance(cookies, dict):
            return None
        return {str(k): str(v) for k, v in cookies.items()}


def x_auth_manager() -> SocialAuthManager:
    """Return a configured X auth manager."""
    return SocialAuthManager(
        platform="x",
        login_url=_X_LOGIN_URL,
        home_url=_X_HOME_URL,
        required=_X_REQUIRED,
        domains=_X_DOMAINS,
        writer="x",
    )


def reddit_auth_manager() -> SocialAuthManager:
    """Return a configured Reddit auth manager."""
    return SocialAuthManager(
        platform="reddit",
        login_url=_REDDIT_LOGIN_URL,
        home_url=_REDDIT_HOME_URL,
        required=_REDDIT_REQUIRED,
        domains=_REDDIT_DOMAINS,
        writer="reddit",
    )


# ---------------------------------------------------------------------------
# Manual / fallback helpers
# ---------------------------------------------------------------------------


def get_twitter_cli_env() -> dict[str, str]:
    """Build the environment for the twitter CLI.

    Priority:
    1. Cookies captured by the Playwright manager.
    2. Existing ``TWITTER_*`` environment variables.
    3. ``STREAMDOC_TWITTER_*`` settings (manual fallback).

    Returns:
        A mapping to pass as ``env`` to ``subprocess.run``.
    """
    env = os.environ.copy()
    manager = x_auth_manager()
    cookies = manager.get_cookies() or {}

    if "auth_token" in cookies and "ct0" in cookies:
        env["TWITTER_AUTH_TOKEN"] = cookies["auth_token"]
        env["TWITTER_CT0"] = cookies["ct0"]
    else:
        if "TWITTER_AUTH_TOKEN" not in env and settings.twitter_auth_token:
            env["TWITTER_AUTH_TOKEN"] = settings.twitter_auth_token
        if "TWITTER_CT0" not in env and settings.twitter_ct0:
            env["TWITTER_CT0"] = settings.twitter_ct0
    # Reason: the public-clis twitter/rdt CLIs run on Python and may print
    # non-ASCII characters; force UTF-8 child stdio so the parent can safely
    # decode the captured pipe as utf-8 on Windows.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def seed_reddit_credentials_from_settings() -> str | None:
    """Write the operator's Reddit cookie header to rdt-cli's credential file.

    This is used as a manual fallback on Windows, where ``browser-cookie3``
    cannot decrypt Chrome's DPAPI-locked cookie database.

    Returns:
        None if seeding succeeded or was not needed, otherwise an error message.
    """
    cookie_header = (settings.reddit_cookie or "").strip()
    if not cookie_header:
        return None

    if cookie_header.lower().startswith("cookie:"):
        cookie_header = cookie_header.split(":", 1)[1].strip()

    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()

    if "reddit_session" not in cookies:
        return "Reddit cookie header is missing the required reddit_session value."

    _write_reddit_cookies(reddit_auth_manager().storage, cookies)
    return None
