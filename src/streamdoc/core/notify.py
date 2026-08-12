"""Pluggable, env-gated notifier subsystem.

Version 1 ships a Telegram backend that uses only the stdlib
``urllib.request``. The public surface is intentionally small:

* ``get_notifier()`` resolves a notifier from ``settings``.
* ``notify_run_success(...)`` builds a user-facing message and dispatches it.
* ``Notifier`` / ``TelegramNotifier`` are the concrete backend classes.

Notifications are best-effort: a failure to notify MUST NOT fail the
preset run that triggered it.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from streamdoc.config import settings

logger = logging.getLogger(__name__)


# Telegram MarkdownV2 escape table.
# Reason: per Telegram docs, these 18 characters must be escaped with a
# leading backslash when parse_mode == "MarkdownV2".
_MARKDOWN_V2_SPECIALS = "_*[]()~`>#+-=|{}.!"
_MARKDOWN_V2_ESCAPE = str.maketrans({c: f"\\{c}" for c in _MARKDOWN_V2_SPECIALS})


class Notifier:
    """Base notifier. Subclasses override ``notify_success``."""

    def notify_success(self, message: str, context: dict[str, Any]) -> bool:
        """Dispatch a success notification.

        Args:
            message: Pre-rendered message text.
            context: Structured fields for backends that need them.

        Returns:
            True when the notification was dispatched (or intentionally
            skipped), False when it failed but did not raise.
        """
        return True


class TelegramNotifier(Notifier):
    """Send notifications via the Telegram Bot API using stdlib only."""

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the notifier.

        Args:
            bot_token: Telegram bot token, or None for no-op.
            chat_id: Target chat id, or None for no-op.
            timeout: Request timeout in seconds.

        Raises:
            ValueError: When exactly one of ``bot_token``/``chat_id`` is
                provided. Both None is explicitly allowed so callers can
                always construct a notifier even when Telegram is not
                configured.
        """
        # Reason: both-None is a valid no-op configuration. This lets the
        # factory always return a Notifier when Telegram is disabled,
        # simplifying call sites.
        if (bot_token is None) != (chat_id is None):
            raise ValueError(
                "Telegram notifier requires both bot_token and chat_id to be set, or neither"
            )
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def notify_success(self, message: str, context: dict[str, Any]) -> bool:
        """Send a MarkdownV2 message via the Telegram Bot API.

        Args:
            message: Pre-rendered, already-escaped message text.
            context: Structured fields (unused by Telegram but part of
                the shared contract).

        Returns:
            True on HTTP 200, False on any failure. Never raises.
        """
        # Reason: both-None constructor means this instance is a no-op.
        if self.bot_token is None or self.chat_id is None:
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                # Reason: the spec only requires HTTP 200 as the success
                # signal. Parsing Telegram's ``result.ok`` adds a failure
                # mode we do not need.
                return bool(resp.status == 200)
        except urllib.error.HTTPError as exc:
            logger.warning(
                "Telegram notification failed (HTTP %s): %s",
                exc.code,
                exc.reason,
            )
        except urllib.error.URLError as exc:
            logger.warning("Telegram notification failed (URL error): %s", exc.reason)
        except TimeoutError:
            logger.warning("Telegram notification timed out after %.1fs", self.timeout)
        except Exception as exc:
            # Reason: catch-all keeps notification failures from bubbling.
            logger.warning("Telegram notification failed: %s", exc)
        return False


def _escape_markdown_v2(text: str) -> str:
    """Escape characters reserved by Telegram MarkdownV2.

    Args:
        text: Raw text to escape.

    Returns:
        Text with reserved characters prefixed by a backslash.
    """
    return text.translate(_MARKDOWN_V2_ESCAPE)


def get_notifier() -> Notifier | None:
    """Resolve a notifier from application settings.

    Returns:
        A configured ``Notifier`` instance, or ``None`` when notifications
        are disabled or incompletely configured.
    """
    # Reason: spec text used ``notify_enabled``/``telegram_*``; T1 shipped
    # ``notify_telegram_*``. Keep those names to avoid invalidating the
    # .env.example and the frontend SettingsPage wiring.
    enabled = getattr(settings, "notify_telegram_enabled", False)
    token = getattr(settings, "notify_telegram_bot_token", None)
    chat_id = getattr(settings, "notify_telegram_chat_id", None)

    if not enabled:
        return None

    if token and chat_id:
        return TelegramNotifier(bot_token=token, chat_id=chat_id)

    # Reason: enabled but incomplete configuration is worth surfacing in
    # logs so operators can debug why notifications are silent.
    logger.info("notify_enabled but telegram creds missing")
    return None


def notify_run_success(
    preset_name: str,
    herenow_url: str | None,
    artifact_path: str | None,
) -> bool:
    """Build and dispatch a success notification for a completed preset run.

    Args:
        preset_name: Display name of the preset that finished.
        herenow_url: Public URL for the generated artifact, if any.
        artifact_path: Local filesystem path to the artifact, if any.

    Returns:
        True if a notification was sent (or skipped because no notifier
        is configured). False if dispatch failed but did not raise.
    """
    # Reason: escape the fully assembled message after substitution so
    # both the hard-coded punctuation and any user-supplied content in
    # preset_name / URLs are safe for Telegram MarkdownV2.
    raw = (
        f"*StreamDoc* — preset `{preset_name}` generated successfully.\n"
        f"Artifact: {artifact_path or '(none)'}\n"
        f"here.now: {herenow_url or '(none)'}"
    )
    message = _escape_markdown_v2(raw)

    context = {
        "preset_name": preset_name,
        "herenow_url": herenow_url,
        "artifact_path": artifact_path,
    }

    try:
        notifier = get_notifier()
        if notifier is None:
            # Reason: no notifier configured is a non-error condition.
            return False
        return notifier.notify_success(message, context)
    except Exception as exc:
        # Reason: belt-and-suspenders. Even a future subclass that forgets
        # to swallow its own errors cannot fail the preset run.
        logger.warning("notify_run_success failed: %s", exc)
        return False
