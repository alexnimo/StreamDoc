"""StreamDoc dev launcher — starts API + Vite dev server with clean shutdown.

Run via:  uv run python scripts/dev.py

This script replaces the shell-based `just dev` target with a cross-platform
Python implementation that:
  - Starts the FastAPI API (uvicorn with reload) on :5454
  - Starts the Vite dev server (HMR) on :5173
  - Shows both processes' output interleaved with prefixes
  - Ctrl-C kills both processes cleanly (no orphans)

On Windows, backgrounding a process with `&` or `start /b` is unreliable
inside just/cmd.exe. This script uses subprocess directly, avoiding all
shell-specific backgrounding issues.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

# Force UTF-8 output (Windows cp1252 can cause OSError on print)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _resolve_cmd(cmd: list[str]) -> list[str]:
    """Resolve command executable for cross-platform execution.

    Args:
        cmd: Command and arguments as a list.

    Returns:
        Resolved command list with correct executable path.
    """
    if os.name != "nt" or len(cmd) == 0:
        return cmd
    exe = cmd[0]
    if "." not in exe:
        import shutil
        for ext in (".cmd", ".exe", ".bat"):
            path = shutil.which(exe + ext) or shutil.which(exe)
            if path:
                cmd[0] = path
                break
    return cmd


def _stream_output(proc: subprocess.Popen, prefix: str) -> None:
    """Stream a process's stdout to our stdout with a prefix.

    Args:
        proc: The subprocess to stream from.
        prefix: Label to prepend to each line (e.g. "API" or "WEB").
    """
    if proc.stdout is None:
        return
    for line in proc.stdout:
        sys.stdout.write(f"[{prefix}] {line}")
        sys.stdout.flush()


def main() -> int:
    """Start API + Vite dev server and manage their lifecycle.

    Returns:
        0 on clean shutdown, 1 on error.
    """
    # Ensure frontend deps are installed
    print("Checking frontend dependencies...")
    npm_cmd = _resolve_cmd(["npm", "install"])
    subprocess.run(npm_cmd, cwd=str(FRONTEND_DIR), check=True)

    # Start API process
    # Reason: --reload-dir limits watching to src/streamdoc only, so we don't
    # need --reload-exclude flags (which have glob expansion issues on Windows).
    print("\nStarting API on :5454 (uvicorn --reload)...")
    api_cmd = _resolve_cmd([
        "uv", "run", "uvicorn", "streamdoc.api.app:create_app",
        "--factory", "--reload",
        "--reload-dir", "src/streamdoc",
        "--port", "5454",
    ])
    api_proc = subprocess.Popen(
        api_cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Start Vite dev server
    print("Starting Vite dev server on :5173...")
    vite_cmd = _resolve_cmd(["npm", "run", "dev"])
    vite_proc = subprocess.Popen(
        vite_cmd,
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Start output streaming threads
    api_thread = Thread(target=_stream_output, args=(api_proc, "API"), daemon=True)
    vite_thread = Thread(target=_stream_output, args=(vite_proc, "WEB"), daemon=True)
    api_thread.start()
    vite_thread.start()

    print("\n" + "=" * 60)
    print("  StreamDoc dev mode running")
    print("  API  -> http://localhost:5454  (Swagger at /docs)")
    print("  UI   -> http://localhost:5173  (open this one)")
    print("  Press Ctrl-C to stop both processes")
    print("=" * 60 + "\n")

    # Wait for either process to exit, or Ctrl-C
    try:
        while True:
            if api_proc.poll() is not None:
                print("\n[API] process exited, stopping Vite...")
                break
            if vite_proc.poll() is not None:
                print("\n[WEB] process exited, stopping API...")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\nCtrl-C received, shutting down...")

    # Clean shutdown: terminate both processes
    for proc, name in [(api_proc, "API"), (vite_proc, "WEB")]:
        if proc.poll() is None:
            print(f"[{name}] terminating...")
            if os.name == "nt":
                # Reason: on Windows, subprocess.terminate sends TerminateProcess
                # which doesn't kill child processes. Use taskkill /T for tree kill.
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
                print(f"[{name}] stopped")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"[{name}] killed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
