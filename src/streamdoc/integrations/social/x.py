"""X (Twitter) social source collector via the public-clis/twitter-cli subprocess.

Install (latest default-branch version):
    uv tool install --upgrade git+https://github.com/public-clis/twitter-cli.git

Or, because ``twitter-cli`` is declared as a project dependency, run ``uv sync``.

The CLI binary is ``twitter`` (not the deprecated npm ``twitter-cli``). It
returns a stable JSON envelope under ``.data`` when invoked with ``--json``.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from streamdoc.config import settings
from streamdoc.integrations.social.auth import get_twitter_cli_env
from streamdoc.integrations.social.base import SocialPost
from streamdoc.integrations.social.downloader import (
    download_image,
    safe_dir_name,
)

logger = logging.getLogger(__name__)

_TWITTER_CLI_BINARY = "twitter"
_X_PLATFORM = "x"

# Reason: twitter-cli's own internal hard ceiling per ``--max`` call is 500.
_X_CLI_HARD_MAX = 500
# Reason: list timelines support cursor pagination; fetch 50 at a time so
# we can stop as soon as the lookback window is exhausted.
_X_LIST_PAGE_SIZE = 50
# Reason: safety cap for the total number of posts collected from a single
# source when no explicit max is configured.
_X_SAFETY_MAX_POSTS = 1000


def _candidate_paths() -> list[Path]:
    """Return additional filesystem locations to probe for the ``twitter`` binary."""
    home = Path.home()
    app_data = os.environ.get("APPDATA")
    candidates: list[Path] = [
        # Current Python environment (covers uv venv installs).
        Path(sys.executable).parent / "twitter",
        # Common user-local install locations.
        home / ".local" / "bin" / "twitter",
        home / "AppData" / "Roaming" / "npm" / "twitter",
    ]
    if app_data:
        candidates.append(Path(app_data) / "npm" / "twitter")
    return candidates


def _find_binary() -> str:
    """Return the path to the public-clis ``twitter`` binary, or '' if missing.

    Resolution order:
        1. ``settings.twitter_cli_binary_path`` override if it points to a file.
        2. ``twitter`` / ``twitter.exe`` on ``$PATH``.
        3. Probed candidate directories from :func:`_candidate_paths`.

    Returns:
        Absolute path to the binary, or empty string.
    """
    override = getattr(settings, "twitter_cli_binary_path", None)
    if override:
        p = Path(override)
        if p.exists() and p.is_file():
            return str(p.resolve())

    binary = shutil.which(_TWITTER_CLI_BINARY)
    if binary:
        return str(Path(binary).resolve())

    for candidate in _candidate_paths():
        for name in (candidate, candidate.with_suffix(".exe"), candidate.with_suffix(".cmd")):
            if name.exists() and name.is_file():
                return str(name.resolve())
    return ""


def _twitter_probe(args: list[str], timeout: int = 15) -> dict[str, Any] | None:
    """Run a read-only ``twitter`` CLI probe and return the parsed JSON envelope.

    Returns None when the binary is missing, the command fails, or the output
    cannot be parsed.  This keeps resolution best-effort but no longer marks
    arbitrary strings as valid.
    """
    binary = _find_binary()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=get_twitter_cli_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("X: twitter-cli probe %s failed: %s", args, exc)
        return None
    if result.returncode != 0:
        return None
    payload: dict[str, Any] | None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("ok") is False:
        return None
    return payload


def _run_twitter(args: list[str], timeout: int = 120) -> dict[str, Any] | list[Any] | None:
    """Run a ``twitter`` CLI command and return its parsed JSON payload.

    Unlike :func:`_twitter_probe`, this helper is meant for the actual data
    fetch and uses a longer timeout.

    Args:
        args: Full argument list starting with the binary path.
        timeout: Subprocess timeout in seconds.

    Returns:
        Parsed JSON payload, or None on failure.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=get_twitter_cli_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("X: twitter-cli command failed: %s", exc)
        return None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.warning("X: twitter-cli exited %d: %s", result.returncode, stderr[:500])
        return None

    payload: dict[str, Any] | list[Any] | None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("X: non-JSON output from twitter-cli")
        payload = None
    return payload


def _extract_next_cursor(payload: Any) -> str | None:
    """Return the next pagination cursor from a twitter-cli timeline payload."""
    if not isinstance(payload, dict):
        return None
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        return pagination.get("nextCursor") or pagination.get("next_cursor")
    return None


