"""
Single source of truth for all yt-dlp interactions.

Consolidates binary discovery, argument building, and invocation so that
channel.py, fetch.py, and any future callers share one consistent config.
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from streamdoc.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Download error classification
# ---------------------------------------------------------------------------

# Reason: YouTube returns distinct error messages for different failure
# modes. Some are permanent (members-only, private, deleted) and should
# never be retried; others are transient (bot detection, rate limit) and
# may succeed with a different bypass method or after an update. Classifying
# them lets the pipeline mark permanently-restricted videos so they don't
# waste time on every run.
_PERMANENT_ERROR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("members_only", re.compile(r"members?-only|Join this channel.*members|level:", re.IGNORECASE)),
    ("private_deleted", re.compile(r"Private video|Video unavailable|has been removed|is not available|deleted", re.IGNORECASE)),
    ("age_restricted", re.compile(r"age[- ]restricted|inappropriate for some users", re.IGNORECASE)),
    ("region_blocked", re.compile(r"is not available in your country|region", re.IGNORECASE)),
]
_TRANSIENT_ERROR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bot_detection", re.compile(r"Sign in to confirm.*not a bot|confirm you.*not a bot", re.IGNORECASE)),
    ("rate_limited", re.compile(r"rate[- ]limit|too many requests|429", re.IGNORECASE)),
    ("login_required", re.compile(r"Sign in|login required", re.IGNORECASE)),
    # Reason: YouTube IP-blocks DASH/HTTPS media downloads (returns 403 on
    # the format URL) while HLS (m3u8) formats from web_safari remain
    # accessible. This is transient/retriable via the bypass chain or HLS
    # fallback path.
    ("http_403", re.compile(r"HTTP Error 403|403 Forbidden|unable to download video data", re.IGNORECASE)),
]
# Reason: cookie DB lock is a Windows-specific infrastructure error, not a
# video-specific error. When Chrome (or Edge) is running, it holds an
# exclusive lock on its cookie SQLite DB, and yt-dlp cannot copy it
# (yt-dlp issue #7271). This is retriable with a different bypass mode.
_COOKIE_DB_LOCK_PATTERN = re.compile(
    r"Could not copy.*cookie database", re.IGNORECASE
)


def classify_download_error(stderr: str) -> str:
    """Classify a yt-dlp stderr/error string into a failure category.

    Categories:
      - ``"members_only"``: Channel-members-only content (permanent).
      - ``"private_deleted"``: Private, deleted, or unavailable video (permanent).
      - ``"age_restricted"``: Age-restricted content (permanent without login).
      - ``"region_blocked"``: Geo-blocked content (permanent).
      - ``"bot_detection"``: YouTube bot-detection challenge (transient).
      - ``"rate_limited"``: Rate limiting (transient).
      - ``"login_required"``: Sign-in required (transient, fixable with cookies).
      - ``"http_403"``: HTTP 403 on media download — YouTube IP-blocks DASH
        formats; retriable via bypass chain or HLS fallback (web_safari client).
      - ``"cookie_db_locked"``: Browser cookie DB locked (infra error, retriable
        with a different bypass mode).
      - ``"other"``: Unclassified error.

    Args:
        stderr: The yt-dlp stderr output or exception message.

    Returns:
        One of the category strings above.
    """
    # Reason: check cookie DB lock before other patterns because it's an
    # infrastructure error that should trigger a fallback retry, not be
    # confused with a video-specific permanent or transient error.
    if _COOKIE_DB_LOCK_PATTERN.search(stderr):
        return "cookie_db_locked"
    for category, pattern in _PERMANENT_ERROR_PATTERNS:
        if pattern.search(stderr):
            return category
    for category, pattern in _TRANSIENT_ERROR_PATTERNS:
        if pattern.search(stderr):
            return category
    return "other"


def is_permanent_error(category: str) -> bool:
    """Return True if the error category means the video can never be downloaded."""
    return category in {"members_only", "private_deleted", "age_restricted", "region_blocked"}


def is_cookie_db_lock_error(stderr: str) -> bool:
    """Return True if the error indicates a locked browser cookie database.

    Reason: on Windows, Chrome/Edge hold an exclusive lock on their cookie
    SQLite DB while running. yt-dlp cannot copy it and fails with
    "Could not copy Chrome cookie database" (yt-dlp issue #7271). This is
    an infrastructure error, not a video-specific error — the caller should
    retry with a different bypass mode (e.g. a pre-exported cookie jar or
    no cookies at all).

    Args:
        stderr: The yt-dlp stderr output or exception message.

    Returns:
        True if the error is a cookie DB lock error.
    """
    return bool(_COOKIE_DB_LOCK_PATTERN.search(stderr))


@dataclass(frozen=True)
class DownloadResult:
    """Result of a yt-dlp download attempt.

    Attributes:
        path: Downloaded media path if successful, else None.
        error: Raw error message if failed, else None.
        error_category: Classified error category (see classify_download_error).
    """
    path: Path | None = None
    error: str | None = None
    error_category: str = "ok"


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------

def _yt_dlp_binary() -> str:
    """Return the path to the yt-dlp binary.

    Resolution order:
      1. ``settings.yt_dlp_path`` (explicit override)
      2. ``settings.yt_dlp_module_path`` (managed install binary)
      3. ``shutil.which("yt-dlp")`` (on PATH)
      4. Fallback common locations
    """
    if settings.yt_dlp_path:
        return settings.yt_dlp_path

    if settings.yt_dlp_module_path:
        return settings.yt_dlp_module_path

    candidate = shutil.which("yt-dlp")
    if candidate:
        return candidate

    # Reason: common install locations on Windows / Linux
    for fallback in (
        Path("/usr/local/bin/yt-dlp"),
        Path("/usr/bin/yt-dlp"),
        Path.home() / ".local/bin/yt-dlp",
    ):
        if fallback.exists():
            return str(fallback)

    raise FileNotFoundError(
        "yt-dlp not found. Install it via `uv pip install yt-dlp` or set STREAMDOC_YT_DLP_PATH."
    )


def must_exist() -> bool:
    """Return True if yt-dlp is available."""
    try:
        _yt_dlp_binary()
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Shared argument builder
# ---------------------------------------------------------------------------

def _resolve_cookie_path() -> Path | None:
    """Return an absolute cookie-jar path if the file exists, else None."""
    cookie_path = settings.yt_dlp_cookiejar_path
    if not cookie_path:
        return None
    p = Path(cookie_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p if p.exists() else None


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``.

    Lists are replaced by the override value, not extended. This is
    intended for merging yt-dlp option dicts (e.g. ``extractor_args``
    and ``http_headers``) without clobbering unrelated keys.

    Args:
        base: Dict to update.
        override: Dict with values to merge.

    Returns:
        Updated ``base`` dict.
    """
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _parse_extra_args_to_opts(extra_args: str | None) -> dict[str, Any]:
    """Translate CLI-style ``STREAMDOC_YT_DLP_EXTRA_ARGS`` into a yt-dlp
    Python API option dict.

    Reason: the Python API does not accept raw string flags like the CLI
    does. We use yt-dlp's own option parser to convert the extra string
    into the equivalent ``YoutubeDL`` params, then keep only the keys that
    differ from the default so we don't clobber the caller's explicit
    options.

    Args:
        extra_args: Raw string of extra yt-dlp CLI arguments.

    Returns:
        Dict of yt-dlp ``YoutubeDL`` options parsed from ``extra_args``.
    """
    if not extra_args:
        return {}

    try:
        default_opts = yt_dlp.parse_options([]).ydl_opts
        extra_opts = yt_dlp.parse_options(shlex.split(extra_args)).ydl_opts
    except Exception as exc:
        logger.warning("Failed to parse STREAMDOC_YT_DLP_EXTRA_ARGS %r: %s", extra_args, exc)
        return {}

    diff: dict[str, Any] = {}
    for key, value in extra_opts.items():
        default_value = default_opts.get(key)
        if value != default_value:
            diff[key] = value
    return diff


def _parse_js_runtimes(runtimes: str | None) -> dict[str, dict[str, Any]]:
    """Parse a comma-separated JS runtimes string into yt-dlp's dict format.

    Reason: yt-dlp's Python API expects ``js_runtimes`` as a dict mapping
    runtime name to an options dict (e.g. ``{"node": {"path": None}}``).
    The CLI accepts ``--js-runtimes node`` or ``--js-runtimes node:/path``.
    This helper converts the config string to the dict format, preserving
    Deno (yt-dlp's default) so both can be used if available.

    Args:
        runtimes: Comma-separated runtime names, optionally with
            ``:path`` suffix (e.g. ``"node"``, ``"node,deno"``,
            ``"node:/usr/bin/node"``). Empty/None returns empty dict.

    Returns:
        Dict suitable for ``YoutubeDL(js_runtimes=...)``.
    """
    if not runtimes:
        return {}
    # Reason: always include deno (yt-dlp's default) so it's used if
    # available, even when the user only specifies node. This matches
    # the CLI behaviour where --js-runtimes node adds node alongside deno.
    result: dict[str, dict[str, Any]] = {"deno": {"path": None}}
    for raw in runtimes.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if ":" in entry:
            name, _, path = entry.partition(":")
            name = name.strip()
            if name:
                result[name] = {"path": path.strip() or None}
        else:
            result[entry] = {"path": None}
    return result


def _apply_bypass_opts(
    opts: dict[str, Any], *, bypass_mode_override: str | None = None
) -> dict[str, Any]:
    """Apply cookie/PO-token/user-agent/extra-args bypass settings to
    an existing yt-dlp ``YoutubeDL`` options dict.

    The function respects the priority order:
      1. ``STREAMDOC_YT_DLP_EXTRA_ARGS`` (highest, user override)
      2. mode-specific bypass (po_token / cookie)
      3. ``STREAMDOC_YT_DLP_USER_AGENT`` (default user-agent)

    Args:
        opts: Base options dict to update.
        bypass_mode_override: When provided, use this mode instead of
            the effective bypass mode. Used by the cookie-DB-lock
            fallback retry logic.

    Returns:
        The updated options dict.
    """
    # Reason: use the effective bypass mode from pot_provider if set,
    # so the downloader respects the runtime fallback decision (e.g.
    # po_token → cookies_from_browser when Docker is not available).
    if bypass_mode_override is not None:
        mode = bypass_mode_override
    else:
        try:
            from streamdoc.core.pot_provider import get_effective_bypass_mode
            mode = get_effective_bypass_mode()
        except ImportError:
            mode = settings.yt_dlp_bypass_mode

    # --- PO-Token bypass (base layer) ---
    if mode == "po_token":
        provider = settings.yt_dlp_pot_provider or "bgutil"
        # Reason: pass the POT provider server URL as base_url so the
        # bgutil plugin knows where to fetch tokens. This lets users
        # run the container on a custom port or host.
        pot_url = settings.pot_provider_url
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["default", "web"],
                "pot_provider": [provider],
            },
            "youtubepot-bgutilhttp": {
                "base_url": [pot_url],
            },
        }

    # --- Cookie bypass (base layer) ---
    if mode == "cookie":
        cookie = _resolve_cookie_path()
        if cookie:
            opts["cookiefile"] = str(cookie)
        else:
            logger.warning(
                "bypass_mode=cookie but cookie jar not found at %s",
                settings.yt_dlp_cookiejar_path,
            )

    # --- web_embedded bypass (base layer) ---
    # Reason: YouTube IP-blocks DASH/HTTPS media downloads mid-stream
    # (HTTP 403 after ~20MB) for the android_vr client, and forces SABR
    # streaming for the web client (no direct format URLs). The
    # web_embedded client (WEB_EMBEDDED_PLAYER) appears as embedded player
    # traffic and gets full-quality HTTPS URLs (up to 4K) that complete
    # without 403. It does NOT require a PO token or cookies. It requires
    # a JS runtime (node/deno) to solve the n-challenge for format URLs.
    # Limitation: does not work for videos with embedding disabled.
    if mode == "web_embedded":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["web_embedded"],
            },
        }

    # --- HLS bypass (base layer) ---
    # Reason: the web_safari client provides HLS (m3u8) formats that bypass
    # YouTube's IP-level DASH download blocks. HLS is typically capped at
    # 480p, so this is a quality-degraded last resort. Requires a JS
    # runtime (node/deno) for the n-challenge solver.
    if mode == "hls":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["web_safari"],
            },
        }

    # --- Cookies-from-browser bypass (base layer) ---
    # Reason: reads cookies directly from the user's signed-in browser
    # session. This is the most reliable way to bypass YouTube's bot
    # detection without running a separate PO-token service. The
    # ``cookiesfrombrowser`` option is a tuple of
    # (browser, profile, keyring, container).
    if mode == "cookies_from_browser":
        browser = settings.yt_dlp_cookies_browser or "chrome"
        profile = settings.yt_dlp_cookies_browser_profile
        opts["cookiesfrombrowser"] = (browser, profile, None, None)

    # --- Extra raw args (user override) ---
    # Reason: extra args have the highest priority. They can override
    # extractor_args fields, cookie source, and user-agent, but they cannot
    # override the explicit caller-controlled keys (extract_flat, etc.)
    # set by build_ydl_opts after this function returns.
    extra = settings.yt_dlp_extra_args
    if extra:
        extra_opts = _parse_extra_args_to_opts(extra)
        if extra_opts:
            _deep_update(opts, extra_opts)

    # --- JS runtime for n-challenge solving (yt-dlp 2026.07+ EJS system) ---
    # Reason: without a JS runtime, yt-dlp cannot solve YouTube's n-challenge
    # and downloads fail with "Sign in to confirm you're not a bot" or
    # "Requested format is not available". We set this after extra args so
    # the user can override it via STREAMDOC_YT_DLP_EXTRA_ARGS if needed,
    # but before the caller-controlled keys in build_ydl_opts.
    js_runtimes = settings.yt_dlp_js_runtimes
    if js_runtimes and "js_runtimes" not in opts:
        opts["js_runtimes"] = _parse_js_runtimes(js_runtimes)

    # --- Default User-Agent (lowest priority) ---
    user_agent = settings.yt_dlp_user_agent
    if user_agent:
        headers = opts.setdefault("http_headers", {})
        # Reason: extra args may set --user-agent or --add-header. Only set
        # a default User-Agent if none was provided by extra args.
        if not headers.get("User-Agent"):
            headers["User-Agent"] = user_agent

    # --- JS runtimes (yt-dlp 2026.07+ n-challenge solver) ---
    # Reason: only set if not already provided via extra args, so the
    # user's explicit --js-runtimes / --no-js-runtimes wins.
    js_runtimes = _parse_js_runtimes(settings.yt_dlp_js_runtimes)
    if js_runtimes and "js_runtimes" not in opts:
        opts["js_runtimes"] = js_runtimes

    return opts


