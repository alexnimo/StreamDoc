import os
import time
from unittest.mock import patch, MagicMock

import pytest

from streamdoc.core.transcript import (
    TRANSCRIPT_SUPPORTED_LANGUAGES,
    _fetched_to_dicts,
    _parse_json3_file,
    _transcript_from_official,
    _transcript_from_yt_dlp_subtitles,
    fallback_audio_to_wav,
    fetch_transcript,
    transcribe_audio,
)


def test_supported_languages_contains_expected():
    for lang in ["en", "he", "ar"]:
        assert lang in TRANSCRIPT_SUPPORTED_LANGUAGES


# ---------------------------------------------------------------------------
# Tests for the v1.x API fix (get_transcript -> fetch)
# ---------------------------------------------------------------------------


def test_fetched_to_dicts_converts_snippet_objects():
    """_fetched_to_dicts should convert v1.x snippet objects to dicts."""
    # Reason: v1.x returns objects with .text/.start/.duration attributes.
    class FakeSnippet:
        def __init__(self, text, start, duration):
            self.text = text
            self.start = start
            self.duration = duration

    fetched = [
        FakeSnippet("Hello world", 0.0, 2.0),
        FakeSnippet("Second segment", 2.0, 3.0),
    ]
    result = _fetched_to_dicts(fetched)
    assert len(result) == 2
    assert result[0]["text"] == "Hello world"
    assert result[0]["start"] == 0.0
    assert result[0]["duration"] == 2.0
    assert result[1]["text"] == "Second segment"


def test_fetched_to_dicts_passes_through_dicts():
    """_fetched_to_dicts should handle dict inputs (backward compat with 0.6.x)."""
    fetched = [
        {"text": "Hello", "start": 0.0, "duration": 1.0},
        {"text": "World", "start": 1.0, "duration": 2.0},
    ]
    result = _fetched_to_dicts(fetched)
    assert len(result) == 2
    assert result[0]["text"] == "Hello"
    assert result[1]["text"] == "World"


def test_transcript_from_official_uses_fetch_not_get_transcript(monkeypatch):
    """Should call api.fetch(), not the removed get_transcript()."""
    # Reason: this is the critical regression test — get_transcript was
    # removed in v1.x and must never be called again.
    mock_api = MagicMock()
    mock_snippet = MagicMock()
    mock_snippet.text = "Test transcript"
    mock_snippet.start = 0.0
    mock_snippet.duration = 2.0
    mock_api.fetch = MagicMock(return_value=[mock_snippet])

    mock_yta_module = MagicMock()
    mock_yta_class = MagicMock(return_value=mock_api)
    mock_yta_module.YouTubeTranscriptApi = mock_yta_class

    with patch.dict("sys.modules", {"youtube_transcript_api": mock_yta_module}):
        result = _transcript_from_official("testVid123", ["en"])

    assert mock_api.fetch.called, "fetch() must be called (not get_transcript)"
    # Reason: MagicMock auto-creates attributes, so we check that
    # get_transcript was never called (not that it doesn't exist).
    get_transcript_calls = [c for c in mock_api.method_calls if c[0] == "get_transcript"]
    assert not get_transcript_calls, "get_transcript must not be called (removed in v1.x)"
    assert result is not None
    assert len(result) == 1
    assert result[0]["text"] == "Test transcript"


def test_transcript_from_official_falls_back_to_any_language(monkeypatch):
    """When configured languages fail, should try any available transcript."""
    class NoTranscriptFound(Exception):
        pass

    mock_api = MagicMock()
    # Reason: fetch with ['en','he','ar'] raises NoTranscriptFound.
    mock_api.fetch = MagicMock(side_effect=NoTranscriptFound("No transcript"))
    # Reason: list() returns a fake transcript list with one entry.
    mock_transcript = MagicMock()
    mock_snippet = MagicMock()
    mock_snippet.text = "Korean auto-gen"
    mock_snippet.start = 0.0
    mock_snippet.duration = 5.0
    mock_transcript.fetch = MagicMock(return_value=[mock_snippet])
    mock_api.list = MagicMock(return_value=[mock_transcript])

    mock_wta_module = MagicMock()
    mock_wta_module.YouTubeTranscriptApi = MagicMock(return_value=mock_api)
    mock_wta_module.NoTranscriptFound = NoTranscriptFound

    with patch.dict("sys.modules", {"youtube_transcript_api": mock_wta_module}):
        result = _transcript_from_official("testVid456", ["en", "he", "ar"])

    assert result is not None
    assert len(result) == 1
    assert result[0]["text"] == "Korean auto-gen"
    # Reason: fetch was tried first, then list() was called for fallback.
    assert mock_api.fetch.call_count == 1
    assert mock_api.list.called


