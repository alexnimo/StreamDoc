"""
YouTube Data API v3 helpers.

Provides a fallback for metadata that yt-dlp cannot reliably obtain when
YouTube rate-limits or bot-blocks the extractor.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from yt_dlp.utils import parse_duration

logger = logging.getLogger(__name__)


def fetch_upload_dates(video_ids: list[str], api_key: str) -> dict[str, str]:
    """Fetch ``publishedAt`` for a list of video IDs via YouTube Data API v3.

    Convenience wrapper around ``fetch_video_metadata`` that returns only
    the upload date. Kept for backwards compatibility.

    Args:
        video_ids: List of YouTube video IDs.
        api_key: YouTube Data API v3 key.

    Returns:
        Dict mapping video ID -> ISO 8601 ``publishedAt`` string.
    """
    metadata = fetch_video_metadata(video_ids, api_key)
    return {vid_id: meta["published_at"] for vid_id, meta in metadata.items()}


def fetch_video_metadata(video_ids: list[str], api_key: str) -> dict[str, dict[str, Any]]:
    """Fetch ``publishedAt`` and ``duration`` for a list of video IDs.

    Batches requests up to 50 IDs per call. ``contentDetails.duration`` is
    an ISO 8601 duration string (e.g. ``PT60S``); we parse it to seconds.

    Args:
        video_ids: List of YouTube video IDs.
        api_key: YouTube Data API v3 key.

    Returns:
        Dict mapping video ID -> dict with ``published_at`` (str),
        ``duration_seconds`` (int | None), and ``title`` (str | None).
    """
    metadata: dict[str, dict[str, Any]] = {}
    if not api_key or not video_ids:
        return metadata

    base_url = "https://www.googleapis.com/youtube/v3/videos"
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        params = {
            "part": "snippet,contentDetails",
            "id": ",".join(batch),
            "key": api_key,
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "StreamDoc"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            for item in data.get("items", []):
                vid_id = item.get("id")
                snippet = item.get("snippet", {}) or {}
                content_details = item.get("contentDetails", {}) or {}
                duration_text = content_details.get("duration")
                if not vid_id:
                    continue
                duration_seconds = None
                if duration_text:
                    try:
                        duration_seconds = int(parse_duration(duration_text))
                    except Exception as exc:
                        logger.debug("Failed to parse duration %r: %s", duration_text, exc)
                metadata[vid_id] = {
                    "published_at": snippet.get("publishedAt"),
                    "duration_seconds": duration_seconds,
                    "title": snippet.get("title"),
                }
        except Exception as exc:
            logger.warning("YouTube Data API video metadata batch failed: %s", exc)
            # Reason: return partial results and let the caller fall back to
            # yt-dlp for the remaining IDs.
            break

    return metadata
