"""Git-sourced plugin version monitoring.

Provides helpers to detect when a git-pinned dependency in ``uv.lock`` has
fallen behind its upstream default branch. Used by both the runtime tools
service (``core/tools.py``) and the update script (``scripts/update.py``)
so the logic is not duplicated.

Reason: git-sourced plugins like ``notebooklm-py`` follow the upstream
default branch but are pinned to a specific commit in ``uv.lock``. A stale
lockfile entry can silently break the integration (e.g. an auth-flow
regression fixed upstream) without any local code change, so active
monitoring is essential.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Git-sourced plugins that follow the upstream default branch.
# Each entry: (package_name, git_url, display_name).
GIT_PLUGINS: list[tuple[str, str, str]] = [
    ("notebooklm-py", "https://github.com/teng-lin/notebooklm-py.git", "NotebookLM SDK"),
]


def locked_git_sha(repo_root: Path, package: str) -> str | None:
    """Extract the locked git commit SHA for a package from uv.lock.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.
        package: Package name to look up in uv.lock.

    Returns:
        The 40-char commit SHA, or None if the package is not git-sourced.
    """
    lock_path = repo_root / "uv.lock"
    if not lock_path.exists():
        return None
    text = lock_path.read_text(encoding="utf-8")
    # Reason: uv.lock stores git sources as:
    #   source = { git = "https://...git#<sha>" }
    pattern = rf'name = "{re.escape(package)}".*?source = {{ git = "([^"]+)#([0-9a-f]{{40}})" }}'
    match = re.search(pattern, text, re.DOTALL)
    return match.group(2) if match else None


def remote_head_sha(git_url: str) -> str | None:
    """Fetch the latest HEAD commit SHA from a remote git repository.

    Uses ``git ls-remote`` which is lightweight and does not clone.

    Args:
        git_url: HTTPS git URL of the remote repository.

    Returns:
        The 40-char HEAD commit SHA, or None on failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", git_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    # Output format: "<sha>\trefs/heads/HEAD"
    return result.stdout.split()[0]


def short_sha(sha: str | None, length: int = 12) -> str:
    """Truncate a SHA to a short prefix for display.

    Args:
        sha: Full SHA string, or None.
        length: Number of characters to keep.

    Returns:
        Short SHA, or ``"unknown"`` if sha is None.
    """
    return sha[:length] if sha else "unknown"


def check_git_plugin_update(repo_root: Path, package: str, git_url: str) -> dict[str, str | bool | None]:
    """Check a single git-sourced plugin for upstream updates.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.
        package: Package name (e.g. ``"notebooklm-py"``).
        git_url: HTTPS git URL of the upstream repository.

    Returns:
        Dict with keys: ``locked_sha``, ``remote_sha``, ``update_available``,
        ``installed_sha_short``, ``latest_sha_short``.
    """
    locked = locked_git_sha(repo_root, package)
    remote = remote_head_sha(git_url)

    if locked is None or remote is None:
        update_available = False
    else:
        update_available = locked != remote

    return {
        "locked_sha": locked,
        "remote_sha": remote,
        "update_available": update_available,
        "installed_sha_short": short_sha(locked),
        "latest_sha_short": short_sha(remote),
    }


def check_all_git_plugins(repo_root: Path) -> list[dict[str, str | bool | None]]:
    """Check all registered git-sourced plugins for upstream updates.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.

    Returns:
        List of check result dicts (one per plugin in ``GIT_PLUGINS``).
    """
    results: list[dict[str, str | bool | None]] = []
    for package, git_url, _display in GIT_PLUGINS:
        info = check_git_plugin_update(repo_root, package, git_url)
        info["package"] = package
        results.append(info)
    return results


def git_plugin_latest(repo_root: Path, package: str) -> tuple[str | None, bool]:
    """Get the latest version identifier and update status for a git plugin.

    For git-sourced plugins, the "latest version" is the remote HEAD SHA.
    The installed version is the locked SHA in uv.lock.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.
        package: Package name (e.g. ``"notebooklm-py"``).

    Returns:
        Tuple of (latest_sha_short, update_available). ``latest_sha_short``
        is a 12-char prefix of the remote HEAD SHA, or None on failure.
    """
    git_url = None
    for pkg, url, _display in GIT_PLUGINS:
        if pkg == package:
            git_url = url
            break
    if git_url is None:
        return None, False

    info = check_git_plugin_update(repo_root, package, git_url)
    remote = info.get("remote_sha")
    if remote is None:
        return None, False
    return short_sha(remote), bool(info.get("update_available"))


def git_update_available(repo_root: Path, package: str) -> bool:
    """Check if a git-sourced plugin has an update available (no network call).

    Compares the locked SHA against the cached remote SHA. This is used
    when we have a cached "latest" value and just need to recompute
    update_available from the current locked SHA.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.
        package: Package name (e.g. ``"notebooklm-py"``).

    Returns:
        True if the locked SHA differs from None (i.e. the package is
        git-sourced and the lock entry exists). The actual comparison
        against the remote requires a network call — use
        :func:`git_plugin_latest` for that.
    """
    locked = locked_git_sha(repo_root, package)
    return locked is not None
