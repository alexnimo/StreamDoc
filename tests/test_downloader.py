import pytest
from unittest.mock import MagicMock, patch

from streamdoc.config import settings
from streamdoc.core.downloader import (
    build_ydl_opts,
    build_common_args,
    classify_download_error,
    is_permanent_error,
    is_cookie_db_lock_error,
    DownloadResult,
)


def test_build_ydl_opts_respects_user_agent(monkeypatch):
    """The user-agent setting should be converted to http_headers."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", "StreamDoc/1.0")

    opts = build_ydl_opts()

    assert opts["http_headers"] == {"User-Agent": "StreamDoc/1.0"}


def test_build_ydl_opts_extra_args_override_user_agent(monkeypatch):
    """Extra raw args should win over the static user-agent setting."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_user_agent", "StaticAgent")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", "--user-agent ExtraAgent")

    def fake_parse_options(argv):
        # Reason: simulate the yt-dlp parser: default has no User-Agent,
        # the extra args string sets one.
        if not argv:
            return MagicMock(ydl_opts={"http_headers": {}})
        return MagicMock(ydl_opts={"http_headers": {"User-Agent": "ExtraAgent"}})

    with patch("yt_dlp.parse_options", side_effect=fake_parse_options):
        opts = build_ydl_opts()

    assert opts["http_headers"]["User-Agent"] == "ExtraAgent"


def test_build_ydl_opts_cookie_mode(monkeypatch, tmp_path):
    """Cookie mode should set cookiefile when the cookie jar exists."""
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("cookie data")

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookie")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookiejar_path", str(cookie_file))

    opts = build_ydl_opts()

    assert opts["cookiefile"] == str(cookie_file)


def test_build_ydl_opts_po_token_mode(monkeypatch):
    """PO-token mode should set the extractor args for the configured provider."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_pot_provider", "bgutil")
    monkeypatch.setattr(settings, "pot_provider_url", "http://127.0.0.1:4416")

    opts = build_ydl_opts()

    assert opts["extractor_args"]["youtube"]["pot_provider"] == ["bgutil"]
    assert opts["extractor_args"]["youtube"]["player_client"] == ["default", "web"]
    assert opts["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == ["http://127.0.0.1:4416"]


def test_build_ydl_opts_extra_args_merge_extractor_args(monkeypatch):
    """Extra --extractor-args should merge with the PO-token defaults."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_extra_args", "--extractor-args youtube:player_client=web")

    def fake_parse_options(argv):
        if not argv:
            return MagicMock(ydl_opts={"extractor_args": {}})
        return MagicMock(ydl_opts={"extractor_args": {"youtube": {"player_client": ["web"]}}})

    with patch("yt_dlp.parse_options", side_effect=fake_parse_options):
        opts = build_ydl_opts()

    # User override for player_client is preserved, pot_provider from mode is kept.
    assert opts["extractor_args"]["youtube"]["player_client"] == ["web"]
    assert opts["extractor_args"]["youtube"]["pot_provider"] == ["bgutil"]


def test_build_common_args_extra_args_wins_over_user_agent_setting(monkeypatch):
    """CLI user-agent should not duplicate when extra args already sets it."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_user_agent", "StaticAgent")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", "--user-agent ExtraAgent")

    args = build_common_args()

    user_agent_indices = [i for i, a in enumerate(args) if a == "--user-agent"]
    assert len(user_agent_indices) == 1


# ---------------------------------------------------------------------------
# cookies_from_browser bypass mode
# ---------------------------------------------------------------------------

def test_build_ydl_opts_cookies_from_browser_mode(monkeypatch):
    """cookies_from_browser mode should set cookiesfrombrowser tuple."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    opts = build_ydl_opts()

    assert opts["cookiesfrombrowser"] == ("chrome", None, None, None)


