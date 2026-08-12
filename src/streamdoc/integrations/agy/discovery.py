"""Discovery helpers for the agy CLI binary and skill install locations.

This module is the *only* place that discovers the agy binary; both the
runner and the orchestrator route through :func:`find_agy_binary` so the
resolution logic stays in one file.

Source of truth for the documented install locations:
    https://antigravity.google/docs/cli/install

Fallback chain (highest priority first):
    1. ``STREAMDOC_AGY_BINARY_PATH`` override if it points to an executable.
    2. ``agy`` / ``agy.cmd`` on ``$PATH`` (operator-installed binary).
    3. Known install directories (e.g. ``%LOCALAPPDATA%\agy\bin``,
       ``~/.local/bin``, the active Python venv, npm global shims).
    4. ``None`` — no agy CLI is available.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from streamdoc.config import settings

_AGY_INSTALL_URL = "https://antigravity.google/docs/cli/install"
_NPM_PACKAGE = "@google/antigravity"


def _is_executable(path: str) -> bool:
    """Return True if the path exists and is executable (or a file on Windows)."""
    p = Path(path)
    if not p.exists():
        return False
    if os.name == "nt":
        return p.is_file()
    return os.access(p, os.X_OK)


def _candidate_paths() -> list[Path]:
    """Return a list of likely agy binary locations to probe."""
    home = Path.home()
    candidates: list[Path] = []

    # Reason: the official Windows installer drops agy.exe under
    # %LOCALAPPDATA%\agy\bin.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "agy" / "bin" / "agy.exe")
    candidates.append(home / "AppData" / "Local" / "agy" / "bin" / "agy.exe")

    # Reason: cross-platform user-local installs and the current Python
    # environment's scripts directory (covers ``uv run`` / venv installs).
    candidates.append(home / ".local" / "bin" / "agy")
    candidates.append(Path(sys.executable).parent / "agy")
    candidates.append(Path(sys.executable).parent / "agy.exe")
    candidates.append(Path(sys.executable).parent / "agy.cmd")

    # Reason: npm global shims on Windows and Unix-like systems.
    app_data = os.environ.get("APPDATA")
    if app_data:
        candidates.append(Path(app_data) / "npm" / "agy.cmd")
        candidates.append(Path(app_data) / "npm" / "agy")
    candidates.append(home / "AppData" / "Roaming" / "npm" / "agy.cmd")
    candidates.append(home / "AppData" / "Roaming" / "npm" / "agy")
    candidates.append(home / ".npm-global" / "bin" / "agy")
    candidates.append(Path("/usr/local/bin/agy"))
    candidates.append(Path("/usr/bin/agy"))

    # Reason: agy may be installed via the npm global ``@google/antigravity``
    # package into a node_modules/.bin directory on the user's PATH.
    for node_modules_bin in (
        home / ".local" / "lib" / "node_modules" / ".bin" / "agy",
        home / ".nvm" / "versions" / "node" / "*" / "bin" / "agy",
        Path("/usr/local/lib/node_modules/.bin/agy"),
        Path("/usr/lib/node_modules/.bin/agy"),
    ):
        candidates.append(node_modules_bin)

    return candidates


def find_agy_binary() -> str | None:
    """Return the absolute path to the agy binary, or None.

    Resolution order:
        1. ``STREAMDOC_AGY_BINARY_PATH`` if the file exists and is executable.
        2. ``agy`` (or ``agy.cmd`` / ``agy.exe`` on Windows) on ``$PATH``.
        3. Probed candidate directories from :func:`_candidate_paths`.

    Returns:
        Absolute path to the agy executable, or ``None`` when not available.

    Never raises. Callers that need to surface "not installed" as a hard
    error should compare against ``None`` themselves or use
    :func:`is_available`.
    """
    # Reason: explicit override wins so operators can point to a non-PATH
    # install (e.g. the Windows Antigravity CLI shipped with the IDE).
    override = settings.agy_binary_path
    if override and _is_executable(override):
        return str(Path(override).resolve())

    # Reason: on Windows ``agy.cmd`` / ``agy.exe`` are common; shutil.which
    # handles PATHEXT.
    binary = shutil.which("agy")
    if binary:
        return str(Path(binary).resolve())

    # Reason: the server process may have a different PATH than the user's
    # shell, so probe the documented and common install locations next.
    for candidate in _candidate_paths():
        # Reason: the nvm path is a wildcard; glob to expand it.
        if "*" in str(candidate):
            for expanded in candidate.parent.glob(candidate.name):
                if _is_executable(str(expanded)):
                    return str(expanded.resolve())
        elif _is_executable(str(candidate)):
            return str(candidate.resolve())

    return None


def is_available() -> bool:
    """Return True if the agy CLI can be invoked."""
    return find_agy_binary() is not None


def install_url() -> str:
    """Return the canonical agy CLI installation documentation URL."""
    return _AGY_INSTALL_URL


def npm_package() -> str:
    """Return the npm package name used for npx-based invocation."""
    return _NPM_PACKAGE


def install_dir() -> Path:
    """Return the primary install directory for vendored agy skills.

    Defaults to ``<repo>/.agents/skills`` per the official agy docs
    (workspace-shared location). The directory is NOT created here.

    Returns:
        Absolute, resolved :class:`pathlib.Path`.
    """
    raw = settings.agy_install_dir
    path = Path(raw).expanduser()
    if not path.is_absolute():
        # Reason: the default is a relative path (".agents/skills") so a
        # fresh checkout works without env configuration. Resolve against
        # the current working directory, which is the StreamDoc project
        # root when running under uvicorn, the CLI, or the test suite.
        path = path.resolve()
    return path


def global_dir() -> Path:
    """Return the global-fallback install directory (per agy docs).

    Defaults to ``~/.gemini/config/skills`` (the documented "global"
    location for agy skills that should be shared across all workspaces
    on the host). Only consulted by :func:`list_installed` for inventory
    purposes.
    """
    return Path(settings.agy_global_dir).expanduser().resolve()


__all__ = [
    "find_agy_binary",
    "global_dir",
    "install_dir",
    "install_url",
    "is_available",
    "npm_package",
]