def build_common_args(
    *, include_progress: bool = False, bypass_mode_override: str | None = None
) -> list[str]:
    """Build the common yt-dlp CLI arguments based on current settings.

    Args:
        include_progress: Include ``--progress`` / ``--newline`` flags
            (useful for media downloads, noisy for metadata queries).
        bypass_mode_override: When provided, use this bypass mode instead of
            the effective bypass mode. Used by the cookie-DB-lock
            fallback retry logic.

    Returns:
        List of CLI argument strings (no binary, no URL).
    """
    args: list[str] = ["--no-warnings"]

    if include_progress:
        args.extend(["--progress", "--newline"])

    # --- Bypass mode ---
    # Reason: use the effective bypass mode from pot_provider if set,
    # so CLI args respect the runtime fallback decision.
    if bypass_mode_override is not None:
        mode = bypass_mode_override
    else:
        try:
            from streamdoc.core.pot_provider import get_effective_bypass_mode
            mode = get_effective_bypass_mode()
        except ImportError:
            mode = settings.yt_dlp_bypass_mode

    if mode == "po_token":
        # Reason: PRD 7.4.1.1 — PO-Token via bgutil provider.
        # Include "default" as a fallback client so that if the bgutil
        # PO Token service is not running, yt-dlp falls back to the
        # default client (android_vr) which does not require a PO token.
        # Without this fallback, the web client returns only storyboard
        # formats and downloads fail with "Requested format is not available".
        provider = settings.yt_dlp_pot_provider or "bgutil"
        pot_url = settings.pot_provider_url
        args.extend([
            "--extractor-args",
            f"youtube:player_client=default,web;pot_provider={provider}",
            "--extractor-args",
            f"youtubepot-bgutilhttp:base_url={pot_url}",
        ])

    if mode == "cookie":
        cookie = _resolve_cookie_path()
        if cookie:
            args.extend(["--cookiefile", str(cookie)])
        else:
            logger.warning("bypass_mode=cookie but cookie jar not found at %s", settings.yt_dlp_cookiejar_path)

    if mode == "web_embedded":
        # Reason: web_embedded client bypasses IP-level 403 blocks on
        # DASH/HTTPS media downloads and gets full-quality URLs (up to 4K)
        # without requiring a PO token or cookies. Requires a JS runtime
        # (node/deno) for n-challenge solving. Does not work for videos
        # with embedding disabled.
        args.extend([
            "--extractor-args",
            "youtube:player_client=web_embedded",
        ])

    if mode == "hls":
        # Reason: web_safari client provides HLS (m3u8) formats that bypass
        # IP-level DASH blocks. Capped at 480p — quality-degraded last resort.
        args.extend([
            "--extractor-args",
            "youtube:player_client=web_safari",
        ])

    if mode == "cookies_from_browser":
        browser = settings.yt_dlp_cookies_browser or "chrome"
        profile = settings.yt_dlp_cookies_browser_profile
        # Reason: yt-dlp CLI format is BROWSER[:PROFILE]. The profile is
        # optional; omit the colon entirely when no profile is set so
        # yt-dlp uses the browser's default profile.
        browser_arg = f"{browser}:{profile}" if profile else browser
        args.extend(["--cookies-from-browser", browser_arg])

    # --- JS runtime for n-challenge solving (yt-dlp 2026.07+ EJS system) ---
    # Reason: without a JS runtime, yt-dlp cannot solve YouTube's n-challenge
    # and downloads fail with "Sign in to confirm you're not a bot" or
    # "Requested format is not available". Node is the default since it's
    # the most commonly installed runtime; Deno is yt-dlp's own default.
    extra = settings.yt_dlp_extra_args
    js_runtimes = settings.yt_dlp_js_runtimes
    if js_runtimes and "--js-runtimes" not in (extra or ""):
        args.extend(["--js-runtimes", js_runtimes])

    # --- Default user-agent (can be overridden by extra args below) ---
    user_agent = settings.yt_dlp_user_agent
    if user_agent and "--user-agent" not in (extra or ""):
        args.extend(["--user-agent", user_agent])

    # --- JS runtimes (yt-dlp 2026.07+ n-challenge solver) ---
    # Reason: only append if not already supplied via extra args, so the
    # user's explicit --js-runtimes / --no-js-runtimes wins.
    js_runtimes = settings.yt_dlp_js_runtimes
    if js_runtimes and "--js-runtimes" not in (extra or ""):
        for raw in js_runtimes.split(","):
            entry = raw.strip()
            if entry:
                args.extend(["--js-runtimes", entry])

    # --- Extra raw args from env (highest priority, appended last) ---
    if extra:
        args.extend(shlex.split(extra))

    return args


