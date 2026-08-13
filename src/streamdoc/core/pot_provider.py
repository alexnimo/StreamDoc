"""PO Token provider container lifecycle management.

Manages the bgutil-ytdlp-pot-provider Docker container that generates
Proof-of-Origin tokens for yt-dlp, bypassing YouTube's bot detection.

Architecture:
    StreamDoc (yt-dlp) → built-in bgutil plugin → HTTP POST http://127.0.0.1:4416 → container

The container runs the official TypeScript/Node.js version of the bgutil
POT provider (brainicism/bgutil-ytdlp-pot-provider). This image's version
matches the bgutil plugin built into yt-dlp, ensuring protocol
compatibility. The Rust rewrite (ghcr.io/jim60105/bgutil-pot) uses a
different versioning scheme and is NOT compatible with yt-dlp's built-in
plugin — it causes a major-version mismatch that silently prevents token
fetches.

On startup, ``ensure_pot_provider()`` checks if the container is already
running, starts it if Docker is available, or falls back to the configured
fallback bypass mode if Docker is not installed.
"""
from __future__ import annotations

import logging
import socket
import subprocess
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from streamdoc.config import settings

logger = logging.getLogger(__name__)


class PotProviderStatus(str, Enum):
    """Result of a pot provider ensure/start attempt."""

    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"


@dataclass
class PotProviderResult:
    """Outcome of an ensure_pot_provider call.

    Attributes:
        status: The resulting status enum.
        effective_bypass_mode: The bypass mode the app should use
            (po_token if the provider is running, or the fallback mode).
        message: Human-readable description for logging and UI.
    """

    status: PotProviderStatus
    effective_bypass_mode: str
    message: str


# Track whether we started the container so we can stop it on shutdown.
_we_started_container: bool = False

# Reason: when the POT provider is unavailable and we fall back to a
# different bypass mode, we store the effective mode here so the
# downloader can read it without mutating the global settings object.
# This is set by ensure_pot_provider() and read by get_effective_bypass_mode().
_effective_bypass_mode: str | None = None

# Reason: track the last time we re-validated the effective bypass mode so
# we don't hammer the POT server with TCP probes on every yt-dlp call.
# Re-validation only happens when the cached mode is a fallback (i.e. the
# POT provider was unavailable at startup) — see get_effective_bypass_mode().
_last_revalidation_ts: float = 0.0

# Reason: minimum interval (seconds) between POT reachability re-checks.
# Keeps per-download overhead negligible while still recovering within a
# reasonable window after the container comes back online.
_REVALIDATION_INTERVAL_S: float = 30.0


def get_effective_bypass_mode() -> str:
    """Return the bypass mode the app should actually use at runtime.

    Reason: when po_token is the configured mode but the POT container
    can't start (no Docker), the app falls back to a different mode.
    This function returns that effective mode so the downloader uses
    the right bypass strategy without needing to mutate settings.

    Self-healing: if the cached effective mode is a fallback (i.e. the
    POT provider was unavailable at startup) but the configured mode is
    ``po_token``, this function periodically re-checks whether the POT
    server has become reachable. If it has, the effective mode is
    upgraded back to ``po_token`` so subsequent downloads use the PO
    token bypass instead of a weaker fallback. This handles the common
    case where the container is started (manually or by a later
    ``ensure_pot_provider`` call) after the server has already booted
    and cached a fallback.

    Returns:
        The effective bypass mode string (e.g. "po_token" or
        "default").
    """
    configured = settings.yt_dlp_bypass_mode
    cached = _effective_bypass_mode

    # Reason: no cached fallback — just return the configured mode.
    if cached is None:
        return configured

    # Reason: cached mode already matches the configured mode — no need
    # to re-validate.
    if cached == configured:
        return cached

    # Reason: only self-heal when the user configured po_token but we
    # cached a fallback. If the user explicitly configured a non-po_token
    # mode, the cached value should not be overridden.
    if configured != "po_token":
        return cached

    # Reason: throttle re-validation so we don't probe the POT server on
    # every single yt-dlp invocation. A 30s interval is negligible
    # overhead (one TCP connect) while recovering quickly after the
    # container comes back.
    import time

    global _last_revalidation_ts
    now = time.monotonic()
    if now - _last_revalidation_ts < _REVALIDATION_INTERVAL_S:
        return cached
    _last_revalidation_ts = now

    if is_pot_server_reachable(timeout=2.0):
        logger.info(
            "PO Token provider is now reachable — upgrading effective bypass "
            "mode from %s to po_token (was cached as fallback at startup)",
            cached,
        )
        _set_effective_mode("po_token")
        return "po_token"

    return cached


