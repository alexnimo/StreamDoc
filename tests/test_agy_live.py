"""Live integration test for the agy runner.

This test is marked ``@pytest.mark.live`` so it is excluded from the
default CI lane (``pytest -m "not live"``). It is intended to be run
on a developer workstation where the agy binary (or npx + the
``@google/antigravity`` package) is installed, so the full
end-to-end path can be exercised against the real CLI.

Skips (does NOT error) when:
  * agy is not on PATH (the CLI cannot run). We do NOT treat the
    ``npx`` shim alone as installed because on Windows the npm
    shim intercepts our --input/--skill/--model/--prompt-file flags
    as unknown config rather than forwarding them to the inner agy
    binary, so the live test would fail spuriously.
  * here.now is unreachable for the optional herenow assertion
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest


@pytest.mark.live
def test_run_skill_live(tmp_path: Path) -> None:
    """End-to-end agy run against a tiny fixture report.

    Asserts:
      * agy binary is reachable on PATH (not just npx).
      * runner.run_skill against the fixture exits 0.
      * artifact_path is not None.
    """
    if shutil.which("agy") is None:
        pytest.skip("agy not installed on PATH (npx-only fallback not supported by the live test)")

    from streamdoc.integrations.agy import run_skill

    # Build a minimal "report" so agy has input. A single-line text
    # file under tmp_path is enough for the binary to invoke.
    src = tmp_path / "tiny.md"
    src.write_text(
        "# tiny report\n\nSome sample text for the model to summarize.\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        run_skill(
            report_paths=[src],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="Summarize the report into a 3-slide presentation.",
            timeout=120.0,
        )
    )

    assert result.exit_code == 0, (
        f"agy exited {result.exit_code}: {result.error}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.artifact_path is not None, f"no artifact parsed from stdout:\n{result.stdout}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
