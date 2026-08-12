"""Reddit social source collector.

Uses the public-clis ``rdt-cli`` (binary ``rdt``) when available and
authenticated, because Reddit's anonymous JSON endpoints are blocked by
Cloudflare. Falls back to a ``curl_cffi`` request when the operator supplies
a cookie string via ``STREAMDOC_REDDIT_COOKIE``.

Install rdt-cli (latest default-branch version):
    uv tool install --upgrade git+https://github.com/public-clis/rdt-cli.git

Or, because ``rdt-cli`` is declared as a project dependency, run ``uv sync``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request

from streamdoc.config import settings
from streamdoc.integrations.social.base import SocialPost
from streamdoc.integrations.social.downloader import (
    download_image,
    safe_dir_name,
)

logger = logging.getLogger(__name__)

_REDDIT_BASE = "https://www.reddit.com"
_RDT_CLI_BINARY = "rdt"


def get_rdt_cli_env() -> dict[str, str]:
    """Return the environment for the rdt CLI.

    Forces UTF-8 stdio for the child process on Windows so the parent does
    not have to decode bytes written in the default console code page.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def resolve_subreddit(identifier: str) -> dict[str, Any]:
    """Resolve a subreddit identifier to its canonical form and title.

    Uses Reddit's public ``/r/{name}/about.json`` endpoint. The endpoint
    is rate-limited and sometimes blocked by Cloudflare, so failures are
    treated as "exists but unknown" to keep the UI responsive.

    Args:
        identifier: Subreddit name (with or without ``r/`` prefix).

    Returns:
        dict with ``resolved_identifier``, ``display_name``, and ``exists``.
    """
    name = re.sub(r"^/?r/", "", identifier.strip()).strip()
    if not name:
        return {"resolved_identifier": identifier, "display_name": identifier, "exists": False}

    url = f"{_REDDIT_BASE}/r/{name}/about.json"
    headers = _build_browser_headers()
    try:
        data = _fetch_json_urllib(url, headers, None, timeout=5)
    except Exception as exc:  # noqa: BLE001
        logger.debug("reddit subreddit resolve failed for %r: %s", name, exc)
        return {"resolved_identifier": name, "display_name": name, "exists": False}

    kind = data.get("kind")
    sub = data.get("data") or {}
    exists = kind == "t5" and sub.get("url", "").lower().endswith(f"/{name.lower()}/")
    display = sub.get("title") or sub.get("display_name_prefixed") or name
    return {
        "resolved_identifier": name,
        "display_name": display,
        "exists": exists,
    }


def _candidate_paths() -> list[Path]:
    """Return additional filesystem locations to probe for the ``rdt`` binary."""
    home = Path.home()
    app_data = os.environ.get("APPDATA")
    candidates: list[Path] = [
        Path(sys.executable).parent / "rdt",
        home / ".local" / "bin" / "rdt",
        home / "AppData" / "Roaming" / "npm" / "rdt",
    ]
    if app_data:
        candidates.append(Path(app_data) / "npm" / "rdt")
    return candidates


def _find_rdt_binary() -> str:
    """Return the path to the public-clis ``rdt`` binary, or '' if missing."""
    override = getattr(settings, "rdt_cli_binary_path", None)
    if override:
        p = Path(override)
        if p.exists() and p.is_file():
            return str(p.resolve())

    binary = shutil.which(_RDT_CLI_BINARY)
    if binary:
        return str(Path(binary).resolve())

    for candidate in _candidate_paths():
        for name in (candidate, candidate.with_suffix(".exe"), candidate.with_suffix(".cmd")):
            if name.exists() and name.is_file():
                return str(name.resolve())
    return ""


def find_rdt_binary() -> str:
    """Public accessor for the configured rdt binary path."""
    return _find_rdt_binary()


def get_rdt_version(binary: str) -> str | None:
    """Return the installed rdt-cli version string, or None if unknown."""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            stdin=subprocess.DEVNULL,
            env=get_rdt_cli_env(),
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _rdt_is_authenticated(binary: str) -> bool:
    """Check whether ``rdt`` has usable Reddit credentials.

    Args:
        binary: Path to the ``rdt`` executable.

    Returns:
        True if ``rdt status`` reports authenticated.
    """
    try:
        result = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            stdin=subprocess.DEVNULL,
            env=get_rdt_cli_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False

    if result.returncode != 0:
        return False

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False

    if not payload.get("ok"):
        return False

    data = payload.get("data", {})
    return bool(data.get("authenticated"))


