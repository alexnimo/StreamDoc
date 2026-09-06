"""Background session keepalive for NotebookLM.

notebooklm-py 0.8.0+ replaced the legacy ``NOTEBOOKLM_REFRESH_CMD`` mechanism
with explicit, typed headless re-auth. StreamDoc now opts in to that behaviour
by setting ``NOTEBOOKLM_HEADLESS_REAUTH=1`` and by holding a long-lived
:class:`notebooklm.NotebookLMClient` open with ``keepalive`` enabled. The
client's internal background task POSTs to ``accounts.google.com/RotateCookies``
on the configured interval, which elicits fresh ``__Secure-1PSIDTS`` cookies so
the session stays warm. If the cookies die between ticks, the headless re-auth
layer silently re-mints them from the persistent browser profile.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from streamdoc.config import settings

if TYPE_CHECKING:
    from streamdoc.integrations.notebooklm.auth import NotebookLMAuthManager

logger = logging.getLogger(__name__)

# notebooklm-py 0.8.0+ uses this env var to gate mid-RPC layer-3 headless re-auth.
NOTEBOOKLM_HEADLESS_REAUTH_ENV = "NOTEBOOKLM_HEADLESS_REAUTH"
NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL_ENV = "NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL"
NOTEBOOKLM_LOG_LEVEL_ENV = "NOTEBOOKLM_LOG_LEVEL"


def configure_refresh_cmd(auth_manager: NotebookLMAuthManager) -> None:
    """Opt in to notebooklm-py's built-in headless re-auth.

    The previous ``NOTEBOOKLM_REFRESH_CMD`` hook was removed upstream in 0.8.0.
    This function keeps the same call signature for StreamDoc callers but now
    sets ``NOTEBOOKLM_HEADLESS_REAUTH=1`` so the upstream auth cascade can
    re-mint cookies automatically. When a Chrome DevTools endpoint is configured,
    it is also exported as ``NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL`` so the upstream
    L3 recovery can attach to the operator's live Chrome instead of the dedicated
    ``browser_profile``.

    Args:
        auth_manager: The auth manager instance.
    """
    try:
        os.environ[NOTEBOOKLM_HEADLESS_REAUTH_ENV] = "1"
        logger.debug("Set %s=1 for built-in headless re-auth", NOTEBOOKLM_HEADLESS_REAUTH_ENV)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to configure headless re-auth env: %s", exc)

    cdp_url = settings.notebooklm_cdp_url
    try:
        if cdp_url:
            os.environ[NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL_ENV] = cdp_url
            logger.info("Set %s=%s", NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL_ENV, cdp_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to configure headless re-auth CDP env: %s", exc)

    # Reason: notebooklm-py reads NOTEBOOKLM_LOG_LEVEL at import time; set it
    # from the StreamDoc setting before any notebooklm module is first imported
    # so the operator can enable DEBUG output without leaking it into the shell.
    if NOTEBOOKLM_LOG_LEVEL_ENV not in os.environ:
        try:
            os.environ[NOTEBOOKLM_LOG_LEVEL_ENV] = settings.notebooklm_log_level
            logger.debug("Set %s=%s", NOTEBOOKLM_LOG_LEVEL_ENV, settings.notebooklm_log_level)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to configure notebooklm log level: %s", exc)


async def keepalive_loop(
    auth_manager: NotebookLMAuthManager,
    interval_minutes: float = 30.0,
) -> None:
    """Hold a long-lived NotebookLM client open to keep the session warm.

    The client runs an internal background task that rotates the ``PSIDTS``
    cookies on the configured interval. Keeping the client open in a dedicated
    background task means the rotation keeps running even when no request is
    actively using a client context.

    If the initial client open fails because the stored session has expired,
    the loop attempts one headless re-capture from the persistent browser
    profile before giving up for this interval.

    Args:
        auth_manager: The auth manager instance.
        interval_minutes: Minutes between keepalive rotations. Converted to
            seconds and passed to :class:`notebooklm.NotebookLMClient`.
    """
    from notebooklm import NotebookLMClient

    from streamdoc.integrations.notebooklm.auth import _is_auth_error

    configure_refresh_cmd(auth_manager)

    if not auth_manager.is_configured():
        logger.info("NotebookLM not configured; keepalive loop idle")
        return

    storage_path = auth_manager.get_storage_path()
    interval_seconds = max(interval_minutes * 60, 60.0)

    while True:
        ctx = None
        try:
            # Reason: allow_headless=True is required in notebooklm-py 0.8.2+
            # for the transport layer to permit mid-RPC headless re-auth when
            # cookies expire. Without it, session_auth.py gates off the L3
            # recovery path at the WebSessionAuth.refresh() level (line 74)
            # even when NOTEBOOKLM_HEADLESS_REAUTH=1 is set, because the env
            # var is only checked as a secondary gate inside the headless
            # reauth function itself — the transport layer never reaches it.
            ctx = NotebookLMClient.from_storage(
                storage_path,
                keepalive=interval_seconds,
                keepalive_min_interval=60.0,
                allow_headless=True,
            )
            await ctx.__aenter__()
            logger.info(
                "NotebookLM keepalive client started (interval: %.1fs)", interval_seconds
            )
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info("NotebookLM keepalive task cancelled")
                raise
            finally:
                await ctx.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NotebookLM keepalive client failed: %s", exc)
            if _is_auth_error(exc):
                logger.info("NotebookLM keepalive attempting headless re-capture")
                try:
                    refreshed = await auth_manager.refresh_session()
                except Exception as refresh_exc:  # noqa: BLE001
                    logger.warning("NotebookLM keepalive re-capture failed: %s", refresh_exc)
                    refreshed = False
                if refreshed:
                    logger.info("NotebookLM keepalive re-capture succeeded; retrying client open")
                    continue
            if ctx is not None:
                try:
                    await ctx.__aexit__(type(exc), exc, None)
                except Exception as close_exc:  # noqa: BLE001
                    logger.debug("NotebookLM keepalive close failed: %s", close_exc)
            logger.warning(
                "NotebookLM keepalive sleeping %.1fs before retry", interval_seconds
            )
            await asyncio.sleep(interval_seconds)
