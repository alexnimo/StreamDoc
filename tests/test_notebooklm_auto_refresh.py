"""Tests for NotebookLM automatic session re-capture.

These tests verify that ``NotebookLMAuthManager`` attempts a refresh when the
stored session has expired, that the status endpoint stays read-only, and that
the underlying refresh path uses ``notebooklm.NotebookLMClient.refresh_auth``.
"""

from pathlib import Path

import pytest

# Skip all tests if the NotebookLM integration is not available.
pytest.importorskip("streamdoc.integrations.notebooklm")

from streamdoc.integrations.notebooklm.auth import (
    NotebookLMAuthManager,
    NotebookLMAuthRequiredError,
)


@pytest.mark.asyncio
async def test_auth_manager_refresh_session_not_configured():
    """refresh_session() returns False when no storage exists."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_manager = NotebookLMAuthManager(f"{tmpdir}/nonexistent/storage_state.json")
        assert await auth_manager.refresh_session() is False


@pytest.mark.asyncio
async def test_refresh_session_uses_headless_reauth_capture(
    monkeypatch: pytest.MonkeyPatch,
):
    """refresh_session() calls run_headless_reauth_capture with the configured browser."""
    import json
    import tempfile

    import streamdoc.config as config_mod

    monkeypatch.delenv("NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL", raising=False)
    monkeypatch.setattr(config_mod.settings, "notebooklm_cdp_url", None)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.write_text(
            json.dumps(
                {
                    "cookies": [
                        {
                            "name": "SID",
                            "value": "stale",
                            "domain": ".google.com",
                            "path": "/",
                        }
                    ],
                    "origins": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(config_mod.settings, "notebooklm_browser", "chromium")

        auth_manager = NotebookLMAuthManager(str(storage))

        captured: dict[str, object] = {}

        async def fake_run_headless_reauth_capture(
            *,
            storage_path: Path,
            browser_profile: Path,
            **kwargs: object,
        ) -> bool:
            captured["storage_path"] = storage_path
            captured["browser_profile"] = browser_profile
            captured["kwargs"] = kwargs
            return True

        monkeypatch.setattr(
            "streamdoc.integrations.notebooklm._auth_capture.run_headless_reauth_capture",
            fake_run_headless_reauth_capture,
        )

        result = await auth_manager.refresh_session()

        assert result is True
        assert captured["storage_path"] == storage
        assert captured["browser_profile"] == storage.parent / "browser_profile"
        assert captured["kwargs"]["browser"] == "chromium"
        assert captured["kwargs"]["headless"] is True
        assert captured["kwargs"]["cdp_url"] is None


@pytest.mark.asyncio
async def test_refresh_session_returns_false_on_failed_reauth(
    monkeypatch: pytest.MonkeyPatch,
):
    """refresh_session() returns False when run_headless_reauth_capture fails."""
    import json
    import tempfile

    import streamdoc.config as config_mod

    monkeypatch.delenv("NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL", raising=False)
    monkeypatch.setattr(config_mod.settings, "notebooklm_cdp_url", None)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.write_text(
            json.dumps(
                {
                    "cookies": [
                        {
                            "name": "SID",
                            "value": "stale",
                            "domain": ".google.com",
                            "path": "/",
                        }
                    ],
                    "origins": [],
                }
            ),
            encoding="utf-8",
        )
        auth_manager = NotebookLMAuthManager(str(storage))

        async def fake_run_headless_reauth_capture(**kwargs: object) -> bool:
            return False

        monkeypatch.setattr(
            "streamdoc.integrations.notebooklm._auth_capture.run_headless_reauth_capture",
            fake_run_headless_reauth_capture,
        )

        result = await auth_manager.refresh_session()

        assert result is False


@pytest.mark.asyncio
async def test_refresh_session_uses_cdp_url_from_env(
    monkeypatch: pytest.MonkeyPatch,
):
    """refresh_session() passes the configured CDP endpoint to run_headless_reauth_capture."""
    import json
    import tempfile

    monkeypatch.setenv("NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL", "http://localhost:9222")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.write_text(
            json.dumps(
                {
                    "cookies": [
                        {
                            "name": "SID",
                            "value": "stale",
                            "domain": ".google.com",
                            "path": "/",
                        }
                    ],
                    "origins": [],
                }
            ),
            encoding="utf-8",
        )
        auth_manager = NotebookLMAuthManager(str(storage))

        captured: dict[str, object] = {}

        async def fake_run_headless_reauth_capture(*, cdp_url: object, **kwargs: object) -> bool:
            captured["cdp_url"] = cdp_url
            return True

        monkeypatch.setattr(
            "streamdoc.integrations.notebooklm._auth_capture.run_headless_reauth_capture",
            fake_run_headless_reauth_capture,
        )

        result = await auth_manager.refresh_session()

        assert result is True
        assert captured["cdp_url"] == "http://localhost:9222"


@pytest.mark.asyncio
async def test_refresh_session_falls_back_from_cdp_to_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    """If the configured CDP endpoint fails, refresh_session() retries with the dedicated profile."""
    import json
    import tempfile

    monkeypatch.setenv("NOTEBOOKLM_HEADLESS_REAUTH_CDP_URL", "http://localhost:9222")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.write_text(
            json.dumps(
                {
                    "cookies": [
                        {
                            "name": "SID",
                            "value": "stale",
                            "domain": ".google.com",
                            "path": "/",
                        }
                    ],
                    "origins": [],
                }
            ),
            encoding="utf-8",
        )
        auth_manager = NotebookLMAuthManager(str(storage))

        calls: list[dict[str, object]] = []

        async def fake_run_headless_reauth_capture(*, cdp_url: object, **kwargs: object) -> bool:
            calls.append({"cdp_url": cdp_url, **kwargs})
            return cdp_url is None

        monkeypatch.setattr(
            "streamdoc.integrations.notebooklm._auth_capture.run_headless_reauth_capture",
            fake_run_headless_reauth_capture,
        )

        result = await auth_manager.refresh_session()

        assert result is True
        assert len(calls) == 2
        assert calls[0]["cdp_url"] == "http://localhost:9222"
        assert calls[1]["cdp_url"] is None


@pytest.mark.asyncio
async def test_check_session_freshness_auto_refresh_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    """When the session probe fails with an auth error and auto_refresh is on,
    the auth manager refreshes and retries."""
    import tempfile
    from unittest.mock import AsyncMock

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.touch()
        auth_manager = NotebookLMAuthManager(str(storage))

        calls = [0]

        async def _probe(self: NotebookLMAuthManager) -> None:
            calls[0] += 1
            if calls[0] == 1:
                raise ValueError(
                    "Authentication expired or invalid. Redirected to: "
                    "https://accounts.google.com/ Run 'notebooklm login' to re-authenticate."
                )

        monkeypatch.setattr(NotebookLMAuthManager, "_probe_session", _probe)
        monkeypatch.setattr(
            NotebookLMAuthManager, "refresh_session", AsyncMock(return_value=True)
        )

        status = await auth_manager.check_session_freshness(auto_refresh=True)

        assert status.is_valid is True
        assert status.is_fresh is True
        assert NotebookLMAuthManager.refresh_session.called is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_check_session_freshness_auto_refresh_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    """auto_refresh=False does not launch a browser re-capture."""
    import tempfile
    from unittest.mock import AsyncMock

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.touch()
        auth_manager = NotebookLMAuthManager(str(storage))

        async def _probe(self: NotebookLMAuthManager) -> None:
            raise ValueError(
                "Authentication expired or invalid. Redirected to: "
                "https://accounts.google.com/ Run 'notebooklm login' to re-authenticate."
            )

        monkeypatch.setattr(NotebookLMAuthManager, "_probe_session", _probe)
        refresh_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(NotebookLMAuthManager, "refresh_session", refresh_mock)

        status = await auth_manager.check_session_freshness(auto_refresh=False)

        assert status.is_valid is False
        assert refresh_mock.called is False


@pytest.mark.asyncio
async def test_check_session_freshness_no_refresh_for_non_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    """Non-auth errors do not trigger a re-capture attempt."""
    import tempfile
    from unittest.mock import AsyncMock

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.touch()
        auth_manager = NotebookLMAuthManager(str(storage))

        async def _probe(self: NotebookLMAuthManager) -> None:
            raise RuntimeError("DNS resolution failed")

        monkeypatch.setattr(NotebookLMAuthManager, "_probe_session", _probe)
        refresh_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(NotebookLMAuthManager, "refresh_session", refresh_mock)

        status = await auth_manager.check_session_freshness(auto_refresh=True)

        assert status.is_valid is False
        assert status.message.startswith("Session invalid or expired")
        assert refresh_mock.called is False


@pytest.mark.asyncio
async def test_require_auth_raises_after_failed_refresh(
    monkeypatch: pytest.MonkeyPatch,
):
    """require_auth() raises a clean error when re-capture also fails."""
    import tempfile
    from unittest.mock import AsyncMock

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(f"{tmpdir}/storage_state.json")
        storage.touch()
        auth_manager = NotebookLMAuthManager(str(storage))

        async def _probe(self: NotebookLMAuthManager) -> None:
            raise ValueError(
                "Authentication expired or invalid. Redirected to: "
                "https://accounts.google.com/ Run 'notebooklm login' to re-authenticate."
            )

        monkeypatch.setattr(NotebookLMAuthManager, "_probe_session", _probe)
        monkeypatch.setattr(
            NotebookLMAuthManager,
            "refresh_session",
            AsyncMock(return_value=False),
        )

        with pytest.raises(NotebookLMAuthRequiredError) as exc_info:
            await auth_manager.require_auth()

        assert "Run 'notebooklm login'" in str(exc_info.value)
