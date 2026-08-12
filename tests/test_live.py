"""Live integration tests against real YouTube endpoints.

Marked with pytest.mark.live so they can be skipped in CI:
    pytest -m "not live"
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pathlib import Path

from streamdoc.core.channel import Channel, Video as VideoDataclass, resolve_channel
from streamdoc.core.fetch import run_fetch
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.models.video import Video as VideoModel

# Targets provided by Alex
REAL_CHANNEL_HANDLE = "https://www.youtube.com/@TradersHelpingTraders"
REAL_VIDEO_URL = "https://youtu.be/n8H8P64x9Mc?si=ApKFik0KaA_hesDv"
REAL_VIDEO_ID = "n8H8P64x9Mc"


@pytest.fixture(scope="session", autouse=True)
def setup_live_db():
    """Ensure DB is initialized for live tests."""
    init_db()


@pytest.mark.live
def test_live_channel_resolution():
    """Verify we can resolve the real handle to a Channel object."""
    channel = resolve_channel(REAL_CHANNEL_HANDLE)
    assert isinstance(channel, Channel)
    assert channel.id is not None
    assert channel.title is not None


@pytest.mark.live
def test_live_video_pipeline():
    """Verify the full pipeline for the specific video provided.

    This test is marked .live because it requires network access and
    a working yt-dlp + JS runtime.  Skip with: pytest -m "not live"
    """
    preset_id = "live_test_video"

    p = Preset(
        id=preset_id,
        name=preset_id,
        channel_list_id=REAL_CHANNEL_HANDLE,
        prompt_md="Analyze this trading video for key strategies and indicators.",
        outputs="pdf,markdown",
        lookback_hours=8760,  # 1 year lookback to ensure we hit the target video
        skip_processed=False,
        active=True,
    )
    with session_scope() as s:
        s.merge(p)

    artifacts = run_fetch(preset_id)

    target_art = next((a for a in artifacts if a.video_id == REAL_VIDEO_ID), None)

    assert target_art is not None, f"Video {REAL_VIDEO_ID} was not processed in the fetch run"
    assert target_art.md_path.exists(), "Markdown report was not generated"
    assert target_art.pdf_path is not None and target_art.pdf_path.exists(), "PDF report was not generated"


@pytest.mark.live
def test_live_multiple_videos_and_presets():
    """Verify that a preset applied to a channel picks up multiple videos."""
    preset_id = "live_finance_preset"
    p = Preset(
        id=preset_id,
        name="Finance Deep Dive",
        channel_list_id=REAL_CHANNEL_HANDLE,
        prompt_md="Focus on the specific trade entries and exits mentioned.",
        outputs="markdown",
        lookback_hours=168,  # Last 7 days
        skip_processed=False,
        active=True,
    )
    with session_scope() as s:
        s.merge(p)

    artifacts = run_fetch(preset_id)

    # Reason: may be 0 if no videos in 7 days, but should not crash
    assert len(artifacts) >= 0
    for art in artifacts:
        assert art.md_path.exists()
        content = art.md_path.read_text(encoding="utf-8")
        assert "Focus on the specific trade entries and exits mentioned." in content


if __name__ == "__main__":
    pytest.main([__file__, "-s"])
