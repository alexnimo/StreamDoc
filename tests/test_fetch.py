from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from streamdoc.core.channel import Video as VideoDataclass
from streamdoc.core.fetch import FetchPolicy, _fetch_video_upload_dates, _parse_published, default_policy


def test_default_policy_values():
    p = default_policy()
    assert p.lookback_hours == 24
    assert p.max_age_days is None
    assert p.require_new is True


def test_fetch_policy_override():
    p = FetchPolicy(lookback_hours=12, max_age_days=30, require_new=False)
    assert p.lookback_hours == 12
    assert p.max_age_days == 30
    assert p.require_new is False


def test_parse_published_iso_with_timezone():
    """ISO 8601 with timezone should parse correctly."""
    dt = _parse_published("2026-07-01T19:34:57+00:00")
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 1
    assert dt.tzinfo is not None


def test_parse_published_iso_with_z_suffix():
    """ISO 8601 with Z suffix should parse correctly."""
    dt = _parse_published("2026-07-01T19:34:57Z")
    assert dt.year == 2026
    assert dt.hour == 19


def test_parse_published_yt_dlp_yyyymmdd():
    """yt-dlp YYYYMMDD format should parse as UTC."""
    dt = _parse_published("20260701")
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 1
    assert dt.tzinfo == timezone.utc


def test_parse_published_empty_returns_epoch():
    """Empty string should return epoch (1970-01-01) — treated as old."""
    dt = _parse_published("")
    assert dt.year == 1970
    assert dt.month == 1
    assert dt.day == 1


def test_parse_published_none_returns_epoch():
    """None should return epoch (1970-01-01)."""
    dt = _parse_published(None)  # type: ignore[arg-type]
    assert dt.year == 1970


def test_parse_published_garbage_returns_epoch():
    """Unparseable strings should return epoch, not raise."""
    dt = _parse_published("not-a-date")
    assert dt.year == 1970


def test_parse_published_epoch_is_before_cutoff():
    """Epoch dates should be before any reasonable lookback cutoff."""
    epoch = _parse_published("")
    cutoff = datetime.now(timezone.utc)
    assert epoch < cutoff


# ---------------------------------------------------------------------------
# Tests for _fetch_video_upload_dates (concurrent date backfill)
# ---------------------------------------------------------------------------


def test_fetch_video_upload_dates_empty_when_all_dated():
    """Should return empty dict when all videos already have dates."""
    videos = [
        VideoDataclass(id="vid1", channel_id="ch1", title="V1", published_at="20260101"),
        VideoDataclass(id="vid2", channel_id="ch1", title="V2", published_at="20260102"),
    ]
    result = _fetch_video_upload_dates(videos, limit=15)
    assert result == {}


def test_fetch_video_upload_dates_empty_when_no_videos():
    """Should return empty dict when videos list is empty."""
    result = _fetch_video_upload_dates([], limit=15)
    assert result == {}


def test_fetch_video_upload_dates_respects_limit():
    """Should only fetch dates for up to `limit` undated videos."""
    # Reason: create 10 undated videos, limit to 3 — only 3 should be fetched.
    videos = [
        VideoDataclass(id=f"vid{i}", channel_id="ch1", title=f"V{i}", published_at="")
        for i in range(10)
    ]

    fetched_ids: list[str] = []

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            vid = url.split("v=")[-1]
            fetched_ids.append(vid)
            return {"upload_date": "20260115"}

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _fetch_video_upload_dates(videos, limit=3, max_workers=2)

    assert len(fetched_ids) <= 3, f"Should only fetch 3 dates, got {len(fetched_ids)}"
    assert len(result) <= 3


def test_fetch_video_upload_dates_concurrent_fetches_all():
    """Concurrent fetching should fetch dates for all undated videos."""
    videos = [
        VideoDataclass(id=f"vid{i}", channel_id="ch1", title=f"V{i}", published_at="")
        for i in range(5)
    ]

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {"upload_date": "20260120"}

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _fetch_video_upload_dates(videos, limit=10, max_workers=5)

    assert len(result) == 5
    for i in range(5):
        assert result[f"vid{i}"] == "20260120"


def test_fetch_video_upload_dates_handles_yt_dlp_errors():
    """Should gracefully handle yt-dlp extraction errors per video."""
    videos = [
        VideoDataclass(id="good1", channel_id="ch1", title="Good", published_at=""),
        VideoDataclass(id="bad1", channel_id="ch1", title="Bad", published_at=""),
    ]

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            vid = url.split("v=")[-1]
            if vid == "bad1":
                raise RuntimeError("Network error")
            return {"upload_date": "20260125"}

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _fetch_video_upload_dates(videos, limit=10, max_workers=2)

    # Reason: good1 should have a date, bad1 should be missing (not crash).
    assert result.get("good1") == "20260125"
    assert "bad1" not in result