def test_build_ydl_opts_cookies_from_browser_with_profile(monkeypatch):
    """cookies_from_browser mode should include the profile when set."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "edge")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", "Profile 1")

    opts = build_ydl_opts()

    assert opts["cookiesfrombrowser"] == ("edge", "Profile 1", None, None)


def test_build_common_args_cookies_from_browser(monkeypatch):
    """CLI args should include --cookies-from-browser with the right browser."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "firefox")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    args = build_common_args()

    assert "--cookies-from-browser" in args
    idx = args.index("--cookies-from-browser")
    assert args[idx + 1] == "firefox"


def test_build_common_args_cookies_from_browser_with_profile(monkeypatch):
    """CLI args should include browser:profile format when profile is set."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", "Default")

    args = build_common_args()

    idx = args.index("--cookies-from-browser")
    assert args[idx + 1] == "chrome:Default"


# ---------------------------------------------------------------------------
# Download error classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stderr,expected", [
    ("Join this channel to get access to members-only content", "members_only"),
    ("This video is available to this channel's members on level: Billionaire", "members_only"),
    ("Sign in to confirm you're not a bot. Use --cookies-from-browser", "bot_detection"),
    ("Video unavailable. This video has been removed by the uploader", "private_deleted"),
    ("Private video", "private_deleted"),
    ("Some random network error", "other"),
    ("ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271", "cookie_db_locked"),
])
def test_classify_download_error(stderr, expected):
    """Error classification should match the expected category."""
    assert classify_download_error(stderr) == expected


def test_is_cookie_db_lock_error_detection():
    """is_cookie_db_lock_error should detect the Chrome cookie DB lock message."""
    assert is_cookie_db_lock_error("ERROR: Could not copy Chrome cookie database. See ...") is True
    assert is_cookie_db_lock_error("Could not copy Edge cookie database") is True
    assert is_cookie_db_lock_error("Some other error") is False
    assert is_cookie_db_lock_error("") is False


def test_is_permanent_error_members_only():
    """members_only should be a permanent error."""
    assert is_permanent_error("members_only") is True
    assert is_permanent_error("private_deleted") is True
    assert is_permanent_error("bot_detection") is False
    assert is_permanent_error("cookie_db_locked") is False
    assert is_permanent_error("other") is False


def test_download_result_dataclass():
    """DownloadResult should store path, error, and category."""
    ok = DownloadResult(path=__import__("pathlib").Path("/tmp/video.mp4"))
    assert ok.error_category == "ok"
    assert ok.error is None

    fail = DownloadResult(error="members-only", error_category="members_only")
    assert fail.path is None
    assert is_permanent_error(fail.error_category)


# ---------------------------------------------------------------------------
# bypass_mode_override (cookie DB lock fallback)
# ---------------------------------------------------------------------------

def test_build_common_args_bypass_mode_override(monkeypatch):
    """bypass_mode_override should replace the primary mode in CLI args."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    # Reason: with override="default", no --cookies-from-browser should appear
    args = build_common_args(bypass_mode_override="default")
    assert "--cookies-from-browser" not in args