def _set_effective_mode(mode: str) -> None:
    """Set the runtime effective bypass mode.

    Args:
        mode: The bypass mode to use at runtime.
    """
    global _effective_bypass_mode
    _effective_bypass_mode = mode


def is_docker_available() -> bool:
    """Check if the Docker CLI is available and the daemon is running.

    Returns:
        True if ``docker info`` succeeds, False otherwise.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def is_pot_server_reachable(url: str | None = None, timeout: float = 2.0) -> bool:
    """Check if the POT provider HTTP server is reachable via TCP.

    Args:
        url: Base URL of the POT server (e.g. http://127.0.0.1:4416).
            Defaults to ``settings.pot_provider_url``.
        timeout: TCP connect timeout in seconds.

    Returns:
        True if a TCP connection to the server's host:port succeeds.
    """
    base_url = url or settings.pot_provider_url
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4416
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _get_container_name() -> str:
    """Return the configured container name."""
    return settings.pot_provider_container_name


def _is_container_running() -> bool:
    """Check if our Docker container is already running.

    Returns:
        True if the container exists and is in "running" state.
    """
    name = _get_container_name()
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def start_pot_container() -> bool:
    """Start the POT provider Docker container.

    Pulls the image if not present, then runs it in detached mode with
    ``--restart unless-stopped`` so it survives app restarts.

    Returns:
        True if the container started successfully, False otherwise.
    """
    image = settings.pot_provider_image
    name = _get_container_name()
    base_url = settings.pot_provider_url
    parsed = urlparse(base_url)
    host_port = parsed.port or 4416

    # Reason: remove any stopped container with the same name before starting
    # a fresh one. This avoids "name already in use" errors on restart.
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    logger.info("Starting PO Token provider container (image=%s, port=%d)", image, host_port)
    try:
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", name,
                "--restart", "unless-stopped",
                "-p", f"{host_port}:4416",
                image,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
        if result.returncode != 0:
            logger.error("Failed to start POT container: %s", result.stderr.strip())
            return False
        logger.info("POT container started (id=%s)", result.stdout.strip()[:12])
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Failed to start POT container: %s", exc)
        return False


def stop_pot_container() -> bool:
    """Stop and remove the POT provider Docker container.

    Returns:
        True if the container was stopped and removed, False on error.
    """
    name = _get_container_name()
    try:
        subprocess.run(
            ["docker", "stop", name],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
        subprocess.run(
            ["docker", "rm", name],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        logger.info("POT container stopped and removed (name=%s)", name)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Failed to stop POT container: %s", exc)
        return False


def ensure_pot_provider() -> PotProviderResult:
    """Ensure the POT provider is available, starting it if needed.

    This is the main entry point called on app startup. The logic:

    1. If the server is already reachable → return ALREADY_RUNNING.
    2. If Docker is available → start the container, wait for it to be
       reachable, return STARTED.
    3. If Docker is not available → fall back to the configured fallback
       bypass mode (or ``default`` no-auth if no fallback is set),
       return FALLBACK.

    The effective bypass mode is returned so the caller can switch the
    runtime bypass mode without mutating global settings.

    Returns:
        PotProviderResult with status, effective bypass mode, and message.
    """
    global _we_started_container

    # Reason: if the server is already reachable (container running from a
    # previous session or started manually), there's nothing to do.
    if is_pot_server_reachable():
        logger.info("PO Token provider already running at %s", settings.pot_provider_url)
        _we_started_container = False
        _set_effective_mode("po_token")
        return PotProviderResult(
            status=PotProviderStatus.ALREADY_RUNNING,
            effective_bypass_mode="po_token",
            message=f"PO Token provider running at {settings.pot_provider_url}",
        )

    # Reason: check if our container exists but isn't responding yet —
    # it might be starting up. Give it a moment.
    if _is_container_running():
        logger.info("POT container is running but server not yet reachable — waiting...")
        if _wait_for_server(timeout=15.0):
            _we_started_container = False
            _set_effective_mode("po_token")
            return PotProviderResult(
                status=PotProviderStatus.ALREADY_RUNNING,
                effective_bypass_mode="po_token",
                message="PO Token provider container was already running",
            )

    # Reason: if Docker is not available, fall back to the configured
    # fallback mode. This is the graceful degradation path for users
    # without Docker installed.
    if not is_docker_available():
        fallback = _resolve_fallback_mode()
        logger.warning(
            "Docker not available — PO Token provider cannot start. "
            "Falling back to bypass_mode=%s. Install Docker to enable PO Token.",
            fallback,
        )
        _we_started_container = False
        _set_effective_mode(fallback)
        return PotProviderResult(
            status=PotProviderStatus.FALLBACK,
            effective_bypass_mode=fallback,
            message=f"Docker not available — using {fallback} bypass mode",
        )

    # Reason: Docker is available and the server isn't running — start it.
    if not start_pot_container():
        fallback = _resolve_fallback_mode()
        logger.error(
            "Failed to start POT container — falling back to bypass_mode=%s",
            fallback,
        )
        _we_started_container = False
        _set_effective_mode(fallback)
        return PotProviderResult(
            status=PotProviderStatus.FALLBACK,
            effective_bypass_mode=fallback,
            message=f"Container start failed — using {fallback} bypass mode",
        )

    # Reason: wait for the server to become reachable after starting.
    if not _wait_for_server(timeout=30.0):
        fallback = _resolve_fallback_mode()
        logger.error(
            "POT container started but server not reachable within 30s — "
            "falling back to bypass_mode=%s",
            fallback,
        )
        _we_started_container = False
        _set_effective_mode(fallback)
        return PotProviderResult(
            status=PotProviderStatus.FALLBACK,
            effective_bypass_mode=fallback,
            message="Container started but server not reachable — using fallback",
        )

    _we_started_container = True
    _set_effective_mode("po_token")
    logger.info("PO Token provider started successfully at %s", settings.pot_provider_url)
    return PotProviderResult(
        status=PotProviderStatus.STARTED,
        effective_bypass_mode="po_token",
        message=f"PO Token provider started at {settings.pot_provider_url}",
    )


def shutdown_pot_provider() -> None:
    """Stop the POT container on app shutdown if we started it.

    Reason: if the user started the container manually (via `just pot-up`
    or `docker run`), we leave it running. We only stop containers that
    we started ourselves during ``ensure_pot_provider()``.
    """
    global _we_started_container
    if _we_started_container:
        stop_pot_container()
        _we_started_container = False


def get_pot_provider_status() -> dict[str, str | bool]:
    """Return the current POT provider status for API/UI consumption.

    Returns:
        Dict with keys: running (bool), reachable (bool), bypass_mode (str),
        url (str), docker_available (bool), message (str).
    """
    reachable = is_pot_server_reachable()
    docker = is_docker_available()
    container_running = _is_container_running() if docker else False

    if reachable:
        status = "active"
        message = f"PO Token active at {settings.pot_provider_url}"
    elif container_running:
        status = "starting"
        message = "POT container running but server not yet reachable"
    elif docker:
        status = "stopped"
        message = "Docker available but POT container not running"
    else:
        status = "unavailable"
        message = "Docker not installed — using fallback bypass mode"

    return {
        "status": status,
        "running": container_running,
        "reachable": reachable,
        "bypass_mode": settings.yt_dlp_bypass_mode,
        "effective_bypass_mode": get_effective_bypass_mode(),
        "url": settings.pot_provider_url,
        "docker_available": docker,
        "message": message,
    }


def _resolve_fallback_mode() -> str:
    """Determine the fallback bypass mode when PO Token is unavailable.

    Priority:
        1. ``settings.yt_dlp_bypass_fallback_mode`` (explicit user config)
        2. ``default`` (no-auth — safe, may hit bot detection on some videos)

    Reason: we default to ``default`` (no-auth) rather than
    ``cookies_from_browser`` because reading cookies from the user's active
    browser profile risks getting their YouTube account banned. The
    ``cookies_from_browser`` mode is opt-in only and should never be used
    as an automatic fallback.

    Returns:
        The fallback bypass mode string.
    """
    if settings.yt_dlp_bypass_fallback_mode:
        return settings.yt_dlp_bypass_fallback_mode
    return "default"


def _wait_for_server(timeout: float = 30.0, interval: float = 1.0) -> bool:
    """Poll the POT server until it's reachable or the timeout expires.

    Args:
        timeout: Maximum time to wait in seconds.
        interval: Polling interval in seconds.

    Returns:
        True if the server became reachable, False on timeout.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_pot_server_reachable(timeout=2.0):
            return True
        time.sleep(interval)
    return False