# ---------------------------------------------------------------------------
# Subprocess invocation helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    """Execute a yt-dlp subprocess command."""
    return subprocess.run(cmd, check=check, text=True, capture_output=True, shell=False)


def _resolve_effective_mode(bypass_mode_override: str | None = None) -> str:
    """Resolve the bypass mode that will actually be applied to yt-dlp args.

    Reason: centralises the mode-resolution logic so both the CLI and Python
    API paths log the same value the user sees applied. Used for the
    per-download INFO log that makes it visible which bypass strategy was
    used (po_token / cookies_from_browser / cookie / default).

    Args:
        bypass_mode_override: When provided, this mode is used instead of the
            runtime effective mode (used by the cookie-DB-lock fallback retry).

    Returns:
        The bypass mode string that will be applied.
    """
    if bypass_mode_override is not None:
        return bypass_mode_override
    try:
        from streamdoc.core.pot_provider import get_effective_bypass_mode
        return get_effective_bypass_mode()
    except ImportError:
        return settings.yt_dlp_bypass_mode


def _get_fallback_bypass_mode() -> str | None:
    """Return the fallback bypass mode if configured and different from primary.

    Reason: when the primary bypass mode is ``cookies_from_browser`` and the
    target browser's cookie DB is locked (Chrome/Edge running on Windows),
    yt-dlp fails with "Could not copy Chrome cookie database" (issue #7271).
    If the user has configured ``STREAMDOC_YT_DLP_BYPASS_FALLBACK_MODE``,
    we retry with that mode instead of failing the entire download.

    Returns:
        The fallback bypass mode string, or None if not configured or same
        as the primary mode.
    """
    fallback = settings.yt_dlp_bypass_fallback_mode
    if not fallback or fallback == settings.yt_dlp_bypass_mode:
        return None
    return fallback