def _resolve_x_user(handle: str) -> dict[str, Any]:
    """Resolve an X user handle via the ``twitter user`` CLI command."""
    # Reason: users paste full URLs or handles with leading @; normalize to the
    # screen name and reject anything that does not look like a valid handle.
    part = handle.split("?", 1)[0].split("#", 1)[0]
    normalized = part.split("/")[-1].strip().lstrip("@")
    if not normalized or not re.match(r"^\w{1,15}$", normalized):
        return {
            "resolved_identifier": handle,
            "display_name": f"@{handle}" if handle else "",
            "exists": False,
        }
    payload = _twitter_probe(["user", normalized, "--json"])
    if payload is None:
        return {
            "resolved_identifier": normalized,
            "display_name": f"@{normalized}",
            "exists": False,
        }
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    name = ""
    screen = ""
    if isinstance(data, dict):
        name = data.get("name") or data.get("Name") or ""
        screen = (
            data.get("screenName")
            or data.get("screen_name")
            or data.get("username")
            or data.get("Username")
            or ""
        )
    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        name = first.get("name") or first.get("Name") or ""
        screen = (
            first.get("screenName")
            or first.get("screen_name")
            or first.get("username")
            or first.get("Username")
            or ""
        )
    if name and screen:
        display = f"{name} (@{screen})"
    elif name:
        display = name
    elif screen:
        display = f"@{screen}"
    else:
        display = f"@{normalized}"
    return {
        "resolved_identifier": screen or normalized,
        "display_name": display,
        "exists": True,
    }


def resolve_x_source(identifier: str) -> dict[str, Any]:
    """Normalize and verify an X/Twitter source descriptor.

    Supported prefixes (per ``XSource``):
      * ``user`` / ``@user`` — a user's timeline
      * ``list/<id>`` — a list by its numeric id
      * ``search/<query>`` — a search query
      * ``tweet/<id>`` — a single tweet thread
      * ``likes/<user>`` — a user's own likes

    Args:
        identifier: Raw X source descriptor.

    Returns:
        dict with ``resolved_identifier``, ``display_name``, and ``exists``.
    """
    raw = identifier.strip().lstrip("@")
    if not raw:
        return {"resolved_identifier": identifier, "display_name": identifier, "exists": False}

    if raw.lower().startswith("list/"):
        tail = raw.split("/", 1)[1].strip()
        # Reason: twitter-cli only accepts a numeric list id, and it cannot
        # fetch list metadata.  Resolve by extracting the id from the input
        # (e.g. a pasted list URL) so the form at least stores a real id.
        match = re.search(r"\d+", tail)
        if not match:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        list_id = match.group(0)
        return {
            "resolved_identifier": f"list/{list_id}",
            "display_name": f"X list {list_id}",
            "exists": True,
        }

    if raw.lower().startswith("search/"):
        query = raw.split("/", 1)[1].strip()
        if not query:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        return {
            "resolved_identifier": f"search/{query}",
            "display_name": f"X search: {query}",
            "exists": True,
        }

    if raw.lower().startswith("tweet/"):
        tail = raw.split("/", 1)[1].strip()
        if not tail:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        clean = tail.split("?", 1)[0].split("#", 1)[0]
        match = re.search(r"\d+", clean)
        if not match:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        tweet_id = match.group(0)
        payload = _twitter_probe(["tweet", tweet_id, "--json"])
        display = f"X tweet {tweet_id}"
        if payload is not None and isinstance(payload, dict):
            data = payload.get("data", {})
            tweet = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else {})
            if isinstance(tweet, dict):
                author = (tweet.get("author") or {}).get("screenName") or ""
                text = tweet.get("text") or ""
                if author:
                    display = f"@{author}: {text[:50]}"
                    if len(text) > 50:
                        display += "..."
        return {
            "resolved_identifier": f"tweet/{tweet_id}",
            "display_name": display,
            "exists": payload is not None,
        }

    if raw.lower().startswith("user/"):
        handle = raw.split("/", 1)[1].strip()
        if not handle:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        return _resolve_x_user(handle)

    if raw.lower().startswith("likes/"):
        handle = raw.split("/", 1)[1].strip()
        if not handle:
            return {"resolved_identifier": raw, "display_name": raw, "exists": False}
        result = _resolve_x_user(handle)
        return {
            "resolved_identifier": f"likes/{result['resolved_identifier']}",
            "display_name": f"likes by {result['display_name']}",
            "exists": result["exists"],
        }

    return _resolve_x_user(raw)


