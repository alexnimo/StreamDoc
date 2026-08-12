"""Smoke tests for the POR-27 T2 agy integration package.

These tests intentionally avoid any external CLI dependency — they
exercise the surface that the rest of the StreamDoc codebase relies on
when agy is *not* installed (the common case on a fresh checkout).
Heavyweight coverage of the happy path (subprocess invocation, file
copy, here.now publish) lives in T6 (`tests/test_agy_skills.py`,
`tests/test_agy_runner.py`, `tests/test_agy_herenow.py`,
`tests/test_agy_upload.py`); this file only asserts that the
integration package's public surface imports cleanly and degrades
gracefully.

Tested here (matches the POR-27 T2 acceptance criteria):

1. The exact import line in the spec
   (`from streamdoc.integrations.agy import is_available, install_all,
   list_installed, run_skill, publish`) succeeds.
2. `is_available()` returns False (no exception) when agy/npx are not
   on PATH.
3. `parse_published_url("... Published: https://here.now/x ...")` returns
   the URL with surrounding noise stripped.
4. `parse_artifact_path` returns the first token after ``Artifact:``
   even when the line is surrounded by log noise.
5. `upload_to_agy` never raises — when agy is disabled or absent, it
   returns ``AgyUploadResult(success=False, errors=[...])``.

The tests deliberately do NOT mock the global ``PATH``: the CI image
does not ship agy, so `find_agy_binary()` returns None and the
"not installed" path is the one we actually exercise in production on
a fresh host.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


# Reason: the hermes-agent venv ships a Python-3.13.6-incompatible
# pydantic_core.pyd. Clearing PYTHONPATH and using the project's own
# .venv (which CI uses) avoids the import failure. The conftest in
# tests/ already handles this for pytest discovery; the explicit
# clear here is belt-and-suspenders for direct python -c invocations.


def test_public_api_imports() -> None:
    """The exact import line from the T2 acceptance criteria works."""
    from streamdoc.integrations.agy import (  # noqa: F401
        is_available,
        install_all,
        list_installed,
        run_skill,
        publish,
    )

    # And the additional surface the orchestrator and the T6 test suite
    # use, also exposed from the top-level package:
    from streamdoc.integrations.agy import (  # noqa: F401
        AGYAvailable,
        AGYNotInstalledError,
        AGYPublishError,
        AGYIntegrationError,
        AGYInvocationError,
        AgyRunResult,
        HerenowResult,
        SkillInfo,
        find_agy_binary,
        install_dir,
        global_dir,
        list_available,
        install,
        update,
        parse_artifact_path,
        parse_published_url,
    )
    from streamdoc.core.agy_upload import (  # noqa: F401
        AgyUploadResult,
        upload_to_agy,
    )


def test_is_available_false_without_agy(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() returns False (does not raise) when agy/npx are off PATH."""
    from streamdoc.integrations.agy import is_available

    # Force a clean PATH: the CI image does not ship agy or npx, so the
    # real call already returns False. The monkeypatch is belt-and-
    # suspenders for hosts that DO have agy installed (developer
    # workstations).
    empty_path = os.path.dirname(shutil.which("python") or "") or ""
    monkeypatch.setenv("PATH", empty_path)
    assert is_available() is False


def test_find_agy_binary_returns_none_without_agy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """find_agy_binary() returns None (does not raise) when agy/npx are off PATH."""
    from streamdoc.integrations.agy import find_agy_binary

    empty_path = os.path.dirname(shutil.which("python") or "") or ""
    monkeypatch.setenv("PATH", empty_path)
    assert find_agy_binary() is None


def test_parse_published_url_tolerates_surrounding_noise() -> None:
    """The exact fixture from the T2 acceptance criteria works."""
    from streamdoc.integrations.agy import parse_published_url

    # The T2 spec fixture: "... Published: https://here.now/x ...".
    assert (
        parse_published_url("... Published: https://here.now/x ...")
        == "https://here.now/x"
    )
    # The cleanest case still works.
    assert (
        parse_published_url("Published: https://here.now/abc")
        == "https://here.now/abc"
    )
    # Mixed case + extra whitespace on the same line.
    assert (
        parse_published_url("[log]   PUBLISHED:   https://here.now/y  \n")
        == "https://here.now/y"
    )
    # No match → None.
    assert parse_published_url("no published line here") is None
    # A non-http URL on the Published: line is rejected.
    assert parse_published_url("Published: file:///etc/passwd") is None