def test_fetch_video_upload_dates_falls_back_to_sequential():
    """Should fall back to sequential if thread pool fails entirely."""
    videos = [
        VideoDataclass(id="vid1", channel_id="ch1", title="V1", published_at=""),
    ]

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {"upload_date": "20260130"}

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    # Reason: force ThreadPoolExecutor to fail so the sequential fallback runs.
    with patch("concurrent.futures.ThreadPoolExecutor", side_effect=RuntimeError("Pool broken")), \
         patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _fetch_video_upload_dates(videos, limit=10, max_workers=5)

    assert result.get("vid1") == "20260130"


def test_fetch_video_upload_dates_uses_api_when_key_is_set(monkeypatch):
    """Should use YouTube Data API before yt-dlp when an API key is set."""
    from streamdoc.config import settings
    monkeypatch.setattr(settings, "youtube_api_key", "test-api-key")

    videos = [
        VideoDataclass(id="vid1", channel_id="ch1", title="V1", published_at=""),
    ]

    def fake_api_fetch(ids, key):
        assert key == "test-api-key"
        return {ids[0]: {"published_at": "2026-07-14T01:00:00Z"}}

    with patch("streamdoc.core.fetch._fetch_video_metadata_from_api", side_effect=fake_api_fetch):
        result = _fetch_video_upload_dates(videos, limit=10)

    assert result == {"vid1": "2026-07-14T01:00:00Z"}


def test_fetch_video_upload_dates_falls_back_to_ytdlp_when_api_is_partial(monkeypatch):
    """Should fetch missing IDs via yt-dlp when the API returns partial data."""
    from streamdoc.config import settings
    monkeypatch.setattr(settings, "youtube_api_key", "test-api-key")

    videos = [
        VideoDataclass(id="api1", channel_id="ch1", title="API", published_at=""),
        VideoDataclass(id="yt1", channel_id="ch1", title="YT", published_at=""),
    ]

    def fake_api_fetch(ids, key):
        return {"api1": {"published_at": "2026-07-14T01:00:00Z"}}

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {"upload_date": "20260713"}

    mock_ytdlp = MagicMock()
    mock_ytdlp.YoutubeDL = FakeYDL

    with patch("streamdoc.core.fetch._fetch_video_metadata_from_api", side_effect=fake_api_fetch), \
         patch.dict("sys.modules", {"yt_dlp": mock_ytdlp}):
        result = _fetch_video_upload_dates(videos, limit=10, max_workers=2)

    assert result["api1"] == "2026-07-14T01:00:00Z"
    assert result["yt1"] == "20260713"


# ---------------------------------------------------------------------------
# Regression: _load_preset must load notebooklm_prompt_template
# ---------------------------------------------------------------------------


