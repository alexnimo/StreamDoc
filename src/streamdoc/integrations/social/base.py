"""Base types and protocol for social source collectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from streamdoc.models.preset import Preset


@dataclass
class SocialPost:
    """A normalized social media post collected from any platform.

    Attributes:
        platform: Platform identifier (e.g. "reddit", "stocktwits", "x").
        source_id: Unique post ID from the source platform.
        url: Canonical URL for the post.
        author: Post author username/handle.
        text: Normalized text content (title + body).
        published_at: UTC datetime the post was published.
        raw: Original post JSON as a string for reprocessing/debug.
        id: Optional local database primary key.
        images: Local file paths to downloaded images.
    """

    platform: str
    source_id: str
    url: str
    author: str
    text: str
    published_at: datetime
    raw: str
    id: int | None = None
    images: list[str] = field(default_factory=list)


@runtime_checkable
class SocialSource(Protocol):
    """Protocol for a platform-specific social post collector."""

    def collect(
        self,
        preset: Preset,
        source_descriptor: str,
        cutoff: datetime,
        dedup_store: Any,
        max_posts: int | None = None,
        skip_processed: bool = True,
    ) -> list[SocialPost]:
        """Collect posts from the platform.

        Args:
            preset: Preset configuration (provides preset_name, etc.).
            source_descriptor: Platform-specific source (e.g. subreddit name).
            cutoff: Posts older than this UTC datetime are ignored.
            dedup_store: Object with ``is_processed(platform, source_id, preset_name)``.
            max_posts: Cap on returned posts (newest first).
            skip_processed: When False, do not skip already-processed posts.

        Returns:
            List of normalized SocialPost objects.
        """
        ...