def get_twitter_binary() -> str:
    """Public accessor for the configured twitter binary path."""
    return _find_binary()


def get_twitter_version(binary: str) -> str | None:
    """Return the installed twitter-cli version string, or None if unknown."""
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
            env=get_twitter_cli_env(),
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def is_twitter_authenticated(binary: str) -> bool:
    """Check whether twitter-cli has usable X credentials.

    Args:
        binary: Path to the ``twitter`` executable.

    Returns:
        True if ``twitter status`` reports authenticated.
    """
    for args in ([binary, "status", "--json"], [binary, "whoami", "--json"]):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                stdin=subprocess.DEVNULL,
                env=get_twitter_cli_env(),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

        if result.returncode != 0:
            continue

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue

        data = payload.get("data", {}) if isinstance(payload, dict) and payload.get("ok") is not False else {}
        if data and isinstance(data, dict) and (
            data.get("authenticated") is True or data.get("id") or data.get("username")
        ):
            # ``status`` returns an empty dict for unauthenticated; ``whoami``
            # returns a user dict when authenticated.
            return True
    return False


class XSourceNotInstalledError(RuntimeError):
    """Raised when the public-clis/twitter-cli ``twitter`` binary is not available."""


def _extract_tweet_list(data: Any) -> list[dict[str, Any]]:
    """Normalize twitter-cli JSON output into a list of tweet dicts.

    Handles the envelope used by public-clis/twitter-cli:
      - ``{"ok": true, "data": [...]}``
      - a plain list of tweet dicts
      - ``{"data": [...]}`` / ``{"data": {"tweets": [...]}}``

    Args:
        data: Parsed JSON from twitter-cli.

    Returns:
        A list of tweet dicts (empty when the envelope is unrecognized or errored).
    """
    if isinstance(data, dict):
        if data.get("ok") is False:
            error = data.get("error", {})
            logger.warning("twitter-cli returned an error: %s", error)
            return []

        tweets = data.get("tweets")
        if isinstance(tweets, list):
            return [t for t in tweets if isinstance(t, dict)]

        payload = data.get("data", [])
        if isinstance(payload, list):
            return [t for t in payload if isinstance(t, dict)]
        if isinstance(payload, dict):
            tweets = payload.get("tweets", [])
            if isinstance(tweets, list):
                return [t for t in tweets if isinstance(t, dict)]
        return []

    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]

    return []


_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def _looks_like_image_url(url: str) -> bool:
    """Return True when ``url`` has a known image file extension."""
    ext = Path(url.split("?", 1)[0]).suffix.lower()
    return ext in _IMAGE_SUFFIXES


def _extract_tweet_images(tweet: dict[str, Any]) -> list[str]:
    """Return deduplicated image URLs from a twitter-cli tweet dict.

    Args:
        tweet: Tweet dictionary from twitter-cli JSON output.

    Returns:
        List of HTTP(S) image URLs.
    """
    images: list[str] = []
    seen: set[str] = set()

    media = tweet.get("media")
    if isinstance(media, list):
        for item in media:
            if not isinstance(item, dict):
                continue
            # Reason: the twitter-cli "url" for a video is an MP4. Only treat
            # photo media as downloadable images.
            if item.get("type") == "video":
                continue
            url = item.get("url")
            if isinstance(url, str) and url and url not in seen and _looks_like_image_url(url):
                images.append(url)
                seen.add(url)

    # Reason: keep parsing the legacy Twitter API v1.1 fields as a fallback
    # in case a downstream caller supplies older JSON. media_url_https is the
    # thumbnail for videos and the full image for photos, so we only keep it
    # when the extension looks like an image.
    entities = tweet.get("entities")
    if isinstance(entities, dict):
        for item in entities.get("media") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("media_url_https") or item.get("media_url") or ""
            if isinstance(url, str) and url and url not in seen and _looks_like_image_url(url):
                images.append(url)
                seen.add(url)

    extended_entities = tweet.get("extended_entities")
    if isinstance(extended_entities, dict):
        for item in extended_entities.get("media") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("media_url_https") or item.get("media_url") or ""
            if isinstance(url, str) and url and url not in seen and _looks_like_image_url(url):
                images.append(url)
                seen.add(url)

    return images


