"""Tests for the PO Token provider container lifecycle management."""
from __future__ import annotations

import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from streamdoc.core import pot_provider
from streamdoc.core.pot_provider import (
    PotProviderStatus,
    ensure_pot_provider,
    get_effective_bypass_mode,
    get_pot_provider_status,
    is_docker_available,
    is_pot_server_reachable,
    shutdown_pot_provider,
    stop_pot_container,
)


# ---------------------------------------------------------------------------
# is_docker_available
# ---------------------------------------------------------------------------

def test_is_docker_available_true(monkeypatch):
    """Docker is available when `docker info` succeeds."""
    fake_result = MagicMock(returncode=0, stdout="Server Version: 27.0", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
    assert is_docker_available() is True


def test_is_docker_available_false_on_nonzero(monkeypatch):
    """Docker is not available when `docker info` returns non-zero."""
    fake_result = MagicMock(returncode=1, stdout="", stderr="docker not found")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)
    assert is_docker_available() is False


def test_is_docker_available_false_on_filenotfound(monkeypatch):
    """Docker is not available when the docker binary is missing."""
    def raise_fnf(*a, **kw):
        raise FileNotFoundError("docker not found")
    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert is_docker_available() is False


def test_is_docker_available_false_on_timeout(monkeypatch):
    """Docker is not available when `docker info` times out."""
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=10)
    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert is_docker_available() is False


# ---------------------------------------------------------------------------
# is_pot_server_reachable
# ---------------------------------------------------------------------------

def test_is_pot_server_reachable_true(monkeypatch):
    """Server is reachable when TCP connect succeeds."""
    fake_socket = MagicMock()
    fake_socket.__enter__ = MagicMock(return_value=fake_socket)
    fake_socket.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: fake_socket)
    assert is_pot_server_reachable("http://127.0.0.1:4416") is True


def test_is_pot_server_reachable_false_on_refused(monkeypatch):
    """Server is not reachable when connection is refused."""
    def raise_refused(*a, **kw):
        raise ConnectionRefusedError("Connection refused")
    monkeypatch.setattr(socket, "create_connection", raise_refused)
    assert is_pot_server_reachable("http://127.0.0.1:4416") is False


def test_is_pot_server_reachable_uses_settings_default(monkeypatch):
    """When no URL is passed, uses settings.pot_provider_url."""
    fake_socket = MagicMock()
    fake_socket.__enter__ = MagicMock(return_value=fake_socket)
    fake_socket.__exit__ = MagicMock(return_value=False)
    captured_addr = []

    def capture(addr, timeout):
        captured_addr.append(addr)
        return fake_socket

    monkeypatch.setattr(socket, "create_connection", capture)
    monkeypatch.setattr(pot_provider.settings, "pot_provider_url", "http://localhost:9999")
    is_pot_server_reachable()
    assert captured_addr[0] == ("localhost", 9999)


# ---------------------------------------------------------------------------
# get_effective_bypass_mode
# ---------------------------------------------------------------------------

def test_get_effective_bypass_mode_defaults_to_settings(monkeypatch):
    """When no effective mode is set, falls back to settings."""
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "cookie")
    assert get_effective_bypass_mode() == "cookie"


def test_get_effective_bypass_mode_returns_set_mode(monkeypatch):
    """When _effective_bypass_mode is set, returns it over settings.

    Reason: the self-healing logic in get_effective_bypass_mode() re-checks
    POT reachability when the cached mode is a fallback and the configured
    mode is po_token. We mock is_pot_server_reachable to return False so the
    cached fallback mode is preserved (simulating the POT server still being
    unavailable).
    """
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    # Reason: reset the revalidation throttle so the check actually runs
    monkeypatch.setattr(pot_provider, "_last_revalidation_ts", 0.0)
    pot_provider._effective_bypass_mode = "default"
    try:
        assert get_effective_bypass_mode() == "default"
    finally:
        pot_provider._effective_bypass_mode = None
        pot_provider._last_revalidation_ts = 0.0