def test_transcript_from_official_returns_none_when_all_fail(monkeypatch):
    """Should return None when both language-filtered and any-language fail."""
    mock_api = MagicMock()
    mock_api.fetch = MagicMock(side_effect=Exception("No transcript"))
    mock_api.list = MagicMock(side_effect=Exception("No transcripts at all"))

    mock_wta_module = MagicMock()
    mock_wta_module.YouTubeTranscriptApi = MagicMock(return_value=mock_api)

    with patch.dict("sys.modules", {"youtube_transcript_api": mock_wta_module}):
        result = _transcript_from_official("noTranscriptVid", ["en"])

    assert result is None


# ---------------------------------------------------------------------------
# Tests for yt-dlp subtitle fallback
# ---------------------------------------------------------------------------


def test_yt_dlp_subtitles_disabled_returns_none(monkeypatch):
    """When use_yt_dlp_subtitles is False, should return None immediately."""
    from streamdoc.config import Settings
    s = Settings(use_yt_dlp_subtitles=False)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)
    result = _transcript_from_yt_dlp_subtitles("testVid", ["en"])
    assert result is None


def test_yt_dlp_subtitles_enabled_fetches_and_parses(monkeypatch, tmp_path):
    """When enabled, should download subtitles via yt-dlp and parse json3."""
    import json
    from streamdoc.config import Settings

    s = Settings(use_yt_dlp_subtitles=True, yt_dlp_bypass_mode="default")
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    # Reason: create a fake json3 subtitle file that yt-dlp "downloads".
    json3_content = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hello"}]},
            {"tStartMs": 2000, "dDurationMs": 3000, "segs": [{"utf8": "World"}]},
        ]
    }
    sub_file = tmp_path / "testVid.en.json3"
    sub_file.write_text(json.dumps(json3_content), encoding="utf-8")

    # Reason: mock yt_dlp.YoutubeDL to just "download" by writing the file.
    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def download(self, urls):
            # Reason: simulate yt-dlp writing the subtitle file.
            for url in urls:
                vid = url.split("v=")[-1]
                target = tmp_path / f"{vid}.en.json3"
                target.write_text(json.dumps(json3_content), encoding="utf-8")

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _transcript_from_yt_dlp_subtitles("testVid", ["en"])

    assert result is not None
    assert len(result) == 2
    assert result[0]["text"] == "Hello"
    assert result[0]["start"] == 0.0
    assert result[1]["text"] == "World"
    assert result[1]["start"] == 2.0


def test_parse_json3_file_handles_missing_file(tmp_path):
    """_parse_json3_file should return None for a non-existent file."""
    result = _parse_json3_file(str(tmp_path / "nonexistent.json3"))
    assert result is None


def test_parse_json3_file_parses_valid_json3(tmp_path):
    """_parse_json3_file should correctly parse a json3 subtitle file."""
    import json
    content = {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 1500, "segs": [{"utf8": "Test"}]},
        ]
    }
    path = tmp_path / "test.json3"
    path.write_text(json.dumps(content), encoding="utf-8")
    result = _parse_json3_file(str(path))
    assert result is not None
    assert len(result) == 1
    assert result[0]["text"] == "Test"
    assert result[0]["start"] == 1.0
    assert result[0]["duration"] == 1.5


def test_fetch_transcript_uses_yt_dlp_fallback_when_official_fails(monkeypatch):
    """fetch_transcript should try yt-dlp subtitles when official API returns None."""
    from streamdoc.config import Settings
    s = Settings(use_yt_dlp_subtitles=True)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    # Reason: mock official API to return None (failure).
    monkeypatch.setattr(
        "streamdoc.core.transcript._transcript_from_official",
        lambda vid, langs: None,
    )
    # Reason: mock yt-dlp fallback to return a valid transcript.
    monkeypatch.setattr(
        "streamdoc.core.transcript._transcript_from_yt_dlp_subtitles",
        lambda vid, langs: [{"text": "From yt-dlp", "start": 0.0, "duration": 2.0}],
    )
    result = fetch_transcript("testVid789")
    assert len(result) >= 1
    assert result[0]["text"] == "From yt-dlp"


