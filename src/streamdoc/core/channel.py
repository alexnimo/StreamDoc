"""
Channel and video resolution via yt-dlp with HTML-scrape fallback.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Channel:
    id: str
    title: str
    source: str = "youtube"


@dataclass
class Video:
    id: str
    channel_id: str
    title: str
    published_at: str
    duration_seconds: int | None = None
    webpage_url: str | None = None


def _resolve_channel_via_html(url: str) -> tuple[str, str] | None:
    """Fallback: scrape channel ID and title from YouTube HTML."""
    import urllib.request

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            cid_match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
            if not cid_match:
                return None
            cid = cid_match.group(1)
            # Reason: prefer "author" or "ownerChannelName" from the embedded
            # JSON metadata — these contain the actual channel name for both
            # channel pages and video pages. The <title> tag is only correct
            # for channel pages; on video pages it contains the video title.
            author_match = (
                re.search(r'"author":"(.*?)"', html)
                or re.search(r'"ownerChannelName":"(.*?)"', html)
            )
            if author_match:
                title = author_match.group(1).strip()
            else:
                title_match = re.search(r"<title>(.*?)</title>", html)
                title = title_match.group(1).replace(" - YouTube", "").strip() if title_match else cid
            return cid, title
    except Exception as exc:
        logger.debug("HTML scrape failed for %s: %s", url, exc)
        return None


def _ensure_youtube_url(identifier: str) -> str:
    """Convert a bare channel ID or handle to a full YouTube URL.

    Args:
        identifier: URL, handle (@name), or channel ID (UC...).

    Returns:
        A full YouTube URL suitable for yt-dlp.
    """
    if identifier.startswith(("http://", "https://")):
        return identifier
    # Reason: bare channel ID like UCMno7bbQKigk6RxiO0uv78g — construct a URL
    if identifier.startswith("UC") and len(identifier) == 24:
        return f"https://www.youtube.com/channel/{identifier}"
    # Reason: handle like @TradersHelpingTraders
    if identifier.startswith("@"):
        return f"https://www.youtube.com/{identifier}"
    # Reason: assume it's a handle without @ prefix
    return f"https://www.youtube.com/@{identifier}"


def resolve_channel(url: str) -> Channel:
    """Resolve a YouTube URL, handle, or channel ID to a Channel object.

    Accepts:
      - Full URLs: https://www.youtube.com/@handle
      - Bare channel IDs: UCMno7bbQKigk6RxiO0uv78g
      - Handles: @TradersHelpingTraders
      - Channel names: TradersHelpingTraders

    Tries yt-dlp first (using --dump-single-json --flat-playlist for
    channel-level metadata without extracting every video), then falls
    back to HTML scraping. For handles, tries multiple URL formats
    to maximize compatibility.
    """
    yt_url = _ensure_youtube_url(url)

    # Build list of alternate URLs to try for handles
    urls_to_try = [yt_url]
    if not url.startswith(("http://", "https://")) and not (url.startswith("UC") and len(url) == 24):
        # Reason: yt-dlp sometimes fails with /@handle URLs; try /c/ and /user/ as fallbacks
        handle = url.lstrip("@")
        alt1 = f"https://www.youtube.com/c/{handle}"
        alt2 = f"https://www.youtube.com/user/{handle}"
        for alt in (alt1, alt2):
            if alt not in urls_to_try:
                urls_to_try.append(alt)

    last_exc: Exception | None = None
    for try_url in urls_to_try:
        try:
            return _resolve_channel_with_yt_dlp(try_url)
        except Exception as exc:
            last_exc = exc
            logger.debug("yt-dlp failed to resolve %s: %s", try_url, exc)

    # Reason: all yt-dlp attempts failed; try HTML scraping on each URL
    for try_url in urls_to_try:
        res = _resolve_channel_via_html(try_url)
        if res:
            return Channel(id=res[0], title=res[1])

    raise RuntimeError(f"Could not resolve channel ID for {url} via yt-dlp or HTML scraping.")


def _resolve_channel_with_yt_dlp(url: str) -> Channel:
    """Use yt-dlp --dump-single-json --flat-playlist to resolve channel metadata.

    Reason: --dump-single-json returns the playlist/channel-level JSON
    (with uploader_id, channel_id) instead of per-entry lines.
    --flat-playlist avoids extracting individual videos (prevents rate-limiting).
    """
    from streamdoc.core.downloader import dump_json

    data = dump_json(url, flat_playlist=True, dump_single_json=True, playlist_end=1)
    # Reason: channel_id is the canonical UC... identifier; uploader_id may be a @handle
    cid = data.get("channel_id") or data.get("uploader_id") or data.get("id")
    if not cid:
        raise RuntimeError(f"Could not find channel ID in yt-dlp response for {url}")
    return Channel(
        id=cid,
        title=data.get("uploader") or data.get("channel") or data.get("title") or cid,
    )


def resolve_video(url: str) -> Video:
    """Resolve a single video URL to a Video dataclass."""
    from streamdoc.core.downloader import dump_json

    data = dump_json(url)
    channel = resolve_channel(url)
    return Video(
        id=data.get("id") or url,
        channel_id=channel.id,
        title=data.get("title") or url,
        published_at=data.get("upload_date") or "",
        duration_seconds=data.get("duration"),
        webpage_url=data.get("webpage_url") or url,
    )