def test_get_effective_bypass_mode_self_heals_when_pot_becomes_reachable(monkeypatch):
    """When the cached mode is a fallback but POT is now reachable, upgrade to po_token.

    Reason: this is the core self-healing fix. If the server cached a fallback
    mode at startup (because the POT container wasn't running yet), but the
    container is now reachable, get_effective_bypass_mode() should upgrade the
    effective mode back to po_token so subsequent downloads use the PO token.
    """
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: True)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(pot_provider, "_last_revalidation_ts", 0.0)
    pot_provider._effective_bypass_mode = "cookies_from_browser"
    try:
        mode = get_effective_bypass_mode()
        assert mode == "po_token", f"Expected self-heal to po_token, got {mode}"
        assert get_effective_bypass_mode() == "po_token"
    finally:
        pot_provider._effective_bypass_mode = None
        pot_provider._last_revalidation_ts = 0.0


def test_get_effective_bypass_mode_does_not_self_heal_when_configured_not_po_token(monkeypatch):
    """When the configured mode is not po_token, the cached mode is returned as-is.

    Reason: self-healing only applies when the user configured po_token but we
    cached a fallback. If the user explicitly configured a non-po_token mode
    (e.g. cookie), the cached value should not be overridden.
    """
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: True)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "cookie")
    pot_provider._effective_bypass_mode = "default"
    try:
        assert get_effective_bypass_mode() == "default"
    finally:
        pot_provider._effective_bypass_mode = None


def test_get_effective_bypass_mode_throttles_revalidation(monkeypatch):
    """Re-validation is throttled — a second call within the interval skips the probe.

    Reason: to avoid hammering the POT server with TCP probes on every yt-dlp
    call, re-validation only happens once per _REVALIDATION_INTERVAL_S seconds.
    """
    probe_count = [0]

    def counting_probe(url=None, timeout=2.0):
        probe_count[0] += 1
        return False

    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", counting_probe)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    pot_provider._effective_bypass_mode = "cookies_from_browser"
    try:
        # First call triggers a probe
        get_effective_bypass_mode()
        assert probe_count[0] == 1
        # Second call within the throttle interval should NOT probe
        get_effective_bypass_mode()
        assert probe_count[0] == 1, "Second call within interval should not re-probe"
    finally:
        pot_provider._effective_bypass_mode = None
        pot_provider._last_revalidation_ts = 0.0


# ---------------------------------------------------------------------------
# ensure_pot_provider — already running
# ---------------------------------------------------------------------------

def test_ensure_pot_provider_already_running(monkeypatch):
    """When the server is already reachable, returns ALREADY_RUNNING."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: True)
    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.ALREADY_RUNNING
    assert result.effective_bypass_mode == "po_token"
    assert get_effective_bypass_mode() == "po_token"


# ---------------------------------------------------------------------------
# ensure_pot_provider — Docker not available (fallback)
# ---------------------------------------------------------------------------

def test_ensure_pot_provider_fallback_no_docker(monkeypatch):
    """When Docker is not available, falls back to the configured fallback mode."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_fallback_mode", "cookie")

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.FALLBACK
    assert result.effective_bypass_mode == "cookie"
    assert get_effective_bypass_mode() == "cookie"


def test_ensure_pot_provider_fallback_defaults_to_cookies_from_browser(monkeypatch):
    """When no fallback mode is configured, defaults to cookies_from_browser."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_fallback_mode", None)

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.FALLBACK
    assert result.effective_bypass_mode == "cookies_from_browser"


# ---------------------------------------------------------------------------
# ensure_pot_provider — Docker available, container starts
# ---------------------------------------------------------------------------

def test_ensure_pot_provider_starts_container(monkeypatch):
    """When Docker is available and server isn't running, starts the container."""
    # Server not reachable initially, then becomes reachable after start
    reachability = [False]

    def fake_reachable(url=None, timeout=2.0):
        return reachability[0]

    def fake_start():
        reachability[0] = True
        return True

    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", fake_reachable)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "start_pot_container", fake_start)
    monkeypatch.setattr(pot_provider, "_wait_for_server", lambda timeout=30.0, interval=1.0: True)

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.STARTED
    assert result.effective_bypass_mode == "po_token"
    assert get_effective_bypass_mode() == "po_token"
    # We started it, so we should stop it on shutdown
    assert pot_provider._we_started_container is True


