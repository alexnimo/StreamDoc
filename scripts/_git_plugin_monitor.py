"""Git-sourced plugin update monitoring for the StreamDoc update script.

Provides helpers to detect when a git-pinned dependency in ``uv.lock`` has
fallen behind its upstream default branch. This matters for plugins like
``notebooklm-py`` whose auth flow can break silently when the lockfile
commit grows stale — the local code is unchanged but upstream fixes a
regression and the operator never knows.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Reason: git-sourced plugins that follow the upstream default branch but
# are pinned to a specific commit in uv.lock. These need active monitoring
# because a stale lockfile entry (e.g. an auth-flow regression fixed
# upstream) can silently break the integration without any local change.
GIT_PLUGINS: list[tuple[str, str]] = [
    ("notebooklm-py", "https://github.com/teng-lin/notebooklm-py.git"),
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
    result = subprocess.run(
        ["git", "ls-remote", git_url, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    # Output format: "<sha>\trefs/heads/HEAD"
    return result.stdout.split()[0]


def check_git_plugin_updates(repo_root: Path, has_git: bool) -> list[str]:
    """Check git-sourced plugins for upstream commits ahead of the lockfile.

    Args:
        repo_root: Path to the repository root containing ``uv.lock``.
        has_git: Whether git is available on PATH.

    Returns:
        A list of human-readable status lines to print.
    """
    lines: list[str] = []
    if not has_git:
        return lines

    for package, git_url in GIT_PLUGINS:
        locked = locked_git_sha(repo_root, package)
        if locked is None:
            lines.append(f"  [WARN] {package}: not a git-sourced dependency in uv.lock")
            continue

        remote = remote_head_sha(git_url)
        if remote is None:
            lines.append(f"  [WARN] {package}: could not fetch remote HEAD from {git_url}")
            continue

        if locked == remote:
            lines.append(f"  [OK] {package}: up to date ({locked[:12]})")
        else:
            lines.append(
                f"  {package}: UPDATE AVAILABLE "
                f"(locked={locked[:12]}, remote={remote[:12]})"
            )
    return lines