def test_load_preset_includes_notebooklm_prompt_template(monkeypatch):
    """_load_preset must load notebooklm_prompt_template from the DB."""
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.models.preset import Preset as PresetModel

    # Reason: create a fake preset record in memory.
    fake_preset = PresetModel(
        id="test-preset",
        name="Test Preset",
        prompt_md="My custom prompt text",
        notebooklm_prompt_template="General Finance",
        notebooklm_kind="slide_deck",
        outputs="pdf,markdown,notebooklm",
    )

    captured_id: str | None = None

    class FakeSession:
        def get(self, model, preset_id):
            nonlocal captured_id
            captured_id = preset_id
            return fake_preset
        def refresh(self, obj):
            pass

    with patch("streamdoc.core.fetch.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda s: FakeSession()
        mock_scope.return_value.__exit__ = lambda s, *a: None
        runner = PresetRunner("test-preset")
        loaded = runner._load_preset("test-preset")

    assert captured_id == "test-preset"
    assert loaded.notebooklm_prompt_template == "General Finance"
    assert loaded.prompt_md == "My custom prompt text"


# ---------------------------------------------------------------------------
# NotebookLM prompt resolution helpers
# ---------------------------------------------------------------------------


def test_notebooklm_prompt_args_template_mode():
    """When a template is selected, only prompt_template is returned."""
    from streamdoc.core.fetch import _notebooklm_prompt_args
    from streamdoc.models.preset import Preset as PresetModel

    preset = PresetModel(
        id="test",
        name="Test",
        prompt_md="custom prompt",
        notebooklm_prompt_template="General Finance",
    )
    args = _notebooklm_prompt_args(preset)
    assert args["prompt_template"] == "General Finance"
    assert args["custom_prompt"] is None


def test_notebooklm_prompt_args_custom_mode():
    """When no template is selected, custom_prompt is returned."""
    from streamdoc.core.fetch import _notebooklm_prompt_args
    from streamdoc.models.preset import Preset as PresetModel

    preset = PresetModel(
        id="test",
        name="Test",
        prompt_md="custom prompt",
        notebooklm_prompt_template=None,
    )
    args = _notebooklm_prompt_args(preset)
    assert args["prompt_template"] is None
    assert args["custom_prompt"] == "custom prompt"


def test_effective_prompt_for_preset_uses_template():
    """When a template is selected, the effective prompt is the template text."""
    from streamdoc.core.fetch import _effective_prompt_for_preset
    from streamdoc.models.preset import Preset as PresetModel

    preset = PresetModel(
        id="test",
        name="Test",
        prompt_md="custom prompt",
        notebooklm_prompt_template="financial_extraction",
    )
    prompt = _effective_prompt_for_preset(preset)
    assert "financial" in prompt.lower() or "metrics" in prompt.lower()


def test_effective_prompt_for_preset_falls_back_to_custom():
    """When no template is selected, the effective prompt is prompt_md."""
    from streamdoc.core.fetch import _effective_prompt_for_preset
    from streamdoc.models.preset import Preset as PresetModel

    preset = PresetModel(
        id="test",
        name="Test",
        prompt_md="custom prompt",
        notebooklm_prompt_template=None,
    )
    assert _effective_prompt_for_preset(preset) == "custom prompt"


# ---------------------------------------------------------------------------
# Regression: max_videos must not starve channels later in the list
# ---------------------------------------------------------------------------


def test_max_videos_is_per_channel_and_keeps_newest(monkeypatch):
    """max_videos limits each channel independently, keeping the newest videos."""
    from datetime import datetime, timezone, timedelta
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.core.channel import Channel
    from streamdoc.models.preset import Preset as PresetModel

    now = datetime.now(timezone.utc)
    queried_channels: list[str] = []
    selected_video_ids: list[str] = []

    def fake_list_videos(ch, *, playlist_mode=False, max_videos=None):
        queried_channels.append(ch.id)
        # Return three videos per channel with spaced-out dates, all within the
        # 24-hour lookback window. The oldest is 8 hours ago; the newest is now.
        return [
            VideoDataclass(
                id=f"{ch.id}-{i}",
                channel_id=ch.id,
                title=f"Video {ch.id} {i}",
                published_at=(now - timedelta(hours=8 - i * 3)).isoformat(),
            )
            for i in range(3)
        ]

    def fake_resolve_channel(channel_id: str) -> Channel:
        return Channel(id=channel_id, title=f"Channel {channel_id}")

    def fake_process_video(self, preset, ch, v, *args, **kwargs):
        selected_video_ids.append(v.id)
        return None

    monkeypatch.setattr("streamdoc.core.fetch._list_videos", fake_list_videos)
    monkeypatch.setattr("streamdoc.core.fetch._is_processed", lambda video_id: False)
    monkeypatch.setattr("streamdoc.core.fetch.session_scope", lambda: MagicMock())
    monkeypatch.setattr("streamdoc.api.sse.emit_progress", lambda *a, **kw: None)
    monkeypatch.setattr("streamdoc.core.fetch.resolve_channel", fake_resolve_channel)
    monkeypatch.setattr(PresetRunner, "_process_video", fake_process_video)

    fake_preset = PresetModel(
        id="test",
        name="Test",
        channel_list_id="A,B,C",
        lookback_hours=24,
        max_videos=2,
    )

    runner = PresetRunner("test")
    with patch("streamdoc.core.fetch.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda s: type(
            "S", (), {"get": lambda s, m, i: fake_preset, "refresh": lambda s, o: None}
        )()
        mock_scope.return_value.__exit__ = lambda s, *a: None
        with patch("streamdoc.core.fetch.complete_job"):
            with patch("streamdoc.core.fetch.run_cleanup"):
                runner.run_once()

    # All three channels should have been queried.
    assert sorted(queried_channels) == ["A", "B", "C"]
    # Each channel contributes exactly 2 videos (the newest ones), so 6 total.
    assert len(selected_video_ids) == 6
    # For each channel, the oldest video (index 0) should have been dropped.
    assert "A-0" not in selected_video_ids
    assert "B-0" not in selected_video_ids
    assert "C-0" not in selected_video_ids


# ---------------------------------------------------------------------------
# Integration: run_once passes correct prompt args to NotebookLM
# ---------------------------------------------------------------------------


def test_send_reports_uses_template_for_notebooklm_when_set(monkeypatch, tmp_path):
    """When notebooklm_prompt_template is set, only the template is passed."""
    from streamdoc.core.fetch import PresetRunner, RunArtifact
    from streamdoc.models.preset import Preset as PresetModel
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = PresetModel(
        id="test",
        name="Test",
        channel_list_id="",
        notebooklm_kind="slide_deck",
        notebooklm_prompt_template="General Finance",
        prompt_md="ignored custom prompt",
    )

    out_dir = tmp_path / "Test"
    out_dir.mkdir()

    runner = PresetRunner("test")
    artifact = RunArtifact(
        video_id="v1",
        md_path=out_dir / "v1.md",
        pdf_path=out_dir / "v1.pdf",
    )
    artifact.md_path.write_text("md")
    artifact.pdf_path.write_text("pdf")

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm") as mock_upload:
        mock_upload.return_value = type(
            "R", (), {
                "success": True,
                "notebook_id": "nb",
                "notebook_url": "url",
                "sources": [],
                "generated_content": [],
                "errors": [],
                "to_dict": lambda self: {},
            }
        )()
        runner._send_reports(fake_preset, [artifact], "job-1")

    assert mock_upload.called
    call_kwargs = mock_upload.call_args.kwargs
    assert call_kwargs["prompt_template"] == "General Finance"
    assert call_kwargs["custom_prompt"] is None


# ---------------------------------------------------------------------------
# Existing-PDF fallback guard: don't upload stale reports when downloads failed
# ---------------------------------------------------------------------------


def test_send_reports_does_not_upload_stale_pdfs_when_downloads_failed(monkeypatch, tmp_path):
    """When candidates_attempted > 0 and artifacts is empty, stale PDFs are NOT uploaded.

    Reason: if all downloads failed (bot detection, rate limit, etc.), the
    output directory may still contain PDFs from a previous successful run.
    Uploading those stale reports to NotebookLM would produce a presentation
    based on old content — misleading and wrong. The existing-PDF fallback
    must only trigger when candidates_attempted == 0 (all videos were already
    processed, none entered the processing phase).
    """
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.models.preset import Preset as PresetModel
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = PresetModel(
        id="test",
        name="StaleGuard",
        channel_list_id="",
        notebooklm_kind="slide_deck",
        notebooklm_prompt_template=None,
        prompt_md="prompt",
    )

    out_dir = tmp_path / "StaleGuard"
    out_dir.mkdir()
    # Reason: create stale PDFs from a previous run that should NOT be uploaded
    (out_dir / "old_video1.pdf").write_bytes(b"%PDF old")
    (out_dir / "old_video2.pdf").write_bytes(b"%PDF old")

    runner = PresetRunner("test")

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm") as mock_upload:
        # candidates_attempted=3 means 3 videos entered processing but all failed
        dest = runner._send_reports(
            fake_preset, [], "job-fail", candidates_attempted=3
        )

    # Reason: upload must NOT have been called — no stale reports uploaded
    assert not mock_upload.called, (
        "upload_to_notebooklm must NOT be called when all downloads failed"
    )
    assert "notebooklm" not in dest, (
        "destinations must not contain notebooklm when downloads failed"
    )


def test_send_reports_uploads_existing_pdfs_when_all_already_processed(monkeypatch, tmp_path):
    """When candidates_attempted == 0 and artifacts is empty, existing PDFs ARE uploaded.

    Reason: this is the intended use case for the existing-PDF fallback — the
    user re-runs a preset where all videos were already processed
    (skip_processed=True), specifically to upload the existing reports to
    NotebookLM. candidates_attempted == 0 means no videos entered processing.
    """
    from streamdoc.core.fetch import PresetRunner
    from streamdoc.models.preset import Preset as PresetModel
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "output_root", str(tmp_path))

    fake_preset = PresetModel(
        id="test",
        name="AlreadyProcessed",
        channel_list_id="",
        notebooklm_kind="slide_deck",
        notebooklm_prompt_template=None,
        prompt_md="prompt",
    )

    out_dir = tmp_path / "AlreadyProcessed"
    out_dir.mkdir()
    (out_dir / "video1.pdf").write_bytes(b"%PDF existing")
    (out_dir / "video2.pdf").write_bytes(b"%PDF existing")

    runner = PresetRunner("test")

    with patch("streamdoc.core.notebooklm_upload.upload_to_notebooklm") as mock_upload:
        mock_upload.return_value = type(
            "R", (), {
                "success": True,
                "notebook_id": "nb",
                "notebook_url": "url",
                "sources": [],
                "generated_content": [],
                "errors": [],
                "to_dict": lambda self: {},
            }
        )()
        # candidates_attempted=0 means all videos were already processed
        dest = runner._send_reports(
            fake_preset, [], "job-reupload", candidates_attempted=0
        )

    assert mock_upload.called, (
        "upload_to_notebooklm should be called to re-upload existing reports"
    )
    assert dest.get("notebooklm") == "success"
