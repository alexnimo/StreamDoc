"""Social platform configuration and auth status routes."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import urllib.error
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import (
    RedditStatusOut,
    SocialAuthResponse,
    SocialSourceResolveRequest,
    SocialSourceResolveResponse,
    SocialStatusOut,
    SocialTestResponse,
    StocktwitsStatusOut,
    TwitterStatusOut,
)
from streamdoc.config import settings
from streamdoc.integrations.social.auth import (
    reddit_auth_manager,
    seed_reddit_credentials_from_settings,
    x_auth_manager,
)
from streamdoc.integrations.social.reddit import (
    _rdt_is_authenticated,
    find_rdt_binary,
    get_rdt_version,
    resolve_subreddit,
)
from streamdoc.integrations.social.stocktwits import (
    _STOCKTWITS_BASE,
    _fetch_stocktwits_json,
    resolve_stocktwits_source,
)
from streamdoc.integrations.social.x import (
    get_twitter_binary,
    get_twitter_version,
    is_twitter_authenticated,
    resolve_x_source,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social", tags=["social"])


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check_stocktwits_reachability() -> dict[str, Any]:
    """Probe the Stocktwits public API and return status info.

    Uses the same ``curl_cffi`` fallback as the collector so the status
    check does not fail on a Cloudflare challenge when the API is in fact
    reachable.
    """
    url = f"{_STOCKTWITS_BASE.rstrip('/')}/trending/symbols.json"
    try:
        _fetch_stocktwits_json(url, timeout=5)
        return {
            "api_reachable": True,
            "rate_limit_remaining": None,
            "message": "Stocktwits API is reachable.",
        }
    except urllib.error.HTTPError as exc:
        return {
            "api_reachable": exc.code in {200, 429},
            "rate_limit_remaining": None,
            "message": f"Stocktwits returned HTTP {exc.code}.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "api_reachable": False,
            "rate_limit_remaining": None,
            "message": f"Could not reach Stocktwits: {exc}",
        }


def _twitter_status() -> dict[str, Any]:
    """Check twitter-cli binary, version, and authentication state."""
    binary = get_twitter_binary()
    if not binary:
        return {
            "binary_found": False,
            "version": None,
            "authenticated": False,
            "message": "twitter binary not found. Install via `uv tool install twitter-cli`.",
        }

    # Reason: version and auth are independent; run them in parallel so a
    # slow ``whoami`` does not block the version probe.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        version_future = pool.submit(get_twitter_version, binary)
        auth_future = pool.submit(is_twitter_authenticated, binary)
        try:
            version = version_future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            version = None
        try:
            authenticated = auth_future.result(timeout=20)
        except concurrent.futures.TimeoutError:
            authenticated = False

    return {
        "binary_found": True,
        "version": version,
        "authenticated": authenticated,
        "message": "Authenticated" if authenticated else "Not authenticated. Run Authorize.",
    }


def _reddit_status() -> dict[str, Any]:
    """Check rdt-cli binary, version, and authentication state."""
    binary = find_rdt_binary()
    if not binary:
        return {
            "binary_found": False,
            "version": None,
            "authenticated": False,
            "message": "rdt binary not found. Install via `uv tool install rdt-cli`.",
        }

    seed_error = seed_reddit_credentials_from_settings()
    if seed_error:
        return {
            "binary_found": True,
            "version": None,
            "authenticated": False,
            "message": f"Reddit not authenticated: {seed_error}",
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        version_future = pool.submit(get_rdt_version, binary)
        auth_future = pool.submit(_rdt_is_authenticated, binary)
        try:
            version = version_future.result(timeout=3)
        except concurrent.futures.TimeoutError:
            version = None
        try:
            authenticated = auth_future.result(timeout=3)
        except concurrent.futures.TimeoutError:
            authenticated = False

    return {
        "binary_found": True,
        "version": version,
        "authenticated": authenticated,
        "message": "Cookies present" if authenticated else "Not authenticated. Run Authorize.",
    }


def _stocktwits_status() -> dict[str, Any]:
    """Check Stocktwits API reachability."""
    result = _check_stocktwits_reachability()
    return {
        "api_reachable": result["api_reachable"],
        "rate_limit_remaining": result.get("rate_limit_remaining"),
        "message": result["message"],
    }


@router.get("/status", response_model=SocialStatusOut)
async def get_social_status() -> SocialStatusOut:
    """Return the authentication and connectivity status for each social platform.

    The three platform checks run concurrently so the settings page loads
    quickly even when one of the CLI binaries is missing or the network is
    slow. Each probe has a short individual timeout.
    """
    now = _now_iso()

    async def _twitter() -> dict[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(_twitter_status), timeout=30)

    async def _reddit() -> dict[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(_reddit_status), timeout=8)

    async def _stocktwits() -> dict[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(_check_stocktwits_reachability), timeout=8)

    try:
        twitter, reddit, stocktwits = await asyncio.gather(
            _twitter(), _reddit(), _stocktwits()
        )
    except TimeoutError:
        # Reason: if any probe hung, report the remaining checks and mark
        # the timed-out platform as unavailable rather than failing the
        # whole request.
        twitter = {"binary_found": False, "version": None, "authenticated": False, "message": "Status check timed out."}
        reddit = {"binary_found": False, "version": None, "authenticated": False, "message": "Status check timed out."}
        stocktwits = {"api_reachable": False, "rate_limit_remaining": None, "message": "Status check timed out."}

    return SocialStatusOut(
        twitter=TwitterStatusOut(
            binary_found=twitter["binary_found"],
            version=twitter["version"],
            authenticated=twitter["authenticated"],
            message=twitter["message"],
            last_check=now,
        ),
        reddit=RedditStatusOut(
            binary_found=reddit["binary_found"],
            version=reddit["version"],
            authenticated=reddit["authenticated"],
            message=reddit["message"],
            last_check=now,
        ),
        stocktwits=StocktwitsStatusOut(
            api_reachable=stocktwits["api_reachable"],
            rate_limit_remaining=stocktwits.get("rate_limit_remaining"),
            message=stocktwits["message"],
            last_check=now,
        ),
    )


@router.post("/auth/{platform}", response_model=SocialAuthResponse)
def auth_platform(platform: str, action: str = "login") -> SocialAuthResponse:
    """Run the social platform auth/refresh/logout flow and return the result."""
    platform = platform.lower()
    action = action.lower()
    cdp_url = settings.social_cdp_url

    if platform == "twitter":
        manager = x_auth_manager()
        if action == "login":
            message = manager.start_login(cdp_url=cdp_url)
            return SocialAuthResponse(platform="twitter", started=True, message=message)
        if action == "refresh":
            ok = manager.refresh(cdp_url=cdp_url)
            return SocialAuthResponse(
                platform="twitter",
                started=True,
                message="X refreshed" if ok else "X refresh failed. Try logging in again.",
            )
        if action == "logout":
            ok = manager.logout()
            return SocialAuthResponse(
                platform="twitter",
                started=False,
                message="X logged out" if ok else "No X session to clear.",
            )
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    if platform == "reddit":
        manager = reddit_auth_manager()
        if action == "login":
            message = manager.start_login(cdp_url=cdp_url)
            return SocialAuthResponse(platform="reddit", started=True, message=message)
        if action == "refresh":
            ok = manager.refresh(cdp_url=cdp_url)
            return SocialAuthResponse(
                platform="reddit",
                started=True,
                message="Reddit refreshed" if ok else "Reddit refresh failed. Try logging in again.",
            )
        if action == "logout":
            ok = manager.logout()
            return SocialAuthResponse(
                platform="reddit",
                started=False,
                message="Reddit logged out" if ok else "No Reddit session to clear.",
            )
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    raise HTTPException(status_code=400, detail=f"Unknown social platform: {platform}")


@router.post("/test/{platform}", response_model=SocialTestResponse)
def test_platform(platform: str) -> SocialTestResponse:
    """Test connectivity for a social platform without running an auth flow."""
    platform = platform.lower()
    if platform == "twitter":
        status = _twitter_status()
        return SocialTestResponse(
            platform="twitter",
            success=status["binary_found"],
            message=status["message"],
        )

    if platform == "reddit":
        status = _reddit_status()
        return SocialTestResponse(
            platform="reddit",
            success=status["binary_found"],
            message=status["message"],
        )

    if platform == "stocktwits":
        status = _check_stocktwits_reachability()
        return SocialTestResponse(
            platform="stocktwits",
            success=status["api_reachable"],
            message=status["message"],
        )

    raise HTTPException(status_code=400, detail=f"Unknown social platform: {platform}")


@router.post("/resolve", response_model=SocialSourceResolveResponse)
def resolve_social_source(body: SocialSourceResolveRequest) -> SocialSourceResolveResponse:
    """Resolve/normalize a social source identifier and return a display name.

    Supported platforms: ``reddit``, ``stocktwits``, ``x``. Failures are
    non-fatal and return the user-supplied identifier so the form stays
    usable even when a platform API is rate-limited.
    """
    platform = body.platform.lower().strip()
    identifier = body.identifier.strip()
    resolvers = {
        "reddit": resolve_subreddit,
        "stocktwits": resolve_stocktwits_source,
        "x": resolve_x_source,
    }
    resolver = resolvers.get(platform)
    if not resolver:
        raise HTTPException(status_code=400, detail=f"Unknown social platform: {platform}")

    try:
        result = resolver(identifier)
    except Exception as exc:
        logger.exception("social source resolution failed for %s/%r", platform, identifier)
        raise HTTPException(status_code=500, detail=f"Resolution failed: {exc}")

    return SocialSourceResolveResponse(
        platform=platform,
        identifier=identifier,
        resolved_identifier=str(result.get("resolved_identifier") or identifier),
        display_name=str(result.get("display_name") or identifier),
        exists=bool(result.get("exists", False)),
    )