def _parse_tweet(
    tweet: dict[str, Any],
    cutoff: datetime,
    dedup_store: Any,
    preset_name: str,
    skip_processed: bool = True,
) -> SocialPost | None:
    """Parse a single twitter-cli tweet dict into a SocialPost.

    Args:
        tweet: Tweet dictionary.
        cutoff: Tweets older than this UTC datetime are ignored.
        dedup_store: Object with ``is_processed(platform, source_id, preset_name)``.
        preset_name: Preset display name used as the dedup scope.
        skip_processed: When False, do not skip already-processed tweets.

    Returns:
        Normalized SocialPost or None if outside the cutoff/already processed.
    """
    tweet_id = str(tweet.get("id") or "")
    if not tweet_id:
        return None

    # twitter-cli exposes both ISO and original Twitter timestamp fields.
    created_at = tweet.get("createdAtISO") or tweet.get("createdAt") or tweet.get("created_at") or ""
    if not created_at:
        logger.warning("X: missing created_at for tweet %s, skipping", tweet_id)
        return None

    published: datetime | None = None
    if "T" in created_at and created_at.endswith(("Z", "+00:00")):
        try:
            published = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            pass

    if published is None:
        try:
            # Old Twitter API v1.1 format: "Wed Jul 23 14:30:00 +0000 2026"
            published = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        except (ValueError, TypeError):
            logger.warning("X: could not parse date %r, skipping", created_at)
            return None

    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)

    if published < cutoff:
        return None

    if skip_processed and dedup_store.is_processed(_X_PLATFORM, tweet_id, preset_name):
        return None

    author_data = tweet.get("author") or {}
    author = (
        author_data.get("screenName")
        or author_data.get("username")
        or author_data.get("name")
        or "unknown"
    )

    text = tweet.get("text") or tweet.get("full_text") or ""

    # Include quoted-tweet text inline so the report is self-contained.
    quoted = tweet.get("quotedTweet")
    if isinstance(quoted, dict):
        qtext = quoted.get("text") or ""
        qauthor = (quoted.get("author") or {}).get("screenName") or ""
        if qtext:
            text = f"{text}\n\n[quoted @{qauthor}]: {qtext}".strip()

    permalink = f"https://x.com/{author}/status/{tweet_id}"
    images = _extract_tweet_images(tweet)

    return SocialPost(
        platform=_X_PLATFORM,
        source_id=tweet_id,
        url=permalink,
        author=author,
        text=text,
        published_at=published,
        raw=json.dumps(tweet, ensure_ascii=False),
        images=images,
    )


def _tweet_published_at(tweet: dict[str, Any]) -> datetime | None:
    """Return the UTC publish date for a raw tweet, or None if unparseable."""
    created_at = tweet.get("createdAtISO") or tweet.get("createdAt") or tweet.get("created_at") or ""
    if not created_at:
        return None

    published: datetime | None = None
    if "T" in created_at and created_at.endswith(("Z", "+00:00")):
        try:
            published = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            pass

    if published is None:
        try:
            published = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        except (ValueError, TypeError):
            return None

    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return published


def _download_images(images: list[str], post_id: str) -> list[str]:
    """Download images to media_root/social/x/<post_id>/ and return local paths.

    Args:
        images: Public image URLs.
        post_id: Tweet ID used as the storage sub-directory.

    Returns:
        Absolute local paths for successfully downloaded images.
    """
    if not images:
        return []

    media_dir = Path(settings.media_root) / "social" / "x" / safe_dir_name(post_id)
    media_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    downloaded: list[str] = []
    for i, url in enumerate(images):
        if not isinstance(url, str) or not url.strip():
            continue
        ext = Path(url.split("?", 1)[0]).suffix or ".jpg"
        if ext.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        dest = media_dir / f"image_{i:02d}{ext}"
        if download_image(url, dest, headers):
            downloaded.append(str(dest.resolve()))
    return downloaded


