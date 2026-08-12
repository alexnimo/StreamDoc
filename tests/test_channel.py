import pytest

from streamdoc.core.channel import Channel, Video, resolve_channel


def test_channel_dataclass():
    c = Channel(id="abc", title="Test")
    assert c.id == "abc"


def test_video_dataclass_defaults():
    v = Video(id="v1", channel_id="abc", title="T", published_at="2026-01-01")
    assert v.duration_seconds is None


def test_resolve_channel_raises_for_bad_url():
    """A completely invalid URL should fail to resolve via both yt-dlp and HTML."""
    with pytest.raises(RuntimeError, match="Could not resolve"):
        resolve_channel("not-a-valid-url")