def test_ensure_pot_provider_start_fails_falls_back(monkeypatch):
    """When container start fails, falls back to the fallback mode."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "start_pot_container", lambda: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_fallback_mode", "default")

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.FALLBACK
    assert result.effective_bypass_mode == "default"


def test_ensure_pot_provider_server_not_reachable_after_start(monkeypatch):
    """When container starts but server isn't reachable within timeout, falls back."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "start_pot_container", lambda: True)
    monkeypatch.setattr(pot_provider, "_wait_for_server", lambda timeout=30.0, interval=1.0: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_fallback_mode", "default")

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.FALLBACK
    assert result.effective_bypass_mode == "default"


# ---------------------------------------------------------------------------
# ensure_pot_provider — container already running but not yet reachable
# ---------------------------------------------------------------------------

def test_ensure_pot_provider_container_starting_up(monkeypatch):
    """When the container is running but server not yet reachable, waits for it."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: True)
    monkeypatch.setattr(pot_provider, "_wait_for_server", lambda timeout=15.0, interval=1.0: True)

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.ALREADY_RUNNING
    assert result.effective_bypass_mode == "po_token"


def test_ensure_pot_provider_container_starting_up_timeout(monkeypatch):
    """When container is running but server never becomes reachable, falls back."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: True)
    monkeypatch.setattr(pot_provider, "_wait_for_server", lambda timeout=15.0, interval=1.0: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "start_pot_container", lambda: True)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_fallback_mode", "default")

    # After the wait fails, it tries to start a new container.
    # But start_pot_container returns True and _wait_for_server (30s) also fails.
    # We need to handle the second _wait_for_server call differently.
    wait_results = [False, False]
    def fake_wait(timeout=30.0, interval=1.0):
        return wait_results.pop(0) if wait_results else False
    monkeypatch.setattr(pot_provider, "_wait_for_server", fake_wait)

    result = ensure_pot_provider()
    assert result.status == PotProviderStatus.FALLBACK


# ---------------------------------------------------------------------------
# shutdown_pot_provider
# ---------------------------------------------------------------------------

def test_shutdown_pot_provider_stops_if_we_started(monkeypatch):
    """shutdown_pot_provider stops the container if we started it."""
    pot_provider._we_started_container = True
    called = {"stop": False}
    monkeypatch.setattr(pot_provider, "stop_pot_container", lambda: called.__setitem__("stop", True))

    shutdown_pot_provider()
    assert called["stop"] is True
    assert pot_provider._we_started_container is False


def test_shutdown_pot_provider_skips_if_not_started(monkeypatch):
    """shutdown_pot_provider does nothing if we didn't start the container."""
    pot_provider._we_started_container = False
    called = {"stop": False}
    monkeypatch.setattr(pot_provider, "stop_pot_container", lambda: called.__setitem__("stop", True))

    shutdown_pot_provider()
    assert called["stop"] is False


# ---------------------------------------------------------------------------
# get_pot_provider_status
# ---------------------------------------------------------------------------

def test_get_pot_provider_status_active(monkeypatch):
    """Status is 'active' when server is reachable."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: True)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: True)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(pot_provider.settings, "pot_provider_url", "http://127.0.0.1:4416")

    status = get_pot_provider_status()
    assert status["status"] == "active"
    assert status["reachable"] is True
    assert status["running"] is True
    assert status["docker_available"] is True


def test_get_pot_provider_status_unavailable(monkeypatch):
    """Status is 'unavailable' when Docker is not installed."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(pot_provider.settings, "pot_provider_url", "http://127.0.0.1:4416")

    status = get_pot_provider_status()
    assert status["status"] == "unavailable"
    assert status["reachable"] is False
    assert status["docker_available"] is False


def test_get_pot_provider_status_stopped(monkeypatch):
    """Status is 'stopped' when Docker is available but container isn't running."""
    monkeypatch.setattr(pot_provider, "is_pot_server_reachable", lambda url=None, timeout=2.0: False)
    monkeypatch.setattr(pot_provider, "is_docker_available", lambda: True)
    monkeypatch.setattr(pot_provider, "_is_container_running", lambda: False)
    monkeypatch.setattr(pot_provider.settings, "yt_dlp_bypass_mode", "po_token")
    monkeypatch.setattr(pot_provider.settings, "pot_provider_url", "http://127.0.0.1:4416")

    status = get_pot_provider_status()
    assert status["status"] == "stopped"
    assert status["running"] is False
    assert status["docker_available"] is True


# ---------------------------------------------------------------------------
# stop_pot_container
# ---------------------------------------------------------------------------

def test_stop_pot_container_success(monkeypatch):
    """stop_pot_container runs docker stop and docker rm."""
    calls = []
    def fake_run(*a, **kw):
        calls.append(a[0])
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(pot_provider.settings, "pot_provider_container_name", "test-pot")

    assert stop_pot_container() is True
    assert any("stop" in c for c in calls)
    assert any("rm" in c for c in calls)
