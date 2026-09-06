"""StreamDoc update script — handles git, Python deps, JS deps, and runtime tools.

Run via:  uv run python scripts/update.py [--check] [--skip-git] [--skip-deps] [--skip-tools] [--skip-frontend]

Modes:
  default   Apply all updates (git pull, uv sync, npm install, upgrade tools, rebuild frontend).
  --check   Dry-run: show what's outdated without changing anything.

This script is cross-platform (uses subprocess, no shell-specific syntax).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Reason: on Windows, the default console encoding may be cp1252 or similar,
# which can't handle some Unicode characters and raises OSError on print.
# Force UTF-8 output so the script works cross-platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Helpers ───────────────────────────────────────────────────────────


def _resolve_cmd(cmd: list[str]) -> list[str]:
    """Resolve a command for cross-platform execution.

    On Windows, npm/git/uv may need .cmd or .exe suffixes. subprocess.run
    with shell=False doesn't search PATHEXT, so we handle the common cases.

    Args:
        cmd: Command and arguments as a list.

    Returns:
        Resolved command list with correct executable name.
    """
    if os.name != "nt" or len(cmd) == 0:
        return cmd

    exe = cmd[0]
    # Reason: on Windows, npm is a .cmd wrapper. Without this, subprocess
    # raises FileNotFoundError. git and uv are .exe and work directly,
    # but we check for .cmd variants just in case.
    if "." not in exe:
        for ext in (".cmd", ".exe", ".bat"):
            path = shutil.which(exe + ext) or shutil.which(exe)
            if path:
                cmd[0] = path
                break
    return cmd


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result.

    Args:
        cmd: Command and arguments as a list.
        cwd: Working directory (defaults to repo root).
        check: Raise on non-zero exit if True.

    Returns:
        CompletedProcess with stdout/stderr captured as text.
    """
    return subprocess.run(
        _resolve_cmd(cmd),
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=check,
    )


