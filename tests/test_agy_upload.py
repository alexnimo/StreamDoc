"""Unit tests for :func:`streamdoc.core.agy_upload.upload_to_agy`.

The orchestrator function is the load-bearing seam between the fetch
pipeline and the agy integration package. The fetch pipeline depends
on a single guarantee: ``upload_to_agy`` NEVER raises; every failure
mode is captured in ``AgyUploadResult.errors`` and the function
returns the corresponding record.

These tests pin that guarantee end-to-end with mock-based isolation:
the agy binary is mocked to be "found", ``runner_mod.run_skill`` is
patched to return controllable ``AgyRunResult`` instances, and
``herenow_mod.publish`` is patched to return controllable
``HerenowResult`` instances. No real subprocess is spawned; no real
network call is made.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------


def _enable_agy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the upload_to_agy orchestrator think agy is enabled + installed.

    The orchestrator checks ``settings.agy_enabled`` (gate #1) and
    ``find_agy_binary()`` (gate #2) before doing any work. By default
    both are off in the test environment, so we patch them in for the
    tests that need to drive the orchestrator past the gates.
    """
    from streamdoc.config import settings
    from streamdoc.core import agy_upload as agy_upload_mod

    monkeypatch.setattr(settings, "agy_enabled", True)
    monkeypatch.setattr(agy_upload_mod, "find_agy_binary", lambda: "/fake/agy")


def _patch_agy_output_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the orchestrator's artifact persistence dir to tmp_path."""
    from streamdoc.config import settings

    monkeypatch.setattr(settings, "agy_output_dir", str(tmp_path / "agy_out"))


# ---------------------------------------------------------------------
# Test 1: spec's "not installed" case via the orchestrator
# ---------------------------------------------------------------------


def test_upload_to_agy_no_binary_returns_success_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When find_agy_binary() returns None, upload_to_agy returns success=False (no raise)."""
    from streamdoc.config import settings
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.core.agy_upload import AgyUploadResult, upload_to_agy

    monkeypatch.setattr(settings, "agy_enabled", True)
    monkeypatch.setattr(agy_upload_mod, "find_agy_binary", lambda: None)

    result = asyncio.run(
        upload_to_agy(
            report_paths=[Path("/tmp/r.pdf")],
            preset_name="t",
            skill="web-video-presentation",
        )
    )

    assert isinstance(result, AgyUploadResult)
    assert result.success is False
    assert result.errors == ["agy not installed"]


def test_upload_to_agy_disabled_returns_success_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When settings.agy_enabled is False, upload_to_agy returns success=False (no raise)."""
    from streamdoc.config import settings
    from streamdoc.core.agy_upload import AgyUploadResult, upload_to_agy

    monkeypatch.setattr(settings, "agy_enabled", False)

    result = asyncio.run(
        upload_to_agy(
            report_paths=[Path("/tmp/r.pdf")],
            preset_name="t",
            skill="web-video-presentation",
        )
    )

    assert isinstance(result, AgyUploadResult)
    assert result.success is False
    assert result.errors == ["agy integration is disabled"]


# ---------------------------------------------------------------------
# Test 2: happy path with publish_herenow=True
# ---------------------------------------------------------------------


def test_upload_to_agy_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: agy enabled, run_skill succeeds, herenow publish succeeds."""
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy import runner as runner_mod

    _enable_agy(monkeypatch)
    _patch_agy_output_dir(monkeypatch, tmp_path)

    # Create a fake "produced" artifact file on disk; the orchestrator
    # copies it under <agy_output_dir>/<preset>/<ts>/.
    src_artifact = tmp_path / "out.html"
    src_artifact.write_bytes(b"<html/>")

    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=src_artifact,
            stdout="Artifact: " + str(src_artifact) + "\n",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    fake_publish = AsyncMock(
        return_value=herenow_mod.HerenowResult(
            success=True,
            url="https://here.now/x",
            stdout="Published: https://here.now/x",
            stderr="",
            exit_code=0,
            error=None,
        )
    )
    monkeypatch.setattr(agy_upload_mod.runner_mod, "run_skill", fake_run)
    monkeypatch.setattr(agy_upload_mod.herenow_mod, "publish", fake_publish)

    in_pdf = tmp_path / "in.pdf"
    in_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
            publish_herenow=True,
        )
    )

    assert result.success is True
    assert result.herenow_url == "https://here.now/x"
    # The artifact was copied to <tmp>/agy_out/t/<ts>/out.html.
    assert result.artifact_path is not None
    assert result.artifact_path.exists()
    assert result.artifact_path.name == "out.html"
    assert result.artifact_path.read_bytes() == b"<html/>"
    # The inner run_skill was called exactly once.
    assert fake_run.call_count == 1
    # The herenow publish path was called exactly once.
    assert fake_publish.call_count == 1


# ---------------------------------------------------------------------
# Test 3: publish_herenow=False -> herenow.publish is NOT called
# ---------------------------------------------------------------------


def test_upload_to_agy_publish_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When publish_herenow=False, the herenow.publish mock is never called."""
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.integrations.agy import runner as runner_mod

    _enable_agy(monkeypatch)
    _patch_agy_output_dir(monkeypatch, tmp_path)

    src_artifact = tmp_path / "out.html"
    src_artifact.write_bytes(b"<html/>")
    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=src_artifact,
            stdout="Artifact: " + str(src_artifact) + "\n",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    # Use a tracking mock (not AsyncMock) so we can assert NOT called.
    fake_publish = MagicMock()
    monkeypatch.setattr(agy_upload_mod.runner_mod, "run_skill", fake_run)
    monkeypatch.setattr(agy_upload_mod.herenow_mod, "publish", fake_publish)

    in_pdf = tmp_path / "in.pdf"
    in_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
            publish_herenow=False,
        )
    )

    assert result.success is True
    assert result.herenow_url is None
    # herenow.publish must NOT be called when publish_herenow=False.
    assert fake_publish.call_count == 0


