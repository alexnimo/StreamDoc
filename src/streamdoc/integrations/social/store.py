"""Deduplication store for collected social posts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from streamdoc.db import session_scope
from streamdoc.integrations.social.base import SocialPost
from streamdoc.models.social_post import SocialPost as SocialPostModel


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO timestamp, returning None on failure."""
    if not value:
        return None
    try:
        v = value
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v)
    except (ValueError, TypeError):
        return None


def _is_older_than_hours(value: str | None, hours: float) -> bool:
    """Return True if the timestamp is older than N hours from now (UTC)."""
    dt = _parse_dt(value)
    if not dt:
        return False
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    try:
        return dt < cutoff
    except TypeError:
        # Reason: if dt is naive, assume it was stored as UTC.
        return dt.replace(tzinfo=UTC) < cutoff


class SocialPostStore:
    """Wraps the SocialPost ORM to provide deduplication helpers."""

    def is_processed(self, platform: str, source_id: str, preset_name: str) -> bool:
        """Return True if the post was already processed for this preset.

        Args:
            platform: Platform identifier (e.g. "reddit").
            source_id: Unique post ID from the source platform.
            preset_name: Preset display name used as the dedup scope.

        Returns:
            True when a matching processed record exists.
        """
        with session_scope() as session:
            existing = (
                session.query(SocialPostModel)
                .filter_by(platform=platform, source_id=source_id, preset_name=preset_name)
                .first()
            )
            return existing is not None and bool(existing.processed)

    def mark_processed(self, post: SocialPost, preset_name: str) -> None:
        """Persist a post as processed for the given preset.

        Uses an upsert so repeated calls are idempotent and the DB unique
        constraint on (platform, source_id, preset_name) is not violated.

        Args:
            post: Normalized post to record.
            preset_name: Preset display name used as the dedup scope.
        """
        self.mark_processed_many([post], preset_name)

    def mark_processed_many(self, posts: list[SocialPost], preset_name: str) -> None:
        """Persist many posts as processed in a single session.

        Args:
            posts: Normalized posts to record.
            preset_name: Preset display name used as the dedup scope.
        """
        if not posts:
            return
        with session_scope() as session:
            now = datetime.now(UTC).isoformat()
            existing_records = {
                (row.platform, row.source_id): row
                for row in session.query(SocialPostModel)
                .filter_by(preset_name=preset_name)
                .all()
            }
            seen: set[tuple[str, str]] = set()
            for post in posts:
                key = (post.platform, post.source_id)
                if key in seen:
                    continue
                seen.add(key)
                existing = existing_records.get(key)
                if existing is not None:
                    existing.processed = True
                    existing.processed_at = now
                    existing.output_status = "ready"
                    existing.raw_data = post.raw
                else:
                    session.add(
                        SocialPostModel(
                            platform=post.platform,
                            source_id=post.source_id,
                            preset_name=preset_name,
                            processed=True,
                            processed_at=now,
                            output_status="ready",
                            raw_data=post.raw,
                        )
                    )

    def reset_outside_window(self, preset_name: str, hours: float) -> None:
        """Remove processed records older than the lookback window.

        Args:
            preset_name: Preset display name to filter on.
            hours: Retention window in hours; older records are deleted.

        Reason: mirrors the video dedup pattern where records outside the
        current lookback window are removed so the same content can be
        re-collected in a future run.
        """
        with session_scope() as session:
            rows = (
                session.query(SocialPostModel)
                .filter_by(preset_name=preset_name)
                .all()
            )
            for row in rows:
                if _is_older_than_hours(row.processed_at, hours):
                    session.delete(row)