def _get_fallback_bypass_modes() -> list[str]:
    """Return the ordered list of fallback bypass modes to try.

    Reason: ``STREAMDOC_YT_DLP_BYPASS_FALLBACK_MODE`` can be a single mode
    or a comma-separated chain (e.g. ``"cookie,default"``). When the first
    fallback fails (e.g. cookie DB lock), the next mode in the chain is
    tried. The default fallback is ``"default"`` (no-auth) which is safe
    but may hit bot detection on some videos.

    NOTE: ``cookies_from_browser`` is opt-in only. Reading cookies from
    the user's active browser profile risks getting their YouTube account
    banned. It should never be used as an automatic fallback.

    Returns:
        Ordered list of fallback mode strings, excluding the primary mode
        and any empty entries. Empty list if no fallback is configured.
    """
    fallback = settings.yt_dlp_bypass_fallback_mode
    if not fallback:
        return []
    primary = settings.yt_dlp_bypass_mode
    modes = [m.strip() for m in fallback.split(",") if m.strip()]
    # Reason: exclude the primary mode from the fallback chain — retrying
    # with the same mode that just failed is pointless.
    return [m for m in modes if m != primary]


def _log_cookie_db_lock_guidance() -> None:
    """Log actionable guidance when a cookie DB lock error is detected."""
    logger.warning(
        "Browser cookie database is locked (yt-dlp issue #7271). "
        "This happens when Chrome/Edge is running on Windows. "
        "Options: (1) close the browser, (2) set STREAMDOC_YT_DLP_COOKIES_BROWSER=firefox "
        "(Firefox does not lock its DB), (3) export cookies to a Netscape file and use "
        "bypass_mode=cookie, (4) set STREAMDOC_YT_DLP_BYPASS_FALLBACK_MODE=default for "
        "no-auth fallback. NOTE: cookies_from_browser with your personal profile risks "
        "getting your YouTube account banned — use a dedicated profile if you opt in."
    )