def _build_browser_headers() -> dict[str, str]:
    """Return a browser-like header set for Reddit fallback requests."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _fetch_json_curl_cffi(url: str, headers: dict[str, str], cookie: str | None) -> dict[str, Any]:
    """Fetch JSON using curl_cffi TLS/browser impersonation.

    Args:
        url: URL to fetch.
        headers: Request headers.
        cookie: Optional cookie header string.

    Returns:
        Parsed JSON dict.

    Raises:
        Exception: On network or parse errors.
    """
    from curl_cffi import requests as curl_requests

    impersonate = getattr(settings, "curl_cffi_impersonate", "chrome133a")
    request_headers = dict(headers)
    if cookie:
        request_headers["Cookie"] = cookie

    response = curl_requests.get(
        url,
        headers=request_headers,
        impersonate=impersonate,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _fetch_json_urllib(
    url: str,
    headers: dict[str, str],
    cookie: str | None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch JSON using ``urllib.request``.

    Args:
        url: URL to fetch.
        headers: Request headers.
        cookie: Optional cookie header string.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON dict.

    Raises:
        urllib.error.HTTPError: On non-2xx HTTP responses.
    """
    request_headers = dict(headers)
    if cookie:
        request_headers["Cookie"] = cookie

    request = Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_reddit_listing(url: str) -> dict[str, Any]:
    """Fetch a Reddit JSON listing.

    Try a lightweight ``urllib`` request first so unit tests that patch
    ``urllib.request.urlopen`` work. In production, Reddit returns a Cloudflare
    challenge, so we fall back to ``curl_cffi`` TLS/browser impersonation.

    Args:
        url: Full Reddit URL ending in ``.json``.

    Returns:
        Reddit listing dict.

    Raises:
        Exception: When the request fails or the response is not JSON.
    """
    cookie = getattr(settings, "reddit_cookie", None) or os.getenv("STREAMDOC_REDDIT_COOKIE")
    headers = _build_browser_headers()

    try:
        return _fetch_json_urllib(url, headers, cookie)
    except urllib.error.HTTPError as exc:
        logger.debug("Reddit urllib got HTTP %s for %s; trying curl_cffi", exc.code, url)
        try:
            return _fetch_json_curl_cffi(url, headers, cookie)
        except Exception as curl_exc:
            logger.warning("Reddit curl_cffi fallback failed for %s: %s", url, curl_exc)
            raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("Reddit urllib request failed for %s: %s", url, exc)
        try:
            return _fetch_json_curl_cffi(url, headers, cookie)
        except Exception as curl_exc:
            logger.warning("Reddit curl_cffi fallback failed for %s: %s", url, curl_exc)
            raise