def _header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}", flush=True)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _skip(msg: str) -> None:
    print(f"  [SKIP] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def _has_npm() -> bool:
    return shutil.which("npm") is not None


def _has_git() -> bool:
    return shutil.which("git") is not None


# ── Git ───────────────────────────────────────────────────────────────


def git_has_upstream() -> bool:
    """Check if the current branch has an upstream tracking branch."""
    try:
        _run(["git", "rev-parse", "--abbrev-ref", "@{u}"])
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def git_is_dirty() -> bool:
    """Check if there are uncommitted changes."""
    result = _run(["git", "status", "--porcelain"])
    return bool(result.stdout.strip())


def git_check() -> None:
    """Show git status: current branch, dirty state, and incoming commits."""
    _header("Git")

    if not _has_git():
        _skip("git not found")
        return

    branch = _run(["git", "branch", "--show-current"]).stdout.strip()
    print(f"  Current branch: {branch}")

    if git_is_dirty():
        _warn("Working tree has uncommitted changes — commit or stash before pulling.")
    else:
        _ok("Working tree is clean")

    if not git_has_upstream():
        _skip("No upstream tracking branch — cannot check for remote updates.")
        return

    # Fetch without modifying working tree
    _run(["git", "fetch", "--quiet"], check=False)

    result = _run(["git", "log", "HEAD..@{u}", "--oneline"], check=False)
    incoming = result.stdout.strip()
    if incoming:
        count = len(incoming.splitlines())
        print(f"  {count} new commit(s) on remote:")
        for line in incoming.splitlines()[:10]:
            print(f"    {line}")
        if count > 10:
            print(f"    ... and {count - 10} more")
    else:
        _ok("Up to date with remote")


def git_pull() -> bool:
    """Pull latest changes from remote. Returns True if successful."""
    _header("Git")

    if not _has_git():
        _skip("git not found")
        return False

    branch = _run(["git", "branch", "--show-current"]).stdout.strip()
    print(f"  Current branch: {branch}")

    if git_is_dirty():
        _fail("Working tree has uncommitted changes. Commit or stash first.")
        return False

    if not git_has_upstream():
        _skip("No upstream tracking branch — cannot pull.")
        return False

    result = _run(["git", "pull", "--ff-only"], check=False)
    if result.returncode != 0:
        _fail(f"git pull failed: {result.stderr.strip()}")
        return False

    output = result.stdout.strip()
    if "Already up to date" in output:
        _ok("Already up to date")
    else:
        _ok("Pulled latest changes")
        print(f"  {output}")
    return True


# ── Python deps ───────────────────────────────────────────────────────


def python_check() -> None:
    """Show outdated Python packages."""
    _header("Python dependencies")

    if not _has_uv():
        _skip("uv not found")
        return

    result = _run(["uv", "pip", "list", "--outdated"], check=False)
    if result.returncode != 0:
        _warn("Could not check outdated packages")
        return

    lines = result.stdout.strip().splitlines()
    # uv pip list --outdated prints a header line + package rows
    outdated = [l for l in lines if l and not l.startswith("Package")]
    if outdated:
        print(f"  {len(outdated)} outdated package(s):")
        for line in outdated[:15]:
            print(f"    {line}")
        if len(outdated) > 15:
            print(f"    ... and {len(outdated) - 15} more")
    else:
        _ok("All Python packages up to date")


def python_sync() -> bool:
    """Sync Python dependencies via uv, upgrading the lockfile first.

    ``uv lock --upgrade`` refreshes the lockfile to the latest versions
    that satisfy the ``>=`` lower bounds in ``pyproject.toml``. This keeps
    regularly-updated plugins (yt-dlp, faster-whisper, notebooklm-py, etc.)
    on their newest releases instead of staying pinned to whatever was
    locked last.
    """
    _header("Python dependencies")

    if not _has_uv():
        _skip("uv not found")
        return False

    lock_result = _run(["uv", "lock", "--upgrade"], check=False)
    if lock_result.returncode != 0:
        _fail(f"uv lock --upgrade failed: {lock_result.stderr.strip()}")
        return False

    sync_result = _run(["uv", "sync", "--extra", "dev"], check=False)
    if sync_result.returncode != 0:
        _fail(f"uv sync failed: {sync_result.stderr.strip()}")
        return False

    _ok("Python dependencies upgraded and synced")
    return True


# ── Frontend deps ─────────────────────────────────────────────────────


def frontend_check() -> None:
    """Show outdated npm packages."""
    _header("Frontend dependencies")

    frontend_dir = REPO_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        _skip("frontend/package.json not found")
        return

    if not _has_npm():
        _skip("npm not found")
        return

    result = _run(["npm", "outdated"], cwd=frontend_dir, check=False)
    # npm outdated returns exit code 1 if there are outdated packages (not an error)
    output = result.stdout.strip()
    if output:
        print("  Outdated packages:")
        for line in output.splitlines()[:15]:
            print(f"    {line}")
    else:
        _ok("All frontend packages up to date")


def frontend_install() -> bool:
    """Install/update frontend dependencies via npm. Returns True if successful."""
    _header("Frontend dependencies")

    frontend_dir = REPO_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        _skip("frontend/package.json not found")
        return False

    if not _has_npm():
        _skip("npm not found")
        return False

    result = _run(["npm", "install"], cwd=frontend_dir, check=False)
    if result.returncode != 0:
        _fail(f"npm install failed: {result.stderr.strip()}")
        return False

    _ok("Frontend dependencies installed")
    return True


def frontend_build() -> bool:
    """Build the frontend. Returns True if successful."""
    _header("Frontend build")

    frontend_dir = REPO_ROOT / "frontend"
    if not _has_npm():
        _skip("npm not found")
        return False

    result = _run(["npm", "run", "build"], cwd=frontend_dir, check=False)
    if result.returncode != 0:
        _fail(f"npm run build failed:\n{result.stderr.strip()}")
        return False

    _ok("Frontend built into src/streamdoc/api/static")
    return True


# ── Runtime tools ─────────────────────────────────────────────────────


# Reason: report when git-pinned deps (e.g. notebooklm-py) fall behind upstream.
try:
    from streamdoc.core.git_plugins import check_all_git_plugins
    def _check_git_plugins(repo_root: Path, has_git: bool) -> list[str]:
        if not has_git: return []
        out: list[str] = []
        for i in check_all_git_plugins(repo_root):
            p, l, r = str(i.get("package", "")), i.get("installed_sha_short") or "?", i.get("latest_sha_short") or "?"
            up = i.get("update_available")
            out.append(f"  {'[OK] ' if not up else ''}{p}: {'up to date' if not up else 'UPDATE AVAILABLE'} ({l}{f'→{r}' if up else ''})")
        return out
except ImportError:
    _check_git_plugins = lambda repo_root, has_git: []  # noqa: E731


def tools_check() -> None:
    """Show current versions of runtime tools."""
    _header("Runtime tools")

    if not _has_uv():
        _skip("uv not found")
        return

    # Reason: notebooklm-py is a git dependency whose auth flow breaks
    # silently when stale, so it is monitored alongside the other tools.
    tools = ["yt-dlp", "ffmpeg-python", "faster-whisper", "twitter-cli", "rdt-cli", "notebooklm-py"]

    for name in tools:
        result = _run(
            ["uv", "run", "python", "-c",
             f"from importlib.metadata import version; print(version('{name}'))"],
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"  {name}: {result.stdout.strip()}")
        else:
            print(f"  {name}: not installed")

    # Check git-sourced plugins for upstream commits ahead of the lockfile.
    for line in _check_git_plugins(REPO_ROOT, _has_git()):
        print(line)

    # Check yt-dlp latest from PyPI
    result = _run(
        ["uv", "run", "python", "-c",
         "import urllib.request, json; data = json.loads(urllib.request.urlopen('https://pypi.org/pypi/yt-dlp/json').read()); print(data['info']['version'])"],
        check=False,
    )
    if result.returncode == 0:
        latest = result.stdout.strip()
        installed = _run(["uv", "run", "python", "-c", "import yt_dlp; print(yt_dlp.version.__version__)"], check=False)
        if installed.returncode == 0:
            inst_ver = installed.stdout.strip()
            # Reason: yt-dlp uses zero-padded dates (2026.06.09) while PyPI reports without padding.
            _norm = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
            if _norm(inst_ver) < _norm(latest):
                print(f"  yt-dlp: installed={inst_ver}, latest={latest}  -> UPDATE AVAILABLE")
            else:
                print(f"  yt-dlp: up to date ({inst_ver})")


def tools_upgrade() -> bool:
    """Upgrade runtime tools via ``uv lock --upgrade-package`` then ``uv sync``.

    For git-sourced plugins like notebooklm-py, ``--upgrade-package``
    re-resolves the default branch to its latest commit.
    """
    _header("Runtime tools")

    if not _has_uv():
        _skip("uv not found")
        return False

    tools = ["yt-dlp", "ffmpeg-python", "faster-whisper", "twitter-cli", "rdt-cli", "notebooklm-py"]
    any_upgraded = False

    for tool in tools:
        # Update the lockfile entry for this specific package
        result = _run(["uv", "lock", "--upgrade-package", tool], check=False)
        if result.returncode != 0:
            _warn(f"Could not update lockfile for {tool}: {result.stderr.strip()}")
            continue
        any_upgraded = True

    if any_upgraded:
        # Sync the environment to pick up the new locked versions
        sync_result = _run(["uv", "sync", "--extra", "dev"], check=False)
        if sync_result.returncode != 0:
            _fail(f"uv sync after tool upgrade failed: {sync_result.stderr.strip()}")
            return False

    # Show new versions
    for tool in tools:
        ver_result = _run(
            ["uv", "run", "python", "-c",
             f"from importlib.metadata import version; print(version('{tool}'))"],
            check=False,
        )
        if ver_result.returncode == 0 and ver_result.stdout.strip():
            print(f"  {tool}: {ver_result.stdout.strip()}")

    _ok("Runtime tools upgraded")
    return True


# ── Main ──────────────────────────────────────────────────────────────


def main() -> int:
    """Run the update flow.

    Returns:
        0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description="StreamDoc update script — git, deps, tools, frontend."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: show what's outdated without changing anything.",
    )
    parser.add_argument("--skip-git", action="store_true", help="Skip git pull.")
    parser.add_argument("--skip-deps", action="store_true", help="Skip Python + JS dep sync.")
    parser.add_argument("--skip-tools", action="store_true", help="Skip runtime tool upgrade.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend rebuild.")
    args = parser.parse_args()

    print(f"StreamDoc update — {'CHECK MODE (dry-run)' if args.check else 'APPLY MODE'}")
    print(f"Repo: {REPO_ROOT}")

    if args.check:
        git_check()
        python_check()
        frontend_check()
        tools_check()
        print("\nDone. Run without --check to apply updates.")
        return 0

    # Apply mode
    success = True

    if not args.skip_git:
        success &= git_pull()

    if not args.skip_deps:
        success &= python_sync()
        success &= frontend_install()

    if not args.skip_tools:
        success &= tools_upgrade()

    if not args.skip_frontend:
        success &= frontend_build()

    _header("Summary")
    if success:
        _ok("All update steps completed.")
        print("\n  Restart the app to pick up changes:")
        print("    just prod       (or just dev / just dev-mprocs)")
    else:
        _warn("Some steps failed — see output above.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
