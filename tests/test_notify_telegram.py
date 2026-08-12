"""Tests for the POR-27 T4 Telegram notifier backend.

These tests verify the env-gated notifier subsystem introduced in T4:
* ``notify_run_success`` is silent when Telegram is not configured.
* When configured, it performs exactly one POST to the Telegram Bot API.
* HTTP errors are swallowed and logged; notification failures never raise.
* The ``TelegramNotifier`` constructor rejects one-sided credentials.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Reason: these tests are fully mocked; no marker is needed. They run
# cleanly under the default `pytest` invocation AND under
# `pytest -m "not live"` (the project's standard non-live lane) because
# the project only registers a `live` marker — there is no `not_live`.


def _ok_response() -> MagicMock:
    """Return a fake urlopen response that behaves as a context manager."""
    resp = MagicMock()
    resp.status = 200
    resp.getcode.return_value = 200
    resp.read.return_value = b'{"ok":true}'
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_no_creds_returns_false_silently() -> None:
    """With no env vars set, notify_run_success returns False and makes no HTTP call."""
    from streamdoc.core.notify import notify_run_success

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = notify_run_success("Daily", None, None)

    assert result is False
    mock_urlopen.assert_not_called()


def test_with_creds_sends_exactly_one_post() -> None:
    """With Telegram enabled + creds set, one POST is sent to Telegram."""
    from streamdoc.core.notify import notify_run_success

    fake_settings = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token="123:abc",
        notify_telegram_chat_id="42",
    )

    with patch("streamdoc.core.notify.settings", fake_settings):
        with patch("urllib.request.urlopen", return_value=_ok_response()) as mock_urlopen:
            result = notify_run_success(
                "Daily",
                "https://here.now/x",
                "/tmp/x.html",
            )

    assert result is True
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert isinstance(req, urllib.request.Request)
    assert req.full_url == "https://api.telegram.org/bot123:abc/sendMessage"
    body = json.loads(req.data)
    assert body["chat_id"] == "42"
    assert body["parse_mode"] == "MarkdownV2"
    assert "Daily" in body["text"]
    # The URL dots are escaped for MarkdownV2.
    assert "https://here\\.now/x" in body["text"]


def test_400_response_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    """A Telegram 400 response is swallowed and returns False."""
    from streamdoc.core.notify import TelegramNotifier

    notifier = TelegramNotifier("123:abc", "42")

    def _raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.telegram.org/bot123:abc/sendMessage",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"ok":false,"description":"bad chat id"}'),
        )

    with patch("urllib.request.urlopen", side_effect=_raise_http_error):
        with caplog.at_level("WARNING"):
            result = notifier.notify_success("hello", {})

    assert result is False
    assert "400" in caplog.text


def test_get_notifier_returns_none_when_disabled() -> None:
    """When Telegram is disabled, get_notifier returns None even if creds are present."""
    from streamdoc.core.notify import get_notifier

    fake_settings = SimpleNamespace(
        notify_telegram_enabled=False,
        notify_telegram_bot_token="x",
        notify_telegram_chat_id="y",
    )
    with patch("streamdoc.core.notify.settings", fake_settings):
        assert get_notifier() is None


def test_get_notifier_returns_none_with_info_log_when_enabled_but_missing_creds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Enabled but missing creds returns None and logs an INFO message."""
    from streamdoc.core.notify import get_notifier

    fake_settings = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token=None,
        notify_telegram_chat_id=None,
    )
    with patch("streamdoc.core.notify.settings", fake_settings):
        with caplog.at_level("INFO"):
            assert get_notifier() is None

    assert "notify_enabled but telegram creds missing" in caplog.text


def test_get_notifier_returns_telegram_when_fully_configured() -> None:
    """When enabled and fully configured, get_notifier returns a TelegramNotifier."""
    from streamdoc.core.notify import TelegramNotifier, get_notifier

    fake_settings = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token="123:abc",
        notify_telegram_chat_id="42",
    )
    with patch("streamdoc.core.notify.settings", fake_settings):
        notifier = get_notifier()

    assert isinstance(notifier, TelegramNotifier)
    assert notifier.bot_token == "123:abc"
    assert notifier.chat_id == "42"


def test_telegram_constructor_rejects_one_sided_creds() -> None:
    """Exactly one of token/chat_id set raises ValueError; both or neither are fine."""
    from streamdoc.core.notify import TelegramNotifier

    with pytest.raises(ValueError):
        TelegramNotifier("token", None)
    with pytest.raises(ValueError):
        TelegramNotifier(None, "42")

    # Both None is an intentional no-op.
    no_op = TelegramNotifier(None, None)
    assert no_op.bot_token is None
    assert no_op.chat_id is None

    # Both set is a normal instance.
    full = TelegramNotifier("token", "42")
    assert full.bot_token == "token"
    assert full.chat_id == "42"


