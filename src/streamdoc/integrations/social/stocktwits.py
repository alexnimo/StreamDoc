"""Stocktwits public API social source collector."""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request

from streamdoc.config import settings
from streamdoc.integrations.social.base import SocialPost
from streamdoc.integrations.social.downloader import (
    download_image,
    safe_dir_name,
)

logger = logging.getLogger(__name__)

_STOCKTWITS_BASE = settings.stocktwits_api_base


# Reason: Stocktwits messages do not expose native image fields; image links
# appear as URLs inside the message body. This pattern catches common image hosts.
_IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"<>]+\.(?:jpg|jpeg|png|gif|webp)",
    re.IGNORECASE,
)


def _fetch_stocktwits_json(url: str, timeout: float = 30) -> dict[str, Any]:
    """Fetch JSON from a Stocktwits public endpoint.

    Try a lightweight browser-like ``urllib`` request first, and fall back
    to ``curl_cffi`` TLS/browser impersonation if Stocktwits returns a
    Cloudflare challenge (403/5xx). This keeps unit tests (which patch
    ``urllib.request.urlopen``) fast while still bypassing anti-bot blocks
    in production.

    Args:
        url: Full URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON dict.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    request = Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Cloudflare / bot-protection block. Try curl_cffi before giving up.
        logger.debug(
            "Stocktwits urllib got HTTP %s for %s; trying curl_cffi", exc.code, url
        )
        try:
            from curl_cffi import requests as curl_requests

            impersonate = getattr(settings, "curl_cffi_impersonate", "chrome133a")
            curl_response = curl_requests.get(
                url,
                headers=headers,
                impersonate=impersonate,
                timeout=timeout,
            )
            curl_response.raise_for_status()
            return curl_response.json()
        except Exception as curl_exc:
            logger.warning("Stocktwits curl_cffi fallback failed for %s: %s", url, curl_exc)
            raise


def _user_exists(user: str) -> bool:
    """Probe the Stocktwits user stream endpoint to verify a username exists.

    Args:
        user: Stocktwits username (without ``@``).

    Returns:
        True if the user stream endpoint returns a 200 with a valid body,
        False if it returns 404 or the request fails.
    """
    url = f"{_STOCKTWITS_BASE.rstrip('/')}/streams/user/{quote(user)}.json?limit=1"
    try:
        data = _fetch_stocktwits_json(url, timeout=5)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        logger.debug("stocktwits user probe HTTP %s for %r", exc.code, user)
        return False
    except Exception as exc:
        logger.debug("stocktwits user probe failed for %r: %s", user, exc)
        return False

    if not isinstance(data, dict):
        return False
    # A valid user stream contains a list of messages (possibly empty).
    return "messages" in data or "user" in data


def resolve_stocktwits_source(identifier: str) -> dict[str, Any]:
    """Resolve a Stocktwits source identifier to its canonical form.

    For symbols, probes the Stocktwits symbol endpoint. For users, verifies
    the username via the user stream endpoint. Trending is accepted as-is.
    Failures are non-fatal and return the user-supplied value.

    Args:
        identifier: Raw Stocktwits descriptor (symbol, ``$SYMBOL``, ``@user``,
            or ``trending``).

    Returns:
        dict with ``resolved_identifier``, ``display_name``, and ``exists``.
    """
    raw = identifier.strip()
    if raw.lower() == "trending":
        return {
            "resolved_identifier": "trending",
            "display_name": "Trending symbols",
            "exists": True,
        }
    if raw.startswith("@"):
        user = raw[1:].strip()
        return {
            "resolved_identifier": f"@{user}",
            "display_name": f"User @{user}",
            "exists": _user_exists(user) if user else False,
        }

    symbol = raw.lstrip("$").strip().upper()
    if not symbol:
        return {"resolved_identifier": raw, "display_name": raw, "exists": False}

    url = f"{_STOCKTWITS_BASE.rstrip('/')}/symbols/{symbol}.json"
    try:
        data = _fetch_stocktwits_json(url, timeout=5)
    except Exception as exc:
        logger.debug("stocktwits symbol resolve failed for %r: %s", symbol, exc)
        return {
            "resolved_identifier": symbol,
            "display_name": symbol,
            "exists": False,
        }

    sym = (data.get("symbol") or {}) if isinstance(data, dict) else {}
    display = sym.get("title") or sym.get("symbol") or symbol
    return {
        "resolved_identifier": sym.get("symbol") or symbol,
        "display_name": display,
        "exists": bool(sym.get("symbol") or sym.get("id")),
    }


class StocktwitsSource:
    """Collect posts from Stocktwits public API endpoints."""

    def collect(
        self,
        preset: Any,
        source_descriptor: str,
        cutoff: datetime,
        dedup_store: Any,
        max_posts: int | None = None,
        skip_processed: bool = True,
    ) -> list[SocialPost]:
        """Collect Stocktwits posts for a preset.

        Supported source descriptors:
            - A single symbol, e.g. ``AAPL``.
            - Comma-separated symbols, e.g. ``AAPL,TSLA,NVDA``.
            - ``trending`` to fetch trending symbols and their recent posts.
            - A username prefixed with ``@``, e.g. ``@trader123``.

        Args:
            preset: Preset configuration (provides ``name`` for dedup scoping).
            source_descriptor: Platform-specific source identifier.
            cutoff: Posts older than this UTC datetime are ignored.
            dedup_store: Object with ``is_processed(platform, source_id, preset_name)``.
            max_posts: Cap on returned posts (newest first).
            skip_processed: When False, do not skip already-processed posts.

        Returns:
            List of normalized SocialPost objects.
        """
        symbols = self._resolve_symbols(source_descriptor.strip())
        if not symbols:
            logger.warning("No Stocktwits symbols/users resolved for %r", source_descriptor)
            return []

        posts_by_id: dict[str, SocialPost] = {}
        for identifier, endpoint_type in symbols:
            messages = self._fetch_messages((identifier, endpoint_type))
            for message in messages:
                social_post = self._to_social_post(
                    message, cutoff, dedup_store, preset.name, identifier, skip_processed
                )
                if social_post is not None and social_post.source_id not in posts_by_id:
                    posts_by_id[social_post.source_id] = social_post

            # Reason: be respectful to the free public API when iterating symbols.
            time.sleep(0.25)

        sorted_posts = sorted(
            posts_by_id.values(), key=lambda p: p.published_at, reverse=True
        )
        if max_posts is not None and max_posts >= 0:
            sorted_posts = sorted_posts[:max_posts]
        return sorted_posts

    def _resolve_symbols(self, descriptor: str) -> list[tuple[str, str]]:
        """Resolve a source descriptor into a list of (label, type) pairs.

        The returned type is either ``"symbol"`` or ``"user"`` and determines
        which stream endpoint is used.

        Args:
            descriptor: Raw source descriptor string.

        Returns:
            List of (identifier, endpoint_type) tuples.
        """
        if descriptor.lower() == "trending":
            return [(s, "symbol") for s in self._fetch_trending_symbols()]
        if descriptor.startswith("@"):
            return [(descriptor[1:], "user")]
        # Reason: strip "$" from tickers like "$AAPL" so the Stocktwits
        # symbol stream endpoint receives the canonical symbol only.
        return [
            (s.strip().lstrip("$").upper(), "symbol")
            for s in descriptor.split(",")
            if s.strip().lstrip("$")
        ]

    def _fetch_trending_symbols(self) -> list[str]:
        """Fetch currently trending symbols from Stocktwits.

        Returns:
            List of symbol tickers.
        """
        url = f"{_STOCKTWITS_BASE.rstrip('/')}/trending/symbols.json"
        try:
            data = self._fetch_json(url)
        except Exception as exc:
            logger.warning("Stocktwits trending fetch failed: %s", exc)
            return []
        return [s.get("symbol", "") for s in data.get("symbols", []) if s.get("symbol")]

    def _fetch_messages(self, label: tuple[str, str]) -> list[dict[str, Any]]:
        """Fetch messages for a symbol or user.

        Args:
            label: Tuple of (identifier, endpoint_type).

        Returns:
            List of raw message dicts from the API.
        """
        identifier, endpoint_type = label
        encoded = quote(identifier)
        if endpoint_type == "user":
            url = f"{_STOCKTWITS_BASE.rstrip('/')}/streams/user/{encoded}.json?limit=30"
        else:
            url = f"{_STOCKTWITS_BASE.rstrip('/')}/streams/symbol/{encoded}.json?limit=30"
        try:
            data = self._fetch_json(url)
        except Exception as exc:
            logger.warning("Stocktwits fetch failed for %s: %s", identifier, exc)
            return []
        return data.get("messages", []) or []

    def _fetch_json(self, url: str) -> dict[str, Any]:
        """Fetch JSON from a Stocktwits public endpoint (instance wrapper)."""
        return _fetch_stocktwits_json(url)

    def _download_images(self, folder_label: str, urls: list[str]) -> list[str]:
        """Download image URLs into the media root and return local paths.

        Args:
            folder_label: Symbol or username used as the storage sub-directory.
            urls: Image URLs to download.

        Returns:
            Absolute local paths for successfully downloaded images.
        """
        if not urls:
            return []

        out_dir = (
            Path(settings.media_root) / "social" / "stocktwits" / safe_dir_name(folder_label)
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }

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

    def _to_social_post(
        self,
        message: dict[str, Any],
        cutoff: datetime,
        dedup_store: Any,
        preset_name: str,
        folder_label: str,
        skip_processed: bool = True,
    ) -> SocialPost | None:
        """Convert a Stocktwits message dict into a normalized SocialPost.

        Args:
            message: Raw message JSON from Stocktwits.
            cutoff: Posts older than this UTC datetime are ignored.
            dedup_store: Deduplication store for the is_processed check.
            preset_name: Preset display name used as the dedup scope.
            folder_label: Symbol or username used as the media sub-directory.
            skip_processed: When False, do not skip already-processed posts.

        Returns:
            Normalized SocialPost or None if it should be skipped.
        """
        raw_id = message.get("id")
        source_id = str(raw_id) if raw_id is not None else ""
        created_at = message.get("created_at")
        if not source_id or not created_at:
            return None

        published_at = self._parse_created_at(created_at)
        if published_at is None:
            return None
        if published_at < cutoff:
            logger.info(
                "Skipping stocktwits post=%s (published %s, before cutoff)",
                source_id,
                published_at.isoformat(),
            )
            return None

        if skip_processed and dedup_store.is_processed("stocktwits", source_id, preset_name):
            logger.info("Skipping already-processed stocktwits post=%s", source_id)
            return None

        body = (message.get("body") or "").strip()
        user = message.get("user") or {}
        author = user.get("username") or ""

        sentiment = self._extract_sentiment(message)
        text = f"[{sentiment}] {body}" if body else f"[{sentiment}]"

        url = f"https://stocktwits.com/message/{source_id}"

        image_urls = self._extract_image_urls(message)
        local_images = self._download_images(folder_label, image_urls)

        raw = json.dumps(message, ensure_ascii=False)

        return SocialPost(
            platform="stocktwits",
            source_id=source_id,
            url=url,
            author=author,
            text=text,
            published_at=published_at,
            raw=raw,
            images=local_images,
        )

    def _parse_created_at(self, value: str) -> datetime | None:
        """Parse a Stocktwits ISO-8601 timestamp to a UTC datetime.

        Args:
            value: Timestamp string from the API.

        Returns:
            UTC datetime or None if parsing fails.
        """
        try:
            v = value
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
        except Exception:
            return None

    def _extract_sentiment(self, message: dict[str, Any]) -> str:
        """Map Stocktwits sentiment values to a normalized label.

        Args:
            message: Raw message JSON.

        Returns:
            ``bullish``, ``bearish``, or ``neutral``.
        """
        entities = message.get("entities") or {}
        sentiment = (entities.get("sentiment") or {}).get("basic")
        if sentiment == "Bullish":
            return "bullish"
        if sentiment == "Bearish":
            return "bearish"
        return "neutral"

    def _extract_image_urls(self, message: dict[str, Any]) -> list[str]:
        """Return deduplicated candidate image URLs from a Stocktwits message.

        Args:
            message: Raw message JSON.

        Returns:
            List of HTTP(S) image URLs (body links + avatar).
        """
        urls: list[str] = []
        seen: set[str] = set()

        body = message.get("body") or ""
        for match in _IMAGE_URL_RE.finditer(body):
            url = match.group(0)
            if url not in seen:
                urls.append(url)
                seen.add(url)

        user = message.get("user") or {}
        avatar = user.get("avatar_url_ssl") or ""
        if avatar and avatar.startswith("http") and avatar not in seen:
            urls.append(avatar)

        return urls