# Reason: the complete set of bypass modes the chain can contain. Used by
# _resolve_bypass_chain() to validate entries and by the frontend to build
# the picklist. Keep in sync with the yt_dlp_bypass_chain config docstring.
SUPPORTED_BYPASS_MODES: frozenset[str] = frozenset(
    {"web_embedded", "po_token", "cookie", "cookies_from_browser", "hls", "default"}
)


def _resolve_bypass_chain() -> list[str]:
    """Return the ordered list of bypass modes to try for downloads.

    Reason: when ``yt_dlp_bypass_chain`` is non-empty, it takes precedence
    over the legacy ``yt_dlp_bypass_mode`` + ``yt_dlp_bypass_fallback_mode``
    pair. Each mode is tried in order; on retriable failure the next mode
    is tried. When the chain is empty, the legacy single-mode + single-
    fallback behavior is preserved for backward compatibility.

    Returns:
        Ordered list of validated bypass mode strings. May be empty if
        the chain setting is unset and the caller should fall back to
        legacy behavior.
    """
    raw = settings.yt_dlp_bypass_chain.strip()
    if not raw:
        return []
    modes: list[str] = []
    for entry in raw.split(","):
        mode = entry.strip()
        if mode and mode in SUPPORTED_BYPASS_MODES:
            modes.append(mode)
        elif mode:
            logger.warning(
                "Ignoring unknown bypass mode '%s' in yt_dlp_bypass_chain "
                "(supported: %s)",
                mode,
                ", ".join(sorted(SUPPORTED_BYPASS_MODES)),
            )
    return modes


# Reason: YouTube's bot detection is not uniform — some channels/videos get
# stricter challenges that the PO token alone cannot satisfy. These transient
# error categories are candidates for an automatic fallback retry with a
# different bypass mode. HTTP 403 is included because it's often a PO-token
# binding issue that a different bypass mode can resolve.
# NOTE: cookies_from_browser is never used as an automatic fallback — reading
# cookies from the user's active browser profile risks getting their YouTube
# account banned. It is opt-in only via explicit STREAMDOC_YT_DLP_BYPASS_MODE
# or STREAMDOC_YT_DLP_BYPASS_FALLBACK_MODE configuration.
_FALLBACK_RETRY_CATEGORIES: frozenset[str] = frozenset(
    {"cookie_db_locked", "bot_detection", "rate_limited", "login_required", "http_403"}
)


def _should_fallback_retry(stderr: str) -> bool:
    """Return True if the error is a candidate for fallback bypass retry.

    Reason: the cookie DB lock is an infrastructure error, while
    bot_detection / rate_limited / login_required are YouTube-side transient
    challenges. All of them may succeed with a different bypass mode, so we
    retry once with the configured fallback mode before giving up.

    Args:
        stderr: The yt-dlp stderr output or exception message.

    Returns:
        True if the error category is in ``_FALLBACK_RETRY_CATEGORIES``.
    """
    return classify_download_error(stderr) in _FALLBACK_RETRY_CATEGORIES