class XSource:
    """Collect tweets from X (Twitter) via the public-clis ``twitter`` CLI."""

    BINARY_HINT = (
        "Install public-clis/twitter-cli (latest version):\n"
        "  uv tool install --upgrade git+https://github.com/public-clis/twitter-cli.git\n"
        "Or ensure the 'twitter' binary is on PATH."
    )

    def collect(
        self,
        preset: Any,
        source_descriptor: str,
        cutoff: datetime,
        dedup_store: Any,
        max_posts: int | None = None,
        skip_processed: bool = True,
    ) -> list[SocialPost]:
        """Collect tweets from an X source.

        Supported source descriptors:
            - ``username`` or ``user/<username>`` -- user's posts
            - ``list/<list_id>`` -- list timeline
            - ``search/<query>`` -- search
            - ``tweet/<id>`` -- single tweet and replies
            - ``likes/<username>`` -- user's likes (own account only)

        Args:
            preset: Preset configuration (provides ``name`` for dedup scoping).
            source_descriptor: X source type + identifier.
            cutoff: Tweets older than this UTC datetime are ignored.
            dedup_store: Object with ``is_processed(platform, source_id, preset_name)``.
            max_posts: Target cap on returned tweets (newest first).
            skip_processed: When False, do not skip already-processed tweets.

        Returns:
            List of normalized SocialPost objects.
        """
        binary = _find_binary()
        if not binary:
            raise XSourceNotInstalledError(self.BINARY_HINT)

        descriptor = source_descriptor.strip()
        parts = descriptor.split("/", 1)
        prefix = parts[0].lower()
        value = parts[1] if len(parts) > 1 else ""

        # Reason: ``max_posts`` is a target, not a page size. If the operator
        # leaves it unset, use a high safety ceiling so we capture everything
        # in the lookback window without letting a single source run forever.
        target = (
            min(max_posts, _X_SAFETY_MAX_POSTS)
            if max_posts is not None and max_posts > 0
            else _X_SAFETY_MAX_POSTS
        )

        if prefix == "list" and value:
            posts = self._collect_list(
                binary, value, cutoff, dedup_store, preset.name, target, skip_processed
            )
        elif prefix == "tweet" and value:
            posts = self._collect_tweet(
                binary, value, cutoff, dedup_store, preset.name, skip_processed
            )
        else:
            posts = self._collect_single_call(
                binary, descriptor, prefix, value, cutoff, dedup_store,
                preset.name, target, skip_processed,
            )

        if posts:
            self._download_images_for_posts(posts)

        logger.info("X: collected %d posts from %s", len(posts), descriptor)
        return posts

    def _collect_list(
        self,
        binary: str,
        list_id: str,
        cutoff: datetime,
        dedup_store: Any,
        preset_name: str,
        target: int,
        skip_processed: bool,
    ) -> list[SocialPost]:
        """Paginate through a Twitter List until the time window is exhausted."""
        posts: list[SocialPost] = []
        cursor: str | None = None
        page_size = min(_X_LIST_PAGE_SIZE, target)
        max_pages = max(1, (target // page_size) + 5)

        for page in range(max_pages):
            if target and len(posts) >= target:
                break

            args = self._build_args(
                binary,
                command="list",
                value=list_id,
                max_count=page_size,
                cursor=cursor,
            )
            logger.info(
                "X: fetching list %s page %d (cursor=%s)", list_id, page + 1, cursor
            )
            payload = _run_twitter(args)
            if payload is None:
                break

            raw_tweets = _extract_tweet_list(payload)
            if not raw_tweets:
                logger.info("X: list %s returned no tweets on page %d", list_id, page + 1)
                break

            page_oldest = _tweet_published_at(raw_tweets[-1])
            for tweet in raw_tweets:
                if not isinstance(tweet, dict):
                    logger.warning("X: skipping non-dict tweet entry in list %s", list_id)
                    continue
                post = _parse_tweet(
                    tweet, cutoff, dedup_store, preset_name, skip_processed
                )
                if post is not None:
                    posts.append(post)
                    if target and len(posts) >= target:
                        break

            # Reason: the list is newest-first. Once the oldest tweet on a page
            # is older than the lookback window, every subsequent page is older.
            if page_oldest is not None and page_oldest < cutoff:
                logger.info("X: list %s reached cutoff on page %d", list_id, page + 1)
                break

            cursor = _extract_next_cursor(payload)
            if not cursor:
                logger.info("X: list %s has no further cursor", list_id)
                break

        return posts

    def _collect_single_call(
        self,
        binary: str,
        descriptor: str,
        prefix: str,
        value: str,
        cutoff: datetime,
        dedup_store: Any,
        preset_name: str,
        target: int,
        skip_processed: bool,
    ) -> list[SocialPost]:
        """Collect from a user timeline, search, or likes (no cursor support)."""
        command, query = self._resolve_command(prefix, value, descriptor)
        if command is None:
            logger.warning("X: unsupported descriptor %r", descriptor)
            return []

        fetch_count = min(target, _X_CLI_HARD_MAX)
        since = None
        until = datetime.now(UTC).strftime("%Y-%m-%d")
        if command == "search" and cutoff:
            # Reason: X search only supports whole-date filtering. Use the
            # lookback date so we do not discard the most recent day.
            since = cutoff.strftime("%Y-%m-%d")

        args = self._build_args(
            binary,
            command=command,
            value=query,
            max_count=fetch_count,
            since=since,
            until=until,
        )
        logger.info("X: invoking %s for descriptor=%s count=%d", command, descriptor, fetch_count)

        payload = _run_twitter(args)
        if payload is None:
            return []

        raw_tweets = _extract_tweet_list(payload)
        posts: list[SocialPost] = []
        for tweet in raw_tweets:
            if not isinstance(tweet, dict):
                continue
            post = _parse_tweet(tweet, cutoff, dedup_store, preset_name, skip_processed)
            if post is not None:
                posts.append(post)
                if target and len(posts) >= target:
                    break

        return posts

    def _collect_tweet(
        self,
        binary: str,
        tweet_id: str,
        cutoff: datetime,
        dedup_store: Any,
        preset_name: str,
        skip_processed: bool,
    ) -> list[SocialPost]:
        """Collect a single tweet thread and its replies."""
        args = self._build_args(binary, command="tweet", value=tweet_id)
        payload = _run_twitter(args)
        if payload is None:
            return []

        raw_tweets = _extract_tweet_list(payload)
        posts: list[SocialPost] = []
        for tweet in raw_tweets:
            if not isinstance(tweet, dict):
                continue
            post = _parse_tweet(tweet, cutoff, dedup_store, preset_name, skip_processed)
            if post is not None:
                posts.append(post)
                break
        return posts

    def _resolve_command(
        self, prefix: str, value: str, descriptor: str
    ) -> tuple[str | None, str]:
        """Map a descriptor to a twitter-cli command and its value."""
        if prefix == "search" and value:
            return "search", value
        if prefix == "likes" and value:
            return "likes", value
        if prefix == "user" and value:
            return "user-posts", value
        # Bare username or unknown prefix — treat as a user timeline.
        if prefix not in ("list", "search", "tweet", "likes", "user"):
            return "user-posts", descriptor
        return None, ""

    def _download_images_for_posts(self, posts: list[SocialPost]) -> None:
        """Download images for all posts in parallel."""
        if not posts:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_post = {
                executor.submit(_download_images, post.images, post.source_id): post
                for post in posts
                if post.images
            }
            for future in concurrent.futures.as_completed(future_to_post):
                post = future_to_post[future]
                try:
                    post.images = future.result()
                except (OSError, RuntimeError, ValueError, TypeError) as exc:
                    logger.warning("X: image download failed for %s: %s", post.source_id, exc)

    def _build_args(
        self,
        binary: str,
        command: str,
        value: str,
        max_count: int | None = None,
        cursor: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[str]:
        """Build public-clis/twitter-cli arguments for a command.

        Args:
            binary: Path to the ``twitter`` binary.
            command: twitter-cli subcommand (``list``, ``user-posts``, etc.).
            value: Subcommand argument (list id, username, query, tweet id).
            max_count: Optional ``--max`` total for this call.
            cursor: Optional ``--cursor`` for list pagination.
            since: Optional ``--since YYYY-MM-DD`` for search.
            until: Optional ``--until YYYY-MM-DD`` for search.

        Returns:
            Argument list for ``subprocess.run``.
        """
        base: list[str] = [binary, command, value, "--json"]

        if command == "search":
            # Reason: for time-window collection we want chronological results,
            # not the algorithmic "Top" tab.
            base.append("--type")
            base.append("latest")

        if max_count:
            base.extend(["--max", str(max_count)])

        if cursor:
            base.extend(["--cursor", cursor])

        if since:
            base.extend(["--since", since])
        if until:
            base.extend(["--until", until])

        return base
