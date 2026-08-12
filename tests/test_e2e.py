from __future__ import annotations

from pathlib import Path

import pytest

import streamdoc.config
from streamdoc.config import Settings
from streamdoc.core.channel import Channel
from streamdoc.core.fetch import VideoDataclass, run_fetch
from streamdoc.db import init_db, session_scope
from streamdoc.models.preset import Preset
from streamdoc.models.video import Video as VideoModel


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_root = tmp_path / "data"
    for sub in ("Media", "Outputs", "State", "Models", "integrations", "cookies"):
        (data_root / sub).mkdir(parents=True, exist_ok=True)
    cfg = {
        "db_path": str(data_root / "State" / "streamdoc.sqlite"),
        "media_root": str(data_root / "Media"),
        "output_root": str(data_root / "Outputs"),
        "model_root": str(data_root / "Models"),
        "presets_path": str(data_root / "presets"),
    }

    # Reason: patch settings attributes directly on each module that
    # imported `settings` at module level.  This avoids module reloads
    # which break isinstance checks in other test files (the reloaded
    # Channel class becomes a different type object).
    import streamdoc.config
    import streamdoc.core.output
    import streamdoc.core.report
    import streamdoc.core.frames
    import streamdoc.core.transcript
    import streamdoc.core.fetch
    import streamdoc.core.downloader
    import streamdoc.core.channel
    import streamdoc.presets

    for key, value in cfg.items():
        setattr(streamdoc.config.settings, key, value)

    # Reason: reset lazy engine so it picks up new db_path
    import streamdoc.db as db_mod
    if db_mod._engine is not None:
        db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._session_factory = None

    init_db()
    yield
    if db_mod._engine is not None:
        db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._session_factory = None


def _seed_preset(name: str) -> Preset:
    p = Preset(
        id=name,
        name=name,
        channel_list_id="fake://unit-test",
        prompt_md="Summarize clearly.",
        outputs="pdf,markdown,notebooklm",
        notebooklm_kind=None,
        schedule=None,
        schedule_interval_hours=12,
        lookback_hours=24,
        max_videos=None,
        text_filter=None,
        date_range_days=None,
        playlist_mode=False,
        skip_processed=True,
        active=True,
    )
    with session_scope() as s:
        s.merge(p)
    return p


def _seed_video(video_id: str, channel_id: str = "UC123") -> VideoModel:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    vm = VideoModel(
        id=video_id,
        channel_id=channel_id,
        title="Test Video",
        published_at=now,
        media_status="missing",
        transcript_status="missing",
        output_status="missing",
    )
    with session_scope() as s:
        s.merge(vm)
    return vm


def test_preset_run_creates_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    preset_id = "e2e_preset"
    video_id = "vid001"
    _seed_preset(preset_id)
    _seed_video(video_id)

    import streamdoc.core.fetch as fetch_module
    from datetime import datetime, timezone

    monkeypatch.setattr(
        fetch_module,
        "resolve_channel",
        lambda url: Channel(id="UC123", title="Test Channel", source="youtube"),
    )
    monkeypatch.setattr(
        fetch_module,
        "_list_videos",
        lambda ch, *, playlist_mode=False, max_videos=None: [
            VideoDataclass(
                id=video_id,
                channel_id="UC123",
                title="Test Video",
                published_at=datetime.now(timezone.utc).isoformat(),
                webpage_url="https://example.com/watch?v=vid001",
            )
        ],
    )

    created: dict[str, Path] = {}

    def fake_download_media(v):
        dest = Path(Settings().media_root) / v.channel_id / v.id / f"{v.id}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-media")
        created["media"] = dest
        # Reason: _download_media now returns a DownloadResult dataclass
        # with a .path attribute, not a bare Path.
        from streamdoc.core.downloader import DownloadResult
        return DownloadResult(path=dest)

    monkeypatch.setattr(fetch_module, "_download_media", fake_download_media)

    def fake_transcript(media_path, video_id):
        created["transcript_input"] = media_path
        return [{"start": 0.0, "duration": 1.0, "text": "hello world"}]

    monkeypatch.setattr(fetch_module, "_get_transcript", fake_transcript)

    # Minimal valid 1x1 JPEG bytes so PIL/reportlab don't choke
    _MINI_JPEG = bytes.fromhex(
        "ffd8ffe000104a46494600010101000100010000"
        "ffdb004300010101010101010101010101010101010101010101"
        "0101010101010101010101010101010101010101010101010101"
        "01010101010101010101010101010101010101ffc0000b080001"
        "00010101011100ffc4001f000001050101010101010000000000"
        "0000000102030405060708090a0bffc400b51000020103030204"
        "030504040000017d010203000411051221314106135161072271"
        "14328191a1082342b1c11552d1f02433627282090a161718191a"
        "25262728292a3435363738393a434445464748494a5354555657"
        "58595a636465666768696a737475767778797a838485868788"
        "898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7"
        "b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6"
        "e7e8e9eaf2f3f4f5f6f7f8f9faffc4001f010003010101010101"
        "010101010000000000000102030405060708090a0bffc400b511"
        "0002010204040304070404040000017d01020300041105122131"
        "41061351610722711432818191a1082342b1c11552d1f0243362"
        "7282090a161718191a25262728292a3435363738393a43444546"
        "4748494a535455565758595a636465666768696a737475767778"
        "797a838485868788898a92939495969798999aa2a3a4a5a6a7a8"
        "a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7"
        "d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000801"
        "0100003f00bf0000000000000000ffd9"
    )
    media_root = streamdoc.config.settings.media_root
    frames_dir = Path(media_root) / "UC123" / video_id / "frames"
    fake_frames = [
        frames_dir / "f1.jpg",
        frames_dir / "f2.jpg",
    ]
    for frame in fake_frames:
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(_MINI_JPEG)

    monkeypatch.setattr(fetch_module, "extract_and_dedup", lambda media_path: fake_frames)

    # Reason: per-video NotebookLM upload was removed. NotebookLM is now
    # a batch operation in _send_reports at the end of run_once. Videos
    # are always marked "ready" after outputs are built. The preset has
    # notebooklm_kind=None so _send_reports will skip NotebookLM entirely.
    artifacts = run_fetch(preset_id)
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.status == "ready"
    assert created["media"].exists()

    # Use the patched module-level settings, not a fresh Settings() instance
    out_root = streamdoc.config.settings.output_root
    md_path = Path(out_root) / preset_id / f"{video_id}.md"
    assert md_path.exists(), "Markdown output should exist"
    pdf_path = md_path.with_suffix(".pdf")
    assert pdf_path.exists(), "PDF output should exist"

    with session_scope() as s:
        loaded = s.get(VideoModel, video_id)
        assert loaded is not None
        assert loaded.media_status == "ready"
        assert loaded.transcript_status == "ready"
        # Reason: output_status is always "ready" now — NotebookLM upload
        # failure no longer marks the video as "integration-failed"
        assert loaded.output_status == "ready"

    # Reason: no integration-failed marker is written anymore
    failure_marker = md_path.parent / f"{video_id}.integration-failed"
    assert not failure_marker.exists(), "integration-failed marker should NOT be written"

    # Also verify new artifact fields are populated
    assert art.title == "Test Video"
    assert art.channel_title == "Test Channel"
    assert art.frame_count == 2
    assert art.transcript_word_count == 2  # "hello world"