def _is_http_403_error(stderr: str) -> bool:
    """Return True if the error is an HTTP 403 on media download.

    Reason: YouTube IP-blocks DASH/HTTPS format URLs (returns 403 when
    yt-dlp tries to download the actual video bytes), while HLS (m3u8)
    formats from the ``web_safari`` client remain accessible. This
    detection triggers the HLS fallback retry path.
    """
    return classify_download_error(stderr) == "http_403"


def _hls_format_selector() -> str:
    """Build a format selector that prefers HLS formats.

    Reason: when YouTube IP-blocks DASH downloads, the only working formats
    are HLS (m3u8) from the ``web_safari`` client. HLS formats are
    progressive (combined audio+video) and typically capped at 480p, so
    we use a simple height-filtered ``best`` selector rather than the
    DASH-style ``bestvideo+bestaudio`` selector.
    """
    res = settings.video_resolution
    if res == "best":
        return "best/bestvideo+bestaudio"
    height = int(res)
    # Reason: HLS formats from web_safari are progressive (audio+video
    # combined), so we use a single-stream selector. The final /best
    # fallback catches cases where the height filter excludes all HLS
    # formats but a lower-quality one is still available.
    return f"best[height<={height}]/best"


def _build_hls_fallback_cmd(
    binary: str, output_template: str, url: str
) -> list[str]:
    """Build a yt-dlp command that uses the web_safari HLS client.

    Reason: the ``web_safari`` client provides HLS (m3u8) formats that
    bypass YouTube's IP-level DASH download blocks. We override the
    player_client to ``web_safari`` and use an HLS-compatible format
    selector. The JS runtime (node) is still required for the n-challenge
    solver. PO-token bypass args are omitted because web_safari HLS
    formats do not require a GVS PO token (per yt-dlp PO Token Guide).

    Args:
        binary: Path to the yt-dlp binary.
        output_template: The ``-o`` output template.
        url: The video URL to download.

    Returns:
        A complete yt-dlp command list (without the URL appended yet).
    """
    args: list[str] = [
        binary,
        "--no-warnings",
        "--progress",
        "--newline",
        # Reason: web_safari provides HLS (m3u8) formats that bypass
        # YouTube's IP-level DASH download blocks.
        "--extractor-args",
        "youtube:player_client=web_safari",
    ]

    # JS runtimes (still needed for n-challenge solver)
    js_runtimes = settings.yt_dlp_js_runtimes
    if js_runtimes:
        for raw in js_runtimes.split(","):
            entry = raw.strip()
            if entry:
                args.extend(["--js-runtimes", entry])

    # Extra raw args (highest priority, appended last)
    extra = settings.yt_dlp_extra_args
    if extra:
        args.extend(shlex.split(extra))

    args.extend([
        "-f", _hls_format_selector(),
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ])
    return args


def dump_json(
    url: str,
    *,
    flat_playlist: bool = False,
    dump_single_json: bool = False,
    playlist_end: int | None = None,
) -> dict[str, Any]:
    """Run ``yt-dlp --dump-json`` / ``--dump-single-json`` and return parsed JSON.

    Args:
        url: YouTube URL to query.
        flat_playlist: Pass ``--flat-playlist`` for quick metadata without
            extracting individual video details (avoids rate-limiting).
        dump_single_json: Pass ``--dump-single-json`` to get the
            playlist/channel-level JSON instead of per-entry lines.
            Use this for channel resolution to get uploader_id, channel_id, etc.
        playlist_end: Limit number of playlist entries.

    Returns:
        Parsed JSON dict from yt-dlp.

    Raises:
        RuntimeError: If yt-dlp exits non-zero or output is unparseable.
    """
    binary = _yt_dlp_binary()
    # Reason: when the bypass chain is active, metadata queries use only
    # the first mode in the chain (no need to iterate — metadata extraction
    # is lightweight and the first mode is the most effective). When the
    # chain is empty, fall back to the legacy effective mode.
    chain = _resolve_bypass_chain()
    if chain:
        mode = chain[0]
        logger.debug("dump_json %s with bypass_mode=%s (chain[0])", url, mode)
        cmd = [binary, *build_common_args(bypass_mode_override=mode)]
    else:
        mode = _resolve_effective_mode()
        logger.debug("dump_json %s with bypass_mode=%s", url, mode)
        cmd = [binary, *build_common_args()]

    if dump_single_json:
        cmd.append("--dump-single-json")
    else:
        cmd.append("--dump-json")

    if flat_playlist:
        cmd.append("--flat-playlist")
    if playlist_end is not None:
        cmd.extend(["--playlist-end", str(playlist_end)])
    cmd.append(url)

    logger.debug("yt-dlp dump_json cmd: %s", " ".join(cmd))
    result = _run(cmd)
    if result.returncode != 0:
        original_err = result.stderr or result.stdout or f"yt-dlp exited {result.returncode}"
        original_category = classify_download_error(original_err)
        # Reason: retry with the fallback bypass mode(s) for infrastructure and
        # transient YouTube errors (cookie DB lock, bot detection, rate
        # limiting, login required, HTTP 403). These may succeed with a
        # different bypass strategy. When the bypass chain is active, use the
        # remaining chain modes. When empty, use the legacy fallback modes.
        if _should_fallback_retry(original_err):
            logger.warning(
                "Primary bypass mode=%s failed for dump_json %s [%s]: %s",
                mode, url, original_category, original_err.strip()[:300],
            )
            if is_cookie_db_lock_error(original_err):
                _log_cookie_db_lock_guidance()
            # Reason: when using the chain, try the remaining modes (chain[1:]).
            # When empty, fall back to the legacy multi-fallback list.
            if chain:
                fallback_modes = chain[1:]
            else:
                fallback_modes = _get_fallback_bypass_modes()
            success = False
            for fb_mode in fallback_modes:
                logger.info(
                    "Retrying dump_json with fallback bypass mode=%s (category=%s)",
                    fb_mode,
                    original_category,
                )
                cmd = [binary, *build_common_args(bypass_mode_override=fb_mode)]
                if dump_single_json:
                    cmd.append("--dump-single-json")
                else:
                    cmd.append("--dump-json")
                if flat_playlist:
                    cmd.append("--flat-playlist")
                if playlist_end is not None:
                    cmd.extend(["--playlist-end", str(playlist_end)])
                cmd.append(url)
                fallback_result = _run(cmd)
                if fallback_result.returncode == 0:
                    result = fallback_result
                    success = True
                    break
                # Reason: this fallback failed. Log it and try the next mode.
                fb_err = fallback_result.stderr or fallback_result.stdout or ""
                fb_category = classify_download_error(fb_err)
                logger.warning(
                    "Fallback bypass mode=%s also failed for dump_json %s [%s]: %s",
                    fb_mode, url, fb_category, fb_err.strip()[:300],
                )
            if not success:
                # Reason: all fallbacks failed. Raise the ORIGINAL error
                # (not a fallback error) because it's the real root cause.
                # A cookie_db_locked fallback error is misleading when the
                # real issue was bot_detection on the primary attempt.
                raise RuntimeError(original_err)
        else:
            raise RuntimeError(original_err)
    try:
        return json.loads(result.stdout)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse yt-dlp JSON output") from exc