# ---------------------------------------------------------------------
# Test 4: prompt resolution priority
# ---------------------------------------------------------------------


def test_upload_to_agy_prompt_resolution_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The orchestrator's prompt resolution priority is honored end-to-end.

    Three sub-cases verified in sequence, each using a fresh fake
    run_skill so the captured prompt argument is unambiguous.

    Priority order (per agy_upload._resolve_prompt):
      1. custom_prompt (raw text) is passed verbatim.
      2. prompt_template (template name) is rendered through
         PromptManager.
      3. settings.agy_default_skill falls through to a fallback chain
         that always yields a non-empty string.
    """
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.integrations.agy import runner as runner_mod

    _enable_agy(monkeypatch)
    _patch_agy_output_dir(monkeypatch, tmp_path)

    # --- Case 1: custom_prompt is passed verbatim ------------------------
    src_artifact = tmp_path / "out.html"
    src_artifact.write_bytes(b"<html/>")
    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=src_artifact,
            stdout="Artifact: " + str(src_artifact) + "\n",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    monkeypatch.setattr(agy_upload_mod.runner_mod, "run_skill", fake_run)
    monkeypatch.setattr(agy_upload_mod.herenow_mod, "publish", MagicMock())

    in_pdf = tmp_path / "in.pdf"
    in_pdf.write_bytes(b"%PDF")

    custom = "CUSTOM_PROMPT_TEXT_xyzzy_NEVER_RENDERED"
    asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
            custom_prompt=custom,
            prompt_template="default",  # also set, but custom should win
        )
    )

    # The captured prompt arg should equal the custom text exactly.
    assert fake_run.call_count == 1
    assert fake_run.call_args.kwargs["prompt"] == custom

    # --- Case 2: prompt_template only, no custom_prompt ------------------
    fake_run.reset_mock()
    asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
            prompt_template="default",
        )
    )
    assert fake_run.call_count == 1
    rendered = fake_run.call_args.kwargs["prompt"]
    # The template renders to a non-empty string (could be a default
    # fallback if the shipped assets/prompts/agy/default.yaml's
    # target_types don't match the runtime ContentType enum — the
    # exact text is not load-bearing; the non-empty guarantee is).
    assert isinstance(rendered, str)
    assert len(rendered) > 0
    # Sanity: it should NOT equal the custom_prompt we passed in case 1.
    assert rendered != custom

    # --- Case 3: neither custom_prompt nor prompt_template ---------------
    # Falls back to settings.agy_default_skill as a template name; the
    # orchestrator's fallback chain guarantees a non-empty prompt.
    fake_run.reset_mock()
    asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
        )
    )
    assert fake_run.call_count == 1
    default_rendered = fake_run.call_args.kwargs["prompt"]
    assert isinstance(default_rendered, str)
    assert len(default_rendered) > 0


# ---------------------------------------------------------------------
# Bonus tests for orchestrator failure modes (not in spec but cheap)
# ---------------------------------------------------------------------


def test_upload_to_agy_run_skill_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When run_skill returns success=False, the orchestrator surfaces the error."""
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.integrations.agy import runner as runner_mod

    _enable_agy(monkeypatch)
    _patch_agy_output_dir(monkeypatch, tmp_path)

    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=False,
            artifact_path=None,
            stdout="",
            stderr="model rejected",
            exit_code=1,
            error="model rejected",
            prompt_file=None,
        )
    )
    monkeypatch.setattr(agy_upload_mod.runner_mod, "run_skill", fake_run)
    monkeypatch.setattr(agy_upload_mod.herenow_mod, "publish", MagicMock())

    in_pdf = tmp_path / "in.pdf"
    in_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
        )
    )

    assert result.success is False
    assert any("model rejected" in e for e in result.errors)


def test_upload_to_agy_herenow_failure_does_not_flip_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A herenow publish failure is best-effort: success stays True, error is captured."""
    from streamdoc.core import agy_upload as agy_upload_mod
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy import runner as runner_mod

    _enable_agy(monkeypatch)
    _patch_agy_output_dir(monkeypatch, tmp_path)

    src_artifact = tmp_path / "out.html"
    src_artifact.write_bytes(b"<html/>")
    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=src_artifact,
            stdout="Artifact: " + str(src_artifact) + "\n",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    fake_publish = AsyncMock(
        return_value=herenow_mod.HerenowResult(
            success=False,
            url=None,
            stdout="",
            stderr="here.now is down",
            exit_code=1,
            error="here.now is down",
        )
    )
    monkeypatch.setattr(agy_upload_mod.runner_mod, "run_skill", fake_run)
    monkeypatch.setattr(agy_upload_mod.herenow_mod, "publish", fake_publish)

    in_pdf = tmp_path / "in.pdf"
    in_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        agy_upload_mod.upload_to_agy(
            report_paths=[in_pdf],
            preset_name="t",
            publish_herenow=True,
        )
    )

    # Content generation succeeded -> success=True, even though publish failed.
    assert result.success is True
    # The herenow error is captured but does not flip success.
    assert any("here.now is down" in e for e in result.errors)
    # No herenow URL because publish failed.
    assert result.herenow_url is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
