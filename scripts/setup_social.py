"""Interactive helper to install and authenticate the social CLI backends.

Run with:
    just setup-social
"""
from __future__ import annotations

import shutil
import subprocess
import sys


def run(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Run a command and return its completed process."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ensure_tool(name: str, install_cmd: list[str]) -> str | None:
    """Ensure a CLI tool is installed, installing it if missing."""
    binary = shutil.which(name)
    if binary:
        print(f"✅ {name} found: {binary}")
        return binary

    print(f"⚠️  {name} not found. Installing with: {' '.join(install_cmd)}")
    result = run(install_cmd, timeout=120)
    if result.returncode != 0:
        print(f"❌ Failed to install {name}:\n{result.stderr}")
        return None

    binary = shutil.which(name)
    if binary:
        print(f"✅ {name} installed: {binary}")
    else:
        print(f"❌ {name} was installed but is not on PATH. Restart your terminal and retry.")
    return binary


def version(name: str, binary: str) -> None:
    """Print the tool version."""
    result = run([binary, "--version"], timeout=15)
    if result.returncode == 0:
        print(f"📦 {name} version:\n{result.stdout.strip()}")
    else:
        print(f"⚠️  Could not get {name} version: {result.stderr.strip()}")


def guide_auth(name: str, binary: str, login_args: list[str]) -> bool:
    """Guide the user through an interactive auth flow in their terminal."""
    print(f"\n🔐 {name} auth")
    print("This will open your browser. Follow the prompts to log in.")
    input("Press Enter to continue...")

    try:
        subprocess.run([binary, *login_args], check=False)
    except FileNotFoundError:
        print(f"❌ Could not run {binary}.")
        return False

    verify = run([binary, "status"], timeout=30)
    if verify.returncode == 0:
        print(f"✅ {name} is authenticated.")
        return True

    print(f"⚠️  {name} auth status uncertain. Run `{name} status` manually to verify.")
    return False


def main() -> int:
    """Install, authenticate, and verify the social CLI backends."""
    print("🔧 StreamDoc social setup\n")

    # 1. Install twitter-cli and rdt-cli if missing.
    # --upgrade ensures the latest default-branch commit is fetched
    # rather than a cached or pinned version.
    twitter_binary = ensure_tool(
        "twitter",
        ["uv", "tool", "install", "--upgrade", "git+https://github.com/public-clis/twitter-cli.git"],
    )
    rdt_binary = ensure_tool(
        "rdt",
        ["uv", "tool", "install", "--upgrade", "git+https://github.com/public-clis/rdt-cli.git"],
    )

    if not twitter_binary and not rdt_binary:
        print("\n❌ Neither social CLI could be installed. Check your internet/uv setup.")
        return 1

    # 2. Show versions.
    if twitter_binary:
        version("twitter", twitter_binary)
    if rdt_binary:
        version("rdt", rdt_binary)

    # 3. Auth flows.
    if twitter_binary:
        guide_auth("twitter", twitter_binary, ["login"])
    if rdt_binary:
        guide_auth("reddit", rdt_binary, ["login"])

    # 4. Final verification.
    print("\n🔍 Final verification")
    if twitter_binary:
        verify = run([twitter_binary, "status"], timeout=30)
        print(f"  twitter status: {'✅ OK' if verify.returncode == 0 else '❌ not authenticated'}")
    if rdt_binary:
        verify = run([rdt_binary, "status"], timeout=30)
        print(f"  rdt status: {'✅ OK' if verify.returncode == 0 else '❌ not authenticated'}")

    print("\n🚀 All done. Visit Settings > Social in the StreamDoc UI to check status.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
