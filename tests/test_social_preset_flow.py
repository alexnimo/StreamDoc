"""Tests for the social preset flow in the PresetRunner pipeline.

Covers the `preset_type == "social"` branch of `run_once`, which delegates
to `_run_social` for collection, report building, and destination dispatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import pytest

from streamdoc.core.fetch import PresetRunner, RunArtifact
from streamdoc.integrations.social.base import SocialPost


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_preset(monkeypatch, tmp_path):
    """Return a social Preset mock with two social sources."""
    import tempfile

    from streamdoc.config import settings
    from streamdoc.db import init_db

    # Isolated DB
    db_path = tmp_path / "test_social.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "output_root", str(tmp_path / "outputs"))
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    init_db()

    # Insert a social-type preset
    from streamdoc.models.preset import Preset as PresetModel

    from streamdoc.db import session_scope

    with session_scope() as s:
        p = PresetModel(
            id="test_social_preset",
            name="Test Social",
            preset_type="social",
            social_sources=json.dumps([
                {"platform": "reddit", "identifier": "r/wallstreetbets", "max_posts": 3},
                {"platform": "stocktwits", "identifier": "$AAPL", "max_posts": 3},
            ]),
            social_lookback_hours=48,
            social_max_posts=10,
            outputs="report",
            schedule=None,
        )
        s.add(p)
    return p


@pytest.fixture
def sample_posts() -> list[SocialPost]:
    """Return sample social posts that mock collectors return."""
    now = datetime.now(timezone.utc)
    return [
        SocialPost(
            platform="reddit",
            source_id="reddit_001",
            author="redditor1",
            text="Sample Reddit post about GME",
            published_at=now - timedelta(hours=2),
            url="https://reddit.com/r/wallstreetbets/comments/1",
            raw='{"data": {"title": "GME", "selftext": "Sample Reddit post"}}',
            images=["/fake/path/img1.png"],
        ),
        SocialPost(
            platform="reddit",
            source_id="reddit_002",
            author="redditor2",
            text="Another Reddit post",
            published_at=now - timedelta(hours=5),
            url="https://reddit.com/r/wallstreetbets/comments/2",
            raw='{"data": {"title": "Another", "selftext": "Another Reddit post"}}',
            images=[],
        ),
        SocialPost(
            platform="stocktwits",
            source_id="st_001",
            author="trader42",
            text="$AAPL Bullish sentiment post",
            published_at=now - timedelta(hours=1),
            url="https://stocktwits.com/trader42/1",
            raw='{"body": "$AAPL Bullish sentiment post", "user": {"username": "trader42"}}',
            images=["/fake/path/st_img.png"],
        ),
    ]


# ── Tests ───────────────────────────────────────────────────────────────


def test_social_run_once_dispatches_to_run_social(mock_preset, sample_posts):
    """Run_once with social preset_type delegates to _run_social."""

    with (
        patch(
            "streamdoc.core.fetch.PresetRunner._run_social",
            return_value=[],
        ) as mock_social,
    ):
        runner = PresetRunner("test_social_preset")
        result = runner.run_once()

    mock_social.assert_called_once()
    assert result == []


def test_social_run_once_skipped_for_youtube(mock_preset, sample_posts):
    """Youtube preset_type does NOT call _run_social."""
    from streamdoc.db import session_scope
    from streamdoc.models.preset import Preset as PresetModel

    with session_scope() as s:
        p = s.get(PresetModel, "test_social_preset")
        p.preset_type = "youtube"

    with (
        patch(
            "streamdoc.core.fetch.PresetRunner._run_social",
        ) as mock_social,
        patch(
            "streamdoc.core.fetch._list_videos",
            return_value=[],
        ),
    ):
        runner = PresetRunner("test_social_preset")
        runner.run_once()
        mock_social.assert_not_called()


def test_run_social_collects_and_builds_report(mock_preset, sample_posts, tmp_path):
    """_run_social collects from registered sources, builds one unified report, returns one artifact."""
    from types import SimpleNamespace

    preset = SimpleNamespace(
        name="Test Social",
        social_sources=json.dumps([
            {"platform": "reddit", "identifier": "r/wallstreetbets", "max_posts": 3},
        ]),
        social_lookback_hours=48,
        social_max_posts=10,
        outputs="report",
        prompt_md="",
        skip_processed=True,
    )
    mock_collector = MagicMock()
    mock_collector.collect.return_value = sample_posts

    with (
        patch(
            "streamdoc.integrations.social.get_collector",
            return_value=lambda: mock_collector,
        ),
        patch(
            "streamdoc.core.fetch.complete_job",
        ) as mock_complete,
    ):
        runner = PresetRunner("test_social_preset")
        artifacts = runner._run_social(
            preset,
            job_id="test_job_social",
        )

    # Should have a single unified report artifact.
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.title == "Social Report — Test Social"
    assert art.channel_title == "social"
    assert art.status == "ready"
    assert art.md_path.exists()

    report_text = art.md_path.read_text(encoding="utf-8")
    # Reason: each platform gets its own dedicated section following the
    # same document pattern, so both platform section headers must appear.
    assert "## Reddit Report" in report_text
    assert "## Stocktwits Report" in report_text
    assert "reddit" in report_text
    assert "stocktwits" in report_text
    assert "$AAPL Bullish sentiment post" in report_text

    # complete_job should be called with the single artifact
    mock_complete.assert_called_once()
    call_args = mock_complete.call_args
    assert len(call_args.args[1]) == 1


def test_run_social_empty_source_list_returns_empty():
    """_run_social with no social_sources returns empty."""
    from types import SimpleNamespace

    preset = SimpleNamespace(
        name="Test Social",
        social_sources=None,
        social_lookback_hours=48,
        social_max_posts=10,
        outputs="report",
        prompt_md="",
    )

    with (
        patch("streamdoc.core.fetch.fail_job") as mock_fail,
        patch("streamdoc.core.fetch.complete_job"),
    ):
        runner = PresetRunner("test_social_preset")
        artifacts = runner._run_social(
            preset,
            job_id="test_job_empty",
        )

    assert artifacts == []
    mock_fail.assert_called_once()


def test_run_social_collector_failure_continues(mock_preset, sample_posts):
    """A single collector failure should not block the whole pipeline."""
    from types import SimpleNamespace

    preset = SimpleNamespace(
        name="Test Social",
        social_sources=json.dumps([
            {"platform": "reddit", "identifier": "r/wallstreetbets", "max_posts": 3},
            {"platform": "stocktwits", "identifier": "$AAPL", "max_posts": 3},
        ]),
        social_lookback_hours=48,
        social_max_posts=10,
        outputs="report",
        prompt_md="",
        skip_processed=True,
    )

    mock_reddit = MagicMock()
    mock_reddit.collect.side_effect = RuntimeError("Reddit API unavailable")

    mock_stocktwits = MagicMock()
    mock_stocktwits.collect.return_value = [sample_posts[-1]]  # only the stocktwits post

    side_effects = [
        lambda: mock_reddit,
        lambda: mock_stocktwits,
    ]

    with (
        patch(
            "streamdoc.integrations.social.get_collector",
            side_effect=side_effects,
        ),
        patch(
            "streamdoc.core.fetch.complete_job",
        ),
    ):
        runner = PresetRunner("test_social_preset")
        artifacts = runner._run_social(
            preset,
            job_id="test_job_partial",
        )

    # Pipeline continues and builds a single unified report with the surviving post.
    assert len(artifacts) == 1
    report_text = artifacts[0].md_path.read_text(encoding="utf-8")
    assert "## Stocktwits Report" in report_text
    assert "stocktwits" in report_text
    assert "trader42" in report_text
    # Reason: Reddit collected zero posts (collector raised), so its
    # section must be omitted entirely — no empty section, no wasted space.
    assert "## Reddit Report" not in report_text


def test_run_social_sends_to_destinations(mock_preset, sample_posts):
    """_run_social calls _send_reports with a single unified report artifact."""
    from types import SimpleNamespace

    preset = SimpleNamespace(
        name="Test Social",
        social_sources=json.dumps([
            {"platform": "reddit", "identifier": "r/wallstreetbets", "max_posts": 3},
        ]),
        social_lookback_hours=48,
        social_max_posts=10,
        outputs="report",
        prompt_md="",
        skip_processed=True,
    )
    mock_collector = MagicMock()
    mock_collector.collect.return_value = sample_posts

    with (
        patch(
            "streamdoc.integrations.social.get_collector",
            return_value=lambda: mock_collector,
        ),
        patch(
            "streamdoc.core.fetch.PresetRunner._send_reports",
            return_value={"report": "OK"},
        ) as mock_send,
        patch(
            "streamdoc.core.fetch.complete_job",
        ),
    ):
        runner = PresetRunner("test_social_preset")
        artifacts = runner._run_social(preset, job_id="test_job_send")

    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    assert len(args) >= 2
    assert len(args[1]) == 1  # single unified report


def test_run_social_with_agy_output(mock_preset, sample_posts):
    """Social pipeline works with agy destination output set."""
    from types import SimpleNamespace

    preset = SimpleNamespace(
        name="Test Social",
        social_sources=json.dumps([
            {"platform": "reddit", "identifier": "r/wallstreetbets", "max_posts": 3},
        ]),
        social_lookback_hours=48,
        social_max_posts=10,
        outputs='["agy"]',
        prompt_md="",
        skip_processed=True,
    )
    mock_collector = MagicMock()
    mock_collector.collect.return_value = sample_posts

    with (
        patch(
            "streamdoc.integrations.social.get_collector",
            return_value=lambda: mock_collector,
        ),
        patch(
            "streamdoc.core.fetch.complete_job",
        ),
    ):
        runner = PresetRunner("test_social_preset")
        artifacts = runner._run_social(preset, job_id="test_job_agy")

    assert len(artifacts) == 1  # single unified report
    assert all(a.status == "ready" for a in artifacts)