def test_fetch_transcript_skips_yt_dlp_when_disabled(monkeypatch):
    """fetch_transcript should return empty when official fails and yt-dlp disabled."""
    from streamdoc.config import Settings
    s = Settings(use_yt_dlp_subtitles=False)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    monkeypatch.setattr(
        "streamdoc.core.transcript._transcript_from_official",
        lambda vid, langs: None,
    )
    # Reason: when disabled, _transcript_from_yt_dlp_subtitles checks the
    # setting and returns None immediately (no yt-dlp calls). We verify
    # the overall result is empty — Whisper fallback is handled by the
    # caller in fetch.py, not by fetch_transcript.
    result = fetch_transcript("testVid000")
    assert result == []


@pytest.mark.skipif(
    os.name != "posix",
    reason="ffmpeg rejects empty input files on this platform, so this test would fail without valid media.",
)
def test_fallback_audio_to_wav_returns_output_path(tmp_path: pytest.TempPathFactory):
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.wav"
    src.write_bytes(b"")
    out = fallback_audio_to_wav(src, dst)
    assert out == dst


def test_transcribe_audio_times_out(monkeypatch, tmp_path):
    """Whisper transcription should return empty list when timeout is exceeded."""
    from streamdoc.config import Settings

    # Reason: set a very short timeout (0.5s) so the test runs fast.
    s = Settings(whisper_timeout_seconds=0.5)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    # Reason: mock faster_whisper so we don't need the actual model.
    # The mock's transcribe method sleeps longer than the timeout.
    mock_model = MagicMock()
    def _slow_transcribe(*args, **kwargs):
        time.sleep(2.0)  # sleeps longer than the 0.5s timeout
        return ([], MagicMock())
    mock_model.transcribe = _slow_transcribe

    mock_whisper_module = MagicMock()
    mock_whisper_module.WhisperModel = MagicMock(return_value=mock_model)

    with patch.dict("sys.modules", {"faster_whisper": mock_whisper_module}):
        wav = tmp_path / "fake.wav"
        wav.write_bytes(b"fake audio")
        result = transcribe_audio(wav)

    # Reason: timeout should cause an empty list return, not a hang.
    assert result == []


def test_transcribe_audio_returns_segments_on_success(monkeypatch, tmp_path):
    """Whisper transcription should return segments when it completes in time."""
    from streamdoc.config import Settings

    s = Settings(whisper_timeout_seconds=10.0)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    # Reason: mock a fast transcription that returns immediately.
    mock_segment = MagicMock()
    mock_segment.text = "  Hello world  "
    mock_segment.start = 0.0
    mock_segment.end = 2.0

    mock_model = MagicMock()
    mock_model.transcribe = MagicMock(return_value=([mock_segment], MagicMock()))

    mock_whisper_module = MagicMock()
    mock_whisper_module.WhisperModel = MagicMock(return_value=mock_model)

    with patch.dict("sys.modules", {"faster_whisper": mock_whisper_module}):
        wav = tmp_path / "fake.wav"
        wav.write_bytes(b"fake audio")
        result = transcribe_audio(wav)

    assert len(result) == 1
    assert result[0]["text"] == "Hello world"
    assert result[0]["start"] == 0.0
    assert result[0]["duration"] == 2.0


def test_transcribe_audio_no_whisper_returns_empty(monkeypatch, tmp_path):
    """If faster_whisper can't be imported, return empty list."""
    from streamdoc.config import Settings

    s = Settings(whisper_timeout_seconds=10.0)
    monkeypatch.setattr("streamdoc.core.transcript.settings", s)

    # Reason: mock the import to fail.
    import builtins
    real_import = builtins.__import__

    def _fail_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("No module named 'faster_whisper'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_fail_import):
        wav = tmp_path / "fake.wav"
        wav.write_bytes(b"fake audio")
        result = transcribe_audio(wav)

    assert result == []