def _format_selector() -> str:
    """Build yt-dlp format selector based on resolution settings."""
    res = settings.video_resolution
    fallback = settings.video_format_fallback
    if res == "best":
        return "bestvideo+bestaudio/best"
    height = int(res)
    if fallback:
        # Prefer exact height, then lower heights down to 360p
        return f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    return f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best"


def download(url: str, output_template: str) -> subprocess.CompletedProcess:
    """Download media via yt-dlp using the configured bypass chain.

    When ``yt_dlp_bypass_chain`` is non-empty, each mode is tried in order.
    On retriable failure (HTTP 403, bot detection, rate limit, cookie DB
    lock) the next mode is tried. On success or permanent error (private,
    deleted, members-only) the chain stops immediately.

    When the chain is empty, the legacy behavior is preserved: the primary
    bypass mode is tried, then the single fallback mode, then the HLS
    fallback (if enabled).

    Args:
        url: Video URL.
        output_template: ``-o`` template string.

    Returns:
        CompletedProcess (caller checks returncode).
    """
    binary = _yt_dlp_binary()
    chain = _resolve_bypass_chain()

    # --- Chain path: iterate modes in order ---
    if chain:
        total = len(chain)
        logger.info("Downloading %s via bypass chain (%d modes): %s", url, total, ", ".join(chain))
        result: subprocess.CompletedProcess[str] | None = None
        for i, mode in enumerate(chain):
            step = i + 1
            # Reason: hls mode uses the HLS format selector (progressive,
            # capped at 480p) instead of the DASH bestvideo+bestaudio
            # selector used by all other modes.
            fmt = _hls_format_selector() if mode == "hls" else _format_selector()
            logger.info("Chain step %d/%d: trying bypass_mode=%s", step, total, mode)
            cmd = [
                binary,
                *build_common_args(include_progress=True, bypass_mode_override=mode),
                "-f", fmt,
                "--merge-output-format", "mp4",
                "-o", output_template,
                url,
            ]
            result = _run(cmd)
            if result.returncode == 0:
                logger.info("Chain step %d/%d succeeded with bypass_mode=%s", step, total, mode)
                return result
            err = result.stderr or result.stdout or ""
            category = classify_download_error(err)
            # Reason: permanent errors (private, deleted, members-only,
            # age-restricted, region-blocked) will never succeed with a
            # different bypass mode — stop the chain immediately.
            if is_permanent_error(category):
                logger.info(
                    "Chain step %d/%d failed with permanent error (%s) — stopping chain",
                    step, total, category,
                )
                return result
            if is_cookie_db_lock_error(err):
                _log_cookie_db_lock_guidance()
            # Reason: retriable error — log and continue to the next mode.
            if step < total:
                logger.info(
                    "Chain step %d/%d failed (%s) — trying next mode",
                    step, total, category,
                )
            else:
                logger.warning(
                    "Chain exhausted (all %d modes failed). Last error: %s",
                    total, category,
                )
        # Reason: all modes failed; return the last result so the caller
        # sees the final error.
        assert result is not None
        return result

    # --- Legacy path: single mode + single fallback + HLS fallback ---
    mode = _resolve_effective_mode()
    logger.info("Downloading %s with bypass_mode=%s (legacy, no chain)", url, mode)
    cmd = [
        binary,
        *build_common_args(include_progress=True),
        "-f", _format_selector(),
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]
    result = _run(cmd)
    # Reason: retry with the fallback bypass mode(s) for infrastructure and
    # transient YouTube errors (cookie DB lock, bot detection, rate limiting,
    # login required, HTTP 403). The fallback chain supports multiple
    # comma-separated modes — if the first fallback fails (e.g. cookie DB
    # lock), the next mode is tried. The default fallback is "default"
    # (no-auth) which is safe but may hit bot detection on some videos.
    # cookies_from_browser is opt-in only (ban risk on personal profiles).
    if result.returncode != 0:
        original_err = result.stderr or result.stdout or ""
        original_category = classify_download_error(original_err)
        if _should_fallback_retry(original_err):
            # Reason: log the original error at WARNING so the operator can
            # see WHY the primary bypass mode failed, even if a fallback
            # succeeds. Without this, the original error is invisible.
            logger.warning(
                "Primary bypass mode=%s failed for %s [%s]: %s",
                mode, url, original_category, original_err.strip()[:300],
            )
            if is_cookie_db_lock_error(original_err):
                _log_cookie_db_lock_guidance()
            fallback_modes = _get_fallback_bypass_modes()
            for fb_mode in fallback_modes:
                logger.info(
                    "Retrying download with fallback bypass mode=%s (category=%s)",
                    fb_mode,
                    original_category,
                )
                cmd = [
                    binary,
                    *build_common_args(
                        include_progress=True, bypass_mode_override=fb_mode
                    ),
                    "-f", _format_selector(),
                    "--merge-output-format", "mp4",
                    "-o", output_template,
                    url,
                ]
                fallback_result = _run(cmd)
                if fallback_result.returncode == 0:
                    return fallback_result
                # Reason: this fallback failed. Log it and try the next mode
                # in the chain. If this fallback hit a cookie DB lock, skip
                # the cookie-DB-lock guidance (already logged above) and move
                # to the next mode silently.
                fb_err = fallback_result.stderr or fallback_result.stdout or ""
                fb_category = classify_download_error(fb_err)
                logger.warning(
                    "Fallback bypass mode=%s also failed for %s [%s]: %s",
                    fb_mode, url, fb_category, fb_err.strip()[:300],
                )
                # Reason: if this fallback failed with cookie_db_locked, don't
                # return it as the final error — the ORIGINAL error is the real
                # root cause. Save the fallback result only if it's a different
                # category (more actionable than the original).
                if fb_category != "cookie_db_locked":
                    result = fallback_result
            # Reason: if we get here, all fallbacks failed. If none of them
            # returned a non-cookie-db-locked error, result still has the
            # original error (which is the real root cause).
            if result.returncode != 0 and classify_download_error(
                result.stderr or result.stdout or ""
            ) == "cookie_db_locked":
                result.stderr = original_err
                result.stdout = ""
        # Reason: non-transient errors (permanent or unclassified) skip the
        # fallback chain — the original result already has the right error.
    # Reason: legacy HLS fallback for backward compat. When the bypass chain
    # is active, hls is a chain entry and this block never runs.
    if result.returncode != 0 and settings.yt_dlp_hls_fallback_enabled:
        err = result.stderr or result.stdout or ""
        if _is_http_403_error(err):
            logger.warning(
                "Download failed with HTTP 403 (YouTube IP-blocks DASH). "
                "Retrying with web_safari HLS fallback (quality may be reduced)."
            )
            hls_cmd = _build_hls_fallback_cmd(binary, output_template, url)
            result = _run(hls_cmd)
    return result


