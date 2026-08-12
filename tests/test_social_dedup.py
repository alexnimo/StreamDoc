"""Tests for the social post deduplication store."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from streamdoc.config import Settings
from streamdoc.db import init_db, session_scope
from streamdoc.integrations.social import SocialPost, SocialPostStore
from streamdoc.models.social_post import SocialPost as SocialPostORM


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Use a temp SQLite database and media root for every test."""
    s = Settings(
        db_path=str(tmp_path / "test.sqlite"),
        media_root=str(tmp_path / "media"),
    )
    monkeypatch.setattr("streamdoc.config.settings", s)
    init_db()


def _sample_post(source_id: str) -> SocialPost:
    return SocialPost(
        platform="reddit",
        source_id=source_id,
        url=f"https://reddit.com/r/test/comments/{source_id}",
        author="u1",
        text="hello",
        published_at=datetime.now(timezone.utc),
        raw='{"id": "' + source_id + '"}',
    )


def test_mark_processed_makes_is_processed_true():
    """A post is considered processed after mark_processed is called."""
    store = SocialPostStore()
    post = _sample_post("post1")
    assert store.is_processed("reddit", "post1", "preset-a") is False

    store.mark_processed(post, "preset-a")

    assert store.is_processed("reddit", "post1", "preset-a") is True


def test_same_post_different_preset_is_not_processed():
    """Dedup is scoped to preset_name, not globally unique."""
    store = SocialPostStore()
    post = _sample_post("post1")
    store.mark_processed(post, "preset-a")

    assert store.is_processed("reddit", "post1", "preset-b") is False


def test_reset_outside_window_allows_recollect():
    """After reset_outside_window removes an old record, is_processed returns False."""
    store = SocialPostStore()
    post = _sample_post("post1")
    store.mark_processed(post, "preset-a")
    assert store.is_processed("reddit", "post1", "preset-a") is True

    # Manually age the record so it is outside a 1-hour window.
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with session_scope() as s:
        row = (
            s.query(SocialPostORM)
            .filter_by(platform="reddit", source_id="post1", preset_name="preset-a")
            .first()
        )
        assert row is not None
        row.processed_at = old

    store.reset_outside_window("preset-a", hours=1)

    assert store.is_processed("reddit", "post1", "preset-a") is False


def test_reset_outside_window_keeps_recent_records():
    """Records inside the window are not removed by reset_outside_window."""
    store = SocialPostStore()
    post = _sample_post("post1")
    store.mark_processed(post, "preset-a")

    store.reset_outside_window("preset-a", hours=24)

    assert store.is_processed("reddit", "post1", "preset-a") is True
