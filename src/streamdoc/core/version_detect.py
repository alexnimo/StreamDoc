"""Version detection for runtime plugins.

Extracted from ``core/tools.py`` to keep that module under 500 lines. Each
detector returns ``(installed_version, binary_path_or_extra_info)``.

For pip-managed plugins (yt-dlp, faster-whisper), ``binary_path`` is the
path to the CLI binary if detected. For git-sourced plugins
(notebooklm-py), the second element is the short locked commit SHA.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def detect_yt_dlp_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for yt-dlp."""
    try:
        import yt_dlp
        version = getattr(yt_dlp, "version", None)
        if version is not None:
            return version.__version__, None
    except Exception:
        pass
    # Fallback: run yt-dlp --version
    binary = shutil.which("yt-dlp")
    if binary:
        try:
            result = subprocess.run(
                [binary, "--version"], capture_output=True, text=True,
                timeout=10, check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip().splitlines()[0].strip(), binary
        except Exception:
            pass
    return None, None


def detect_faster_whisper_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for faster-whisper."""
    try:
        import faster_whisper
        version = getattr(faster_whisper, "__version__", None)
        if version:
            return version, None
    except Exception:
        pass
    return None, None


def detect_ffmpeg_version() -> tuple[str | None, str | None]:
    """Return (installed_version, binary_path) for ffmpeg."""
    binary = shutil.which("ffmpeg")
    if not binary:
        return None, None
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, text=True,
            timeout=10, check=False,
        )
        if result.returncode == 0:
            # First line: "ffmpeg version 7.0.2 Copyright ..."
            first_line = result.stdout.strip().splitlines()[0]
            parts = first_line.split()
            if len(parts) >= 3:
                return parts[2].strip(), binary
    except Exception:
        pass
    return None, binary


def detect_notebooklm_py_version() -> tuple[str | None, str | None]:
    """Return (installed_version, locked_sha_short) for notebooklm-py.

    Uses importlib.metadata for the version and reads the locked git SHA
    from uv.lock for the "binary_path" field (displayed as the commit hash).
    """
    try:
        from importlib.metadata import version
        ver = version("notebooklm-py")
        if ver:
            from streamdoc.core.git_plugins import GIT_PLUGINS, locked_git_sha, short_sha
            repo_root = Path(__file__).resolve().parents[2]
            for pkg, _url, _display in GIT_PLUGINS:
                if pkg == "notebooklm-py":
                    sha = locked_git_sha(repo_root, pkg)
                    return ver, short_sha(sha)
            return ver, None
    except Exception:
        pass
    return None, None


def detect_version(name: str) -> tuple[str | None, str | None]:
    """Dispatch to the correct version detector for a plugin.

    Args:
        name: Plugin identifier (yt_dlp, ffmpeg, faster_whisper, notebooklm_py).

    Returns:
        Tuple of (installed_version, binary_path_or_sha_short).
    """
    if name == "yt_dlp":
        return detect_yt_dlp_version()
    if name == "faster_whisper":
        return detect_faster_whisper_version()
    if name == "ffmpeg":
        return detect_ffmpeg_version()
    if name == "notebooklm_py":
        return detect_notebooklm_py_version()
    return None, None
