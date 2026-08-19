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
    _is_http_403_error,
    _hls_format_selector,
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


# ---------------------------------------------------------------------------
# web_embedded bypass mode
# ---------------------------------------------------------------------------

def test_build_ydl_opts_web_embedded_mode(monkeypatch):
    """web_embedded mode should set player_client to web_embedded only."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "web_embedded")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)

    opts = build_ydl_opts()

    assert opts["extractor_args"]["youtube"]["player_client"] == ["web_embedded"]


def test_build_common_args_web_embedded_mode(monkeypatch):
    """CLI args should include --extractor-args with player_client=web_embedded."""
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "web_embedded")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "yt_dlp_user_agent", None)

    args = build_common_args()

    # Reason: --extractor-args is a flag+value pair; find the pair that
    # sets player_client=web_embedded.
    ea_indices = [i for i, a in enumerate(args) if a == "--extractor-args"]
    assert len(ea_indices) >= 1
    found = any(
        "player_client=web_embedded" in args[i + 1] for i in ea_indices
    )
    assert found, f"Expected player_client=web_embedded in args: {args}"


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
    # Reason: HTTP 403 is a transient PO-token/format issue, not permanent.
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", True),
    ("Join this channel to get access to members-only content", False),
    ("Private video", False),
    ("Video unavailable", False),
    ("Some random network error", False),
])
def test_should_fallback_retry(stderr, expected):
    """_should_fallback_retry should match transient/retriable categories only."""
    from streamdoc.core.downloader import _should_fallback_retry
    assert _should_fallback_retry(stderr) is expected


def test_get_fallback_bypass_modes_parses_comma_separated(monkeypatch):
    """_get_fallback_bypass_modes should parse comma-separated fallback chains."""
    from streamdoc.core.downloader import _get_fallback_bypass_modes

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "cookies_from_browser,cookie,default")
    modes = _get_fallback_bypass_modes()
    assert modes == ["cookies_from_browser", "cookie", "default"]


def test_get_fallback_bypass_modes_excludes_primary(monkeypatch):
    """_get_fallback_bypass_modes should exclude the primary mode from the chain."""
    from streamdoc.core.downloader import _get_fallback_bypass_modes

    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "po_token,cookies_from_browser")
    modes = _get_fallback_bypass_modes()
    assert modes == ["cookies_from_browser"]


def test_download_preserves_original_error_when_fallback_hits_cookie_lock(monkeypatch):
    """download() should return the original error, not cookie_db_locked, when
    the fallback fails with a cookie DB lock.

    Reason: when po_token fails with bot_detection and the fallback to
    cookies_from_browser hits the cookie DB lock, the user should see the
    bot_detection error (the real root cause), not the misleading
    cookie_db_locked error from the fallback attempt.
    """
    from streamdoc.core.downloader import download
    from unittest.mock import MagicMock

    monkeypatch.setattr(settings, "yt_dlp_bypass_chain", "")
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", "cookies_from_browser,default")
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
            # Reason: po_token fails with bot detection
            return MagicMock(returncode=1, stderr="Sign in to confirm you're not a bot", stdout="")
        if call_count["n"] == 2:
            # Reason: cookies_from_browser fallback hits cookie DB lock
            return MagicMock(returncode=1, stderr="ERROR: Could not copy Chrome cookie database.", stdout="")
        # Reason: default fallback also fails with bot detection
        return MagicMock(returncode=1, stderr="Sign in to confirm you're not a bot", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", "%(id)s.%(ext)s")

    # Reason: all 3 attempts made (po_token + 2 fallbacks)
    assert call_count["n"] == 3
    assert result.returncode == 1
    # Reason: the final error should be the bot_detection error, NOT
    # cookie_db_locked (which was just the fallback hitting Chrome's lock).
    from streamdoc.core.downloader import classify_download_error
    assert classify_download_error(result.stderr or "") == "bot_detection"


# ---------------------------------------------------------------------------
# HTTP 403 classification and HLS fallback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stderr,expected", [
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "http_403"),
    ("HTTP Error 403: Forbidden", "http_403"),
    ("403 Forbidden", "http_403"),
])
def test_classify_http_403(stderr, expected):
    """403 errors should be classified as http_403 (transient, HLS-retriable)."""
    assert classify_download_error(stderr) == expected


@pytest.mark.parametrize("stderr", [
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "403 Forbidden",
])
def test_is_http_403_error_true(stderr):
    """_is_http_403_error should detect 403 media download errors."""
    assert _is_http_403_error(stderr) is True


@pytest.mark.parametrize("stderr", [
    "Sign in to confirm you're not a bot",
    "Private video",
    "Could not copy Chrome cookie database",
    "Some random error",
])
def test_is_http_403_error_false(stderr):
    """_is_http_403_error should not match non-403 errors."""
    assert _is_http_403_error(stderr) is False


def test_hls_format_selector_with_resolution(monkeypatch):
    """_hls_format_selector should produce a height-filtered best selector."""
    monkeypatch.setattr(settings, "video_resolution", "720")
    assert _hls_format_selector() == "best[height<=720]/best"


def test_hls_format_selector_best(monkeypatch):
    """_hls_format_selector should handle the 'best' resolution setting."""
    monkeypatch.setattr(settings, "video_resolution", "best")
    sel = _hls_format_selector()
    assert "best" in sel


def test_download_hls_fallback_on_403(monkeypatch, tmp_path):
    """download() should retry with HLS fallback when primary fails with 403."""
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_chain", "")
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", None)
    monkeypatch.setattr(settings, "yt_dlp_hls_fallback_enabled", True)
    monkeypatch.setattr(settings, "yt_dlp_js_runtimes", "node")
    monkeypatch.setattr(settings, "yt_dlp_extra_args", None)
    monkeypatch.setattr(settings, "video_resolution", "1080")

    call_args: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_args.append(cmd)
        s = " ".join(cmd)
        if "web_safari" not in s:
            # Primary DASH attempt: 403
            return MagicMock(returncode=1, stderr="ERROR: unable to download video data: HTTP Error 403: Forbidden", stdout="")
        # HLS fallback: success
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", str(tmp_path / "%(title)s.%(ext)s"))

    assert result.returncode == 0
    # Reason: two calls — primary DASH + HLS fallback (no legacy fallback mode)
    assert len(call_args) == 2
    assert "web_safari" in " ".join(call_args[1])


def test_download_hls_fallback_disabled(monkeypatch, tmp_path):
    """download() should NOT retry with HLS when the setting is disabled."""
    from streamdoc.core.downloader import download

    monkeypatch.setattr(settings, "yt_dlp_bypass_chain", "")
    monkeypatch.setattr(settings, "yt_dlp_bypass_mode", "default")
    monkeypatch.setattr(settings, "yt_dlp_bypass_fallback_mode", None)
    monkeypatch.setattr(settings, "yt_dlp_hls_fallback_enabled", False)

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        return MagicMock(returncode=1, stderr="ERROR: unable to download video data: HTTP Error 403: Forbidden", stdout="")

    with patch("streamdoc.core.downloader._run", side_effect=fake_run), \
         patch("streamdoc.core.downloader._yt_dlp_binary", return_value="yt-dlp"):
        result = download("https://youtube.com/watch?v=test", str(tmp_path / "%(title)s.%(ext)s"))

    assert result.returncode == 1
    assert call_count["n"] == 1