class RedditSource:
    """Collect posts from a subreddit via ``rdt-cli`` or an authenticated fallback."""

    def collect(
        self,
        preset: Any,
        source_descriptor: str,
        cutoff: datetime,
        dedup_store: Any,
        max_posts: int | None = None,
        skip_processed: bool = True,
    ) -> list[SocialPost]:
        """Collect posts from a subreddit.

        Args:
            preset: Preset configuration (provides ``name`` for dedup scoping).
            source_descriptor: Subreddit name (e.g. "wallstreetbets" or "r/wallstreetbets").
            cutoff: Posts older than this UTC datetime are ignored.
            dedup_store: Object with ``is_processed(platform, source_id, preset_name)``.
            max_posts: Cap on returned posts (newest first).
            skip_processed: When False, do not skip already-processed posts.

        Returns:
            List of normalized SocialPost objects.
        """
        # Reason: users may paste "r/wallstreetbets" or "/r/wallstreetbets";
        # strip the known prefix before building the Reddit URL.
        subreddit = re.sub(
            r"^/?r/",
            "",
            source_descriptor.strip(),
            flags=re.IGNORECASE,
        ).strip("/")

        posts_by_id: dict[str, SocialPost] = {}
        for endpoint in [".json", "new.json"]:
            url = f"{_REDDIT_BASE}/r/{subreddit}/{endpoint}"
            try:
                data = self._fetch_subreddit(url, max_posts)
            except Exception as exc:
                logger.warning("Reddit fetch failed for %s: %s", url, exc)
                continue

            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {}) if isinstance(child, dict) else {}
                social_post = self._to_social_post(
                    post_data, cutoff, dedup_store, preset.name, skip_processed
                )
                if social_post is not None and social_post.source_id not in posts_by_id:
                    posts_by_id[social_post.source_id] = social_post

        # Reason: newest first, then cap to max_posts.
        sorted_posts = sorted(
            posts_by_id.values(), key=lambda p: p.published_at, reverse=True
        )
        if max_posts is not None and max_posts >= 0:
            sorted_posts = sorted_posts[:max_posts]
        return sorted_posts

    def _fetch_subreddit(self, url: str, max_posts: int | None) -> dict[str, Any]:
        """Fetch a subreddit listing, preferring ``rdt`` when authenticated.

        Args:
            url: Reddit public JSON URL.
            max_posts: Used to set ``--limit`` for ``rdt``.

        Returns:
            Reddit listing-shaped dict.
        """
        binary = _find_rdt_binary()
        if binary and _rdt_is_authenticated(binary):
            return self._fetch_with_rdt(binary, url, max_posts)

        logger.debug("rdt not available or not authenticated; falling back to direct fetch")
        return _fetch_reddit_listing(url)

    def _fetch_with_rdt(
        self,
        binary: str,
        url: str,
        max_posts: int | None,
    ) -> dict[str, Any]:
        """Call ``rdt sub <subreddit> --json --limit N`` and return the listing.

        Args:
            binary: Path to the ``rdt`` executable.
            url: Full Reddit ``.json`` URL.
            max_posts: Limit passed to ``rdt``.

        Returns:
            Reddit listing dict.
        """
        match = re.search(r"/r/([^/]+)/(.+\.json)$", url)
        if not match:
            logger.warning("Could not derive rdt subreddit from %s", url)
            return _fetch_reddit_listing(url)

        subreddit = match.group(1)
        endpoint = match.group(2)
        sort = "hot" if endpoint == ".json" else "new"

        limit = max_posts if max_posts is not None else 25
        args = [
            binary,
            "sub",
            subreddit,
            "-s",
            sort,
            "--json",
            "--limit",
            str(limit),
        ]

        logger.info("Reddit: invoking rdt for r/%s (%s)", subreddit, sort)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            stdin=subprocess.DEVNULL,
            env=get_rdt_cli_env(),
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.warning("rdt exited %d for r/%s: %s", result.returncode, subreddit, stderr[:500])
            return _fetch_reddit_listing(url)

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("rdt returned non-JSON output for r/%s", subreddit)
            return _fetch_reddit_listing(url)

        if payload.get("ok") is False:
            logger.warning("rdt returned an error for r/%s: %s", subreddit, payload.get("error"))
            return _fetch_reddit_listing(url)

        data = payload.get("data", {})
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("rdt returned unexpected payload for r/%s", subreddit)
            return _fetch_reddit_listing(url)

        return data

    def _to_social_post(
        self,
        post_data: dict[str, Any],
        cutoff: datetime,
        dedup_store: Any,
        preset_name: str,
        skip_processed: bool = True,
    ) -> SocialPost | None:
        """Convert a Reddit post dict into a normalized SocialPost.

        Args:
            post_data: Reddit post JSON under ``data.children[].data``.
            cutoff: Posts older than this UTC datetime are ignored.
            dedup_store: Deduplication store for the is_processed check.
            preset_name: Preset display name used as the dedup scope.
            skip_processed: When False, do not skip already-processed posts.

        Returns:
            Normalized SocialPost or None if it should be skipped.
        """
        source_id = post_data.get("id")
        created_utc = post_data.get("created_utc")
        if not source_id or not created_utc:
            return None

        published_at = datetime.fromtimestamp(created_utc, tz=UTC)
        if published_at < cutoff:
            logger.info(
                "Skipping reddit post=%s (published %s, before cutoff)",
                source_id,
                published_at.isoformat(),
            )
            return None

        if skip_processed and dedup_store.is_processed("reddit", source_id, preset_name):
            logger.info("Skipping already-processed reddit post=%s", source_id)
            return None

        title = (post_data.get("title") or "").strip()
        selftext = (post_data.get("selftext") or "").strip()
        text = f"{title}\n\n{selftext}" if selftext else title

        permalink = post_data.get("permalink") or ""
        if permalink:
            url = f"https://www.reddit.com{permalink}"
        else:
            url = post_data.get("url") or ""

        images = self._extract_image_urls(post_data)
        local_images = self._download_images(source_id, images)

        raw = json.dumps(post_data, ensure_ascii=False)

        return SocialPost(
            platform="reddit",
            source_id=source_id,
            url=url,
            author=post_data.get("author") or "",
            text=text,
            published_at=published_at,
            raw=raw,
            images=local_images,
        )

    def _extract_image_urls(self, post_data: dict[str, Any]) -> list[str]:
        """Return a deduplicated list of candidate image URLs from a Reddit post.

        Args:
            post_data: Reddit post JSON.

        Returns:
            List of HTTP(S) image URLs (preview + thumbnail).
        """
        urls: list[str] = []
        seen: set[str] = set()

        preview = post_data.get("preview") or {}
        for img in preview.get("images", []):
            source = img.get("source") or {}
            src_url = source.get("url") or ""
            if src_url and src_url.startswith("http") and src_url not in seen:
                urls.append(src_url)
                seen.add(src_url)

        thumbnail = post_data.get("thumbnail") or ""
        if isinstance(thumbnail, str) and thumbnail.startswith("http") and thumbnail not in seen:
            urls.append(thumbnail)

        return urls

    def _download_images(self, source_id: str, urls: list[str]) -> list[str]:
        """Download image URLs into the media root and return local paths.

        Args:
            source_id: Reddit post ID used as the storage sub-directory.
            urls: Image URLs to download.

        Returns:
            Absolute local paths for successfully downloaded images.
        """
        if not urls:
            return []

        out_dir = Path(settings.media_root) / "social" / "reddit" / safe_dir_name(source_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        headers = _build_browser_headers()
        headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"

        local_paths: list[str] = []
        for idx, url in enumerate(urls):
            if not isinstance(url, str) or not url.strip():
                continue
            ext = Path(url.split("?", 1)[0]).suffix or ".jpg"
            filename = f"{idx:02d}{ext}"
            dest = out_dir / filename
            if download_image(url, dest, headers):
                local_paths.append(str(dest.resolve()))
        return local_paths