def test_build_ydl_opts_bypass_mode_override(monkeypatch):
    """bypass_mode_override should replace the primary mode in ydl opts."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    opts = build_ydl_opts(bypass_mode_override="default")
    assert "cookiesfrombrowser" not in opts


def test_build_ydl_opts_bypass_mode_override_to_cookie(monkeypatch, tmp_path):
    """bypass_mode_override=cookie should set cookiefile, not browser cookies."""
    cookie_file = tmp_path / "youtube.txt"
    cookie_file.write_text("cookie data")

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)
    monkeypatch.setattr(settings, "yt_dlp_cookiejar_path", str(cookie_file))

    opts = build_ydl_opts(bypass_mode_override="cookie")
    assert opts["cookiefile"] == str(cookie_file)
    assert "cookiesfrombrowser" not in opts


# ---------------------------------------------------------------------------
# download() cookie DB lock fallback retry
# ---------------------------------------------------------------------------

def test_download_retries_with_fallback_on_cookie_db_lock(monkeypatch):
    """download() should retry with fallback mode when cookie DB is locked."""
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Reason: first call fails with cookie DB lock error
            return MagicMock(returncode=1, stderr="ERROR: Could not copy Chrome cookie database.", stdout="")
        # Reason: second call (fallback) succeeds
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", "%(id)s.%(ext)s")

    assert call_count["n"] == 2
    assert result.returncode == 0


def test_download_no_retry_without_fallback_mode(monkeypatch):
    """download() should not retry if no fallback mode is configured."""
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", None)
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        return MagicMock(returncode=1, stderr="ERROR: Could not copy Chrome cookie database.", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", "%(id)s.%(ext)s")

    assert call_count["n"] == 1
    assert result.returncode == 1


def test_download_no_retry_on_permanent_error(monkeypatch):
    """download() should not retry on permanent errors (e.g. members-only)."""
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        # Reason: members-only is a permanent error — retrying with a
        # different bypass mode will never help.
        return MagicMock(returncode=1, stderr="Join this channel to get access to members-only content", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", "%(id)s.%(ext)s")

    assert call_count["n"] == 1


def test_download_retries_with_fallback_on_bot_detection(monkeypatch):
    """download() should retry with fallback mode on bot detection errors.

    Reason: YouTube's bot detection is not uniform — some channels/videos get
    stricter challenges that the PO token alone cannot satisfy. The fallback
    to cookies_from_browser uses the operator's signed-in session and is far
    more resilient.
    """
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)
    monkeypatch.setattr(settings, "yt_dlp_pot_provider", "bgutil")
    monkeypatch.setattr(settings, "pot_provider_url", "http://127.0.0.1:4416")

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Reason: first call (po_token) fails with bot detection
            return MagicMock(returncode=1, stderr="Sign in to confirm you're not a bot", stdout="")
        # Reason: second call (fallback cookies_from_browser) succeeds
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", "%(id)s.%(ext)s")

    assert call_count["n"] == 2
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# dump_json() cookie DB lock fallback retry
# ---------------------------------------------------------------------------

def test_dump_json_retries_with_fallback_on_cookie_db_lock(monkeypatch):
    """dump_json should retry with fallback mode when cookie DB is locked."""
    import json as _json
    from streamdoc.core.downloader import dump_json

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MagicMock(returncode=1, stderr="ERROR: Could not copy Chrome cookie database.", stdout="")
        return MagicMock(returncode=0, stderr="", stdout=_json.dumps({"id": "UCtest", "title": "Test"}))

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        data = dump_json("https://youtube.com/channel/UCtest", flat_playlist=True, dump_single_json=True)

    assert call_count["n"] == 2
    assert data["id"] == "UCtest"


def test_dump_json_retries_with_fallback_on_bot_detection(monkeypatch):
    """dump_json should retry with fallback mode on bot detection errors."""
    import json as _json
    from streamdoc.core.downloader import dump_json

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "cookies_from_browser")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser", "chrome")
    monkeypatch.setattr(settings, "yt_dlp_cookies_browser_profile", None)
    monkeypatch.setattr(settings, "yt_dlp_pot_provider", "bgutil")
    monkeypatch.setattr(settings, "pot_provider_url", "http://127.0.0.1:4416")

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return MagicMock(returncode=1, stderr="Sign in to confirm you're not a bot", stdout="")
        return MagicMock(returncode=0, stderr="", stdout=_json.dumps({"id": "UCtest", "title": "Test"}))

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        data = dump_json("https://youtube.com/channel/UCtest", flat_playlist=True, dump_single_json=True)

    assert call_count["n"] == 2
    assert data["id"] == "UCtest"


# ---------------------------------------------------------------------------
# _should_fallback_retry classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stderr,expected", [
    ("Sign in to confirm you're not a bot", True),
    ("ERROR: Could not copy Chrome cookie database.", True),
    ("Rate limit exceeded. Too many requests (429)", True),
    ("Sign in to view this content", True),
    ("Join this channel to get access to members-only content", False),
    ("Private video", False),
    ("Video unavailable", False),
    ("Some random network error", False),
])
def test_should_fallback_retry(stderr, expected):
    """_should_fallback_retry should match transient/retriable categories only."""
    from streamdoc.core.downloader import _should_fallback_retry
    assert _should_fallback_retry(stderr) is expected
