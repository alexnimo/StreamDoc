import pytest
from unittest.mock import patch

from streamdoc.config import settings
from streamdoc.core.channel import Video as VideoDataclass
from streamdoc.core.fetch import _is_short


def test_is_short_disabled(monkeypatch):
    """When skip_shorts is False, no video is treated as a Short."""
    monkeypatch.setattr(settings, "skip_shorts", False)
    v = VideoDataclass(
        id="s1",
        channel_id="ch1",
        title="Short",
        published_at="",
        duration_seconds=30,
        webpage_url="https://www.youtube.com/shorts/s1",
    )
    assert _is_short(v) is False


def test_is_short_by_url(monkeypatch):
    """A /shorts/ URL should be detected as a Short."""
    monkeypatch.setattr(settings, "skip_shorts", True)
    monkeypatch.setattr(settings, "shorts_max_seconds", 60)
    v = VideoDataclass(
        id="s1",
        channel_id="ch1",
        title="Short",
        published_at="",
        duration_seconds=120,
        webpage_url="https://www.youtube.com/shorts/s1",
    )
    assert _is_short(v) is True


def test_is_short_by_duration(monkeypatch):
    """A video at or below the threshold should be detected as a Short."""
    monkeypatch.setattr(settings, "skip_shorts", True)
    monkeypatch.setattr(settings, "shorts_max_seconds", 60)
    v = VideoDataclass(
        id="v1",
        channel_id="ch1",
        title="Regular",
        published_at="",
        duration_seconds=60,
        webpage_url="https://www.youtube.com/watch?v=v1",
    )
    assert _is_short(v) is True


def test_is_not_short_regular_video(monkeypatch):
    """A regular video longer than the threshold is not a Short."""
    monkeypatch.setattr(settings, "skip_shorts", True)
    monkeypatch.setattr(settings, "shorts_max_seconds", 60)
    v = VideoDataclass(
        id="v1",
        channel_id="ch1",
        title="Regular",
        published_at="",
        duration_seconds=120,
        webpage_url="https://www.youtube.com/watch?v=v1",
    )
    assert _is_short(v) is False


def test_is_short_unknown_duration(monkeypatch):
    """If duration is unknown and URL is not /shorts/, do not treat as Short."""
    monkeypatch.setattr(settings, "skip_shorts", True)
    monkeypatch.setattr(settings, "shorts_max_seconds", 60)
    v = VideoDataclass(
        id="v1",
        channel_id="ch1",
        title="Unknown",
        published_at="",
        duration_seconds=None,
        webpage_url="https://www.youtube.com/watch?v=v1",
    )
    assert _is_short(v) is False