# ---------------------------------------------------------------------------
# Python API helper (for _list_videos)
# ---------------------------------------------------------------------------

def build_ydl_opts(
    *,
    quiet: bool = True,
    extract_flat: bool | str = "in_playlist",
    dump_single_json: bool = True,
    playlistend: int = 100,
    bypass_mode_override: str | None = None,
) -> dict[str, Any]:
    """Build an ``yt_dlp.YoutubeDL`` options dict that mirrors CLI bypass config.

    The Python API does not support ``--extractor-args`` or ``--user-agent``
    as raw strings, so we translate the relevant settings into the equivalent
    dict keys and apply them consistently.

    Args:
        quiet: Suppress yt-dlp console output.
        extract_flat: Flat extraction mode for playlist/channel listings.
        dump_single_json: Return playlist-level JSON instead of per-entry.
        playlistend: Max number of playlist entries to extract.
        bypass_mode_override: When provided, use this bypass mode instead of
            ``settings.yt_dlp_bypass_mode``. Used by the cookie-DB-lock
            fallback retry logic.

    Returns:
        Options dict suitable for ``yt_dlp.YoutubeDL(ydl_opts)``.
    """
    opts: dict[str, Any] = {
        "quiet": quiet,
    }

    # Reason: apply bypass/cookie/user-agent/extra-args first. Then set the
    # explicit caller-controlled keys on top so they cannot be overridden by
    # STREAMDOC_YT_DLP_EXTRA_ARGS.
    _apply_bypass_opts(opts, bypass_mode_override=bypass_mode_override)

    opts["quiet"] = quiet
    opts["extract_flat"] = extract_flat
    opts["dump_single_json"] = dump_single_json
    opts["playlistend"] = playlistend

    return opts