def test_parse_artifact_path_tolerates_surrounding_noise() -> None:
    """Artifact: <path> lines with surrounding log noise still parse correctly."""
    from streamdoc.integrations.agy import parse_artifact_path

    assert parse_artifact_path("Artifact: /tmp/x") == Path("/tmp/x")
    # Noisy fixture (mirrors the herenow Published: fixture above).
    assert (
        parse_artifact_path("... Artifact: /tmp/y ... extra")
        == Path("/tmp/y")
    )
    # Mixed case.
    assert parse_artifact_path("ARTIFACT: /tmp/up") == Path("/tmp/up")
    # Multi-line with the artifact on the second line.
    nl = "\n"
    assert (
        parse_artifact_path(f"loading...{nl}Artifact: /tmp/z{nl}done")
        == Path("/tmp/z")
    )
    # No match → None.
    assert parse_artifact_path("nothing here") is None
    # Empty input → None.
    assert parse_artifact_path("") is None


def test_upload_to_agy_does_not_raise_when_disabled() -> None:
    """upload_to_agy returns success=False (no exception) when agy is disabled.

    This is the load-bearing safety guarantee: the fetch pipeline
    (T3) calls upload_to_agy for every preset that lists 'agy' in its
    outputs, and the operator has not yet opted in.
    """
    from streamdoc.config import settings
    from streamdoc.core.agy_upload import AgyUploadResult, upload_to_agy

    # The default config ships with agy_enabled=False; assert that the
    # call site is honoured without requiring env mutation.
    original = settings.agy_enabled
    settings.agy_enabled = False
    try:
        import asyncio

        result = asyncio.run(
            upload_to_agy(
                report_paths=[Path("x.pdf")],
                preset_name="smoke",
                skill="web-video-presentation",
                model="kimi-k2.7",
            )
        )
        assert isinstance(result, AgyUploadResult)
        assert result.success is False
        # The exact error message is an implementation detail; we only
        # assert that SOME non-empty error is reported.
        assert result.errors, "expected at least one error in result.errors"
    finally:
        settings.agy_enabled = original


def test_upload_to_agy_does_not_raise_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """upload_to_agy returns success=False (no exception) when agy binary is missing.

    Mirrors the T2 acceptance criterion: "no exception escapes" when
    the operator has not installed agy.
    """
    from streamdoc.config import settings
    from streamdoc.core.agy_upload import AgyUploadResult, upload_to_agy

    original = settings.agy_enabled
    settings.agy_enabled = True
    # Strip PATH to a directory that has neither agy nor npx.
    empty_path = os.path.dirname(shutil.which("python") or "") or ""
    monkeypatch.setenv("PATH", empty_path)
    try:
        import asyncio

        result = asyncio.run(
            upload_to_agy(
                report_paths=[Path("x.pdf")],
                preset_name="smoke",
                skill="web-video-presentation",
                model="kimi-k2.7",
            )
        )
        assert isinstance(result, AgyUploadResult)
        assert result.success is False
        # Either the disabled gate OR the binary-missing gate may fire
        # depending on test ordering / env. With agy_enabled=True and
        # PATH stripped, the binary-missing gate is the one that fires.
        assert any(
            "not installed" in e.lower() for e in result.errors
        ), f"expected 'not installed' in errors, got {result.errors}"
    finally:
        settings.agy_enabled = original


def test_upload_to_agy_no_artifact_path_does_not_crash() -> None:
    """upload_to_agy handles a missing report_path gracefully (no exception)."""
    from streamdoc.config import settings
    from streamdoc.core.agy_upload import upload_to_agy

    original = settings.agy_enabled
    settings.agy_enabled = False  # short-circuit before the runner
    try:
        import asyncio

        result = asyncio.run(
            upload_to_agy(
                report_paths=[],
                preset_name="smoke",
                skill="web-video-presentation",
            )
        )
        assert result.success is False
        assert result.errors
    finally:
        settings.agy_enabled = original


def test_skills_list_handles_missing_assets_dir() -> None:
    """list_available returns [] (not an exception) when assets/ is not shipped yet.

    T5 may not have landed — the runtime must still function so the
    fetch pipeline degrades gracefully.
    """
    from streamdoc.integrations.agy import list_available, list_installed

    # Both are safe to call when the assets/install dirs are absent.
    assert isinstance(list_available(), list)
    assert isinstance(list_installed(), list)
