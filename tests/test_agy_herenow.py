"""Unit tests for :mod:`streamdoc.integrations.agy.herenow`.

The herenow publish path is a *second* agy skill invocation chained
on top of the content-generation skill. These tests pin the contract
between the orchestrator (:func:`streamdoc.core.agy_upload`) and the
herenow module: the publish call must
  - emit a ``HerenowResult(success=True, url=<https://...>)`` when the
    inner agy run succeeds and the stdout contains a parseable URL,
  - emit a non-raising ``HerenowResult(success=False, ...)`` when the
    artifact file is missing on disk (best-effort publish),
  - raise :class:`AGYPublishError` when the herenow skill exits 0 but
    no ``Published:`` line is found (a hard contract violation).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Same async-test strategy as test_agy_runner: use asyncio.run() per test
# to keep them hermetic.


def test_parse_published_url_extracts_https() -> None:
    """The parser extracts the first http(s) URL after "Published:".

    Tolerant of mixed case, leading/trailing log noise, surrounding
    whitespace, and trailing punctuation (the CLI may emit a
    sentence-terminating period after the URL).
    """
    from streamdoc.integrations.agy.herenow import parse_published_url

    # Spec fixture.
    assert (
        parse_published_url("Published: https://here.now/abc")
        == "https://here.now/abc"
    )
    # Mixed case + extra whitespace.
    assert (
        parse_published_url("[log]   PUBLISHED:   https://here.now/y  \n")
        == "https://here.now/y"
    )
    # Trailing punctuation trimmed.
    assert (
        parse_published_url("Published: https://here.now/with-period.")
        == "https://here.now/with-period"
    )
    # http:// is also accepted (https isn't the only valid scheme).
    assert (
        parse_published_url("Published: http://here.now/abc")
        == "http://here.now/abc"
    )
    # Non-http URLs are rejected — the parser guards against a
    # misbehaving skill printing a relative path or file:// URL.
    assert parse_published_url("Published: file:///etc/passwd") is None
    assert parse_published_url("Published: relative/path") is None
    # No Published: line at all.
    assert parse_published_url("nothing here") is None
    # Empty input.
    assert parse_published_url("") is None


def test_publish_success_returns_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Successful agy run with "Published: <url>" -> HerenowResult with url set."""
    from streamdoc.integrations.agy import runner as runner_mod
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy.herenow import publish

    # Create a real artifact so publish() doesn't short-circuit with
    # "artifact not found".
    artifact = tmp_path / "presentation.html"
    artifact.write_bytes(b"<html/>")

    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=artifact,
            stdout="Published: https://here.now/x",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    # Reason: herenow.py does `from ... import runner` and binds
    # `run_skill` as a local name on the herenow module. Patching
    # `runner.run_skill` does NOT propagate to the herenow module's
    # local binding; we must patch the symbol the herenow module
    # actually looks up.
    monkeypatch.setattr(herenow_mod, "run_skill", fake_run)

    result = asyncio.run(publish(artifact_path=artifact))

    assert result.success is True
    assert result.url == "https://here.now/x"
    assert result.exit_code == 0
    assert result.error is None
    # The inner run_skill is called exactly once with the artifact as
    # the only --input and the default herenow-publish skill.
    assert fake_run.call_count == 1
    call_kwargs = fake_run.call_args.kwargs
    assert call_kwargs["report_paths"] == [artifact]
    assert call_kwargs["skill"] == "herenow-publish"
    # The model arg is "" so the CLI picks its default.
    assert call_kwargs["model"] == ""


def test_publish_no_url_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When agy exits 0 but stdout has no 'Published:' line, AGYPublishError is raised."""
    from streamdoc.integrations.agy import runner as runner_mod
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy.exceptions import AGYPublishError
    from streamdoc.integrations.agy.herenow import publish

    artifact = tmp_path / "presentation.html"
    artifact.write_bytes(b"<html/>")

    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=True,
            artifact_path=artifact,
            stdout="done with publish\nno url here\n",
            stderr="",
            exit_code=0,
            error=None,
            prompt_file=None,
        )
    )
    monkeypatch.setattr(herenow_mod, "run_skill", fake_run)

    with pytest.raises(AGYPublishError) as excinfo:
        asyncio.run(publish(artifact_path=artifact))

    # The error message should mention the prefix the operator
    # is looking for, so the operator knows what to fix in the
    # skill's contract.
    assert "Published" in str(excinfo.value)


def test_publish_missing_artifact_returns_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the artifact file is missing, publish() returns success=False (no raise)."""
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy.herenow import publish

    fake_run = MagicMock()
    monkeypatch.setattr(herenow_mod, "run_skill", fake_run)

    missing = tmp_path / "does-not-exist.html"
    result = asyncio.run(publish(artifact_path=missing))

    assert result.success is False
    assert result.url is None
    assert result.error is not None
    assert "not found" in result.error.lower()
    # The inner agy call must NOT be made when the file is missing —
    # otherwise we'd spawn a CLI that just fails with a different error.
    assert fake_run.call_count == 0


def test_publish_failed_run_surfaces_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the inner agy run fails, publish() returns success=False with the error."""
    from streamdoc.integrations.agy import runner as runner_mod
    from streamdoc.integrations.agy import herenow as herenow_mod
    from streamdoc.integrations.agy.herenow import publish

    artifact = tmp_path / "presentation.html"
    artifact.write_bytes(b"<html/>")

    fake_run = AsyncMock(
        return_value=runner_mod.AgyRunResult(
            success=False,
            artifact_path=None,
            stdout="",
            stderr="network down",
            exit_code=1,
            error="network down",
            prompt_file=None,
        )
    )
    monkeypatch.setattr(herenow_mod, "run_skill", fake_run)

    result = asyncio.run(publish(artifact_path=artifact))

    assert result.success is False
    assert result.url is None
    assert "network down" in (result.error or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