def test_markdown_v2_escape_covers_specials() -> None:
    """Reserved MarkdownV2 characters are escaped correctly."""
    from streamdoc.core.notify import _escape_markdown_v2

    assert _escape_markdown_v2("hello.world") == "hello\\.world"
    assert _escape_markdown_v2("a_b*c[d]") == "a\\_b\\*c\\[d\\]"
    assert _escape_markdown_v2("a~b") == "a\\~b"
    assert _escape_markdown_v2("a>b") == "a\\>b"
    assert _escape_markdown_v2("a+b") == "a\\+b"


def test_notify_run_success_returns_false_when_notifier_unconfigured() -> None:
    """notify_run_success returns False when no notifier is configured."""
    from streamdoc.core.notify import notify_run_success

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = notify_run_success("Daily", "https://x", "/a")

    assert result is False
    mock_urlopen.assert_not_called()


class _BrokenNotifier:
    """Fake notifier that always raises, used to test the outer guard."""

    def notify_success(self, message: str, context: dict) -> bool:
        raise RuntimeError("boom")


def test_notify_run_success_swallows_programmer_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even if get_notifier returns a broken notifier, notify_run_success does not raise."""
    from streamdoc.core.notify import notify_run_success

    with patch("streamdoc.core.notify.get_notifier", return_value=_BrokenNotifier()):
        with caplog.at_level("WARNING"):
            result = notify_run_success("Daily", "https://x", "/a")

    assert result is False
    assert "boom" in caplog.text


# ---------------------------------------------------------------------------
# T6 spec-named tests (added alongside the existing T4 tests)
# ---------------------------------------------------------------------------
#
# Reason: the T6 acceptance criteria name four tests with specific
# names. The existing T4 tests cover the same scenarios but with
# different names. We add the spec-named variants here (without
# removing the T4 ones) so both the T4 and T6 acceptance criteria
# are literally satisfied.

def test_no_env_returns_false_silently() -> None:
    """Spec-named: notify_run_success returns False when notify env is off (no network)."""
    from streamdoc.core.notify import notify_run_success

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = notify_run_success("Daily", None, None)

    assert result is False
    mock_urlopen.assert_not_called()


def test_success_post() -> None:
    """Spec-named: when configured, exactly one POST is sent to the Telegram Bot API."""
    from streamdoc.core.notify import notify_run_success

    fake_settings = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token="123:abc",
        notify_telegram_chat_id="42",
    )

    resp = MagicMock()
    resp.status = 200
    resp.getcode.return_value = 200
    resp.read.return_value = b'{"ok":true}'
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False

    with patch("streamdoc.core.notify.settings", fake_settings):
        with patch("urllib.request.urlopen", return_value=resp) as mock_urlopen:
            result = notify_run_success(
                "Daily",
                "https://here.now/x",
                "/tmp/x.html",
            )

    assert result is True
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert isinstance(req, urllib.request.Request)
    assert req.full_url == "https://api.telegram.org/bot123:abc/sendMessage"
    body = json.loads(req.data)
    assert body["chat_id"] == "42"
    assert body["parse_mode"] == "MarkdownV2"
    assert "Daily" in body["text"]
    # Telegram MarkdownV2 requires dots in URLs to be escaped.
    assert "https://here\\.now/x" in body["text"]


def test_telegram_400_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    """Spec-named: a Telegram 400 response is swallowed; returns False (no raise)."""
    from streamdoc.core.notify import TelegramNotifier

    notifier = TelegramNotifier("123:abc", "42")

    def _raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.telegram.org/bot123:abc/sendMessage",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"ok":false,"description":"bad chat id"}'),
        )

    with patch("urllib.request.urlopen", side_effect=_raise_http_error):
        with caplog.at_level("WARNING"):
            result = notifier.notify_success("hello", {})

    assert result is False
    # The 400 must be surfaced in the logs so the operator can debug.
    assert "400" in caplog.text


def test_missing_one_credential_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    """Spec-named: get_notifier returns None when exactly one credential is set."""
    from streamdoc.core.notify import get_notifier

    # Bot token set but chat_id is None.
    fake_settings = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token="123:abc",
        notify_telegram_chat_id=None,
    )
    with patch("streamdoc.core.notify.settings", fake_settings):
        with caplog.at_level("INFO"):
            assert get_notifier() is None

    # Chat id set but bot token is None.
    fake_settings2 = SimpleNamespace(
        notify_telegram_enabled=True,
        notify_telegram_bot_token=None,
        notify_telegram_chat_id="42",
    )
    with patch("streamdoc.core.notify.settings", fake_settings2):
        with caplog.at_level("INFO"):
            assert get_notifier() is None
