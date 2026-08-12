"""Unit tests for :mod:`streamdoc.integrations.agy.runner`.

These tests cover the subprocess invocation contract that
:func:`streamdoc.core.agy_upload.upload_to_agy` and the here.now
publish path depend on. The load-bearing assertion is the EXACT
argv shape passed to ``asyncio.create_subprocess_exec`` — this is
the contract with the external agy CLI (per the POR-27 "Testing
Decisions" section: "subprocess command shape is asserted because
it's the contract with the external CLI").

Strategy: patch :func:`asyncio.create_subprocess_exec` to return a
fake ``Process`` whose ``communicate()`` is an awaitable returning a
controllable (stdout, stderr) tuple. The fake process's
``returncode`` is also controllable so the same harness covers
success, non-zero exit, and timeout paths.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

# Reason: pytest-asyncio is in dev deps; the project has no
# asyncio_mode marker so tests need an explicit loop. We use a
# per-test event loop via asyncio.run() to keep each test hermetic
# (no shared state, no loop policy issues on Windows).

# The ``make_fake_subprocess`` fixture is auto-discovered from conftest.
# Add it as a test parameter to create a mock subprocess in 1-2 lines:
#     patcher, proc = make_fake_subprocess(returncode=0, stdout=b"...")


# ---------------------------------------------------------------------
# Test 1: upload_to_agy returns success=False when agy is not installed
# ---------------------------------------------------------------------


def test_run_skill_not_installed_raises_or_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When find_agy_binary() returns None, upload_to_agy returns success=False.

    The spec's test name is ``test_run_skill_not_installed_raises_or_returns_error``
    but its body targets :func:`streamdoc.core.agy_upload.upload_to_agy`
    (the orchestrator), not the runner directly. The orchestrator
    converts the missing-binary case into
    ``AgyUploadResult(success=False, errors=["agy not installed"])``
    without raising — this is the load-bearing "no exception escapes"
    guarantee the fetch pipeline depends on.
    """
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


# ---------------------------------------------------------------------
# Test 2: success path parses Artifact: and asserts the exact command
# ---------------------------------------------------------------------


def test_run_skill_success_parses_artifact_path(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Happy path: stdout contains Artifact: -> success + parsed path.

    Also asserts the EXACT command shape passed to the subprocess.
    This is the contract with the external CLI (per the POR-27
    "Testing Decisions" rationale).
    """
    from streamdoc.integrations.agy import runner as runner_mod

    artifact = tmp_path / "out.html"
    artifact.write_bytes(b"<html/>")
    stdout = (
        b"loading...\n"
        b"Artifact: " + str(artifact).encode("utf-8") + b"\n"
        b"done\n"
    )

    fake_subprocess, process = make_fake_subprocess(
        returncode=0, stdout=stdout, stderr=b""
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hello",
            keep_prompt_file=True,
        )
    )

    # 1. The functional contract: artifact is parsed and the run is marked success.
    assert result.success is True
    assert result.artifact_path == artifact
    assert result.exit_code == 0
    assert result.error is None

    # 2. The CLI contract: the agy command uses --dangerously-skip-permissions,
    # --prompt, --add-dir, and --model. We use membership/positional checks
    # that are robust to the skills-directory --add-dir being inserted when
    # the install dir exists on disk.
    assert fake_subprocess.call_count == 1
    call = fake_subprocess.call_args
    # The runner calls asyncio.create_subprocess_exec(*cmd, ...), so the
    # patched function's positional args are the unpacked cmd list.
    cmd = list(call.args)
    assert cmd[0] == "/fake/agy"
    # Reason: --dangerously-skip-permissions is mandatory in print mode so
    # agy can auto-approve tool permissions (read_file/write_file/shell)
    # without an interactive prompt — without it agy silently produces no
    # output.
    assert "--dangerously-skip-permissions" in cmd
    assert "--prompt" in cmd
    prompt_idx = cmd.index("--prompt")
    assert cmd[prompt_idx + 1] == "hello"
    # --add-dir <parent> for the source report
    assert "--add-dir" in cmd
    assert str(input_pdf.parent) in cmd
    # --model <id> (present because model is non-None)
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "kimi-k2.7"
    # The prompt is also written to a temp file for testability.
    assert result.prompt_file is not None
    assert result.prompt_file.suffix == ".txt"
    assert Path(result.prompt_file).read_text(encoding="utf-8") == "hello"


def test_run_skill_omits_model_flag_when_model_is_none(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When model is None/empty, the --model flag is omitted from argv."""
    from streamdoc.integrations.agy import runner as runner_mod

    artifact = tmp_path / "out.html"
    artifact.write_bytes(b"<html/>")
    fake_subprocess, _ = make_fake_subprocess(
        returncode=0,
        stdout=b"Artifact: " + str(artifact).encode("utf-8") + b"\n",
        stderr=b"",
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="",  # empty -> --model flag omitted
            prompt="hi",
        )
    )

    cmd = list(fake_subprocess.call_args.args)
    # No --model flag should be present.
    assert "--model" not in cmd


# ---------------------------------------------------------------------
# Test 3: timeout path
# ---------------------------------------------------------------------


def test_run_skill_timeout(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """asyncio.TimeoutError from communicate() -> success=False with timeout error."""
    from streamdoc.integrations.agy import runner as runner_mod

    fake_subprocess, process = make_fake_subprocess(
        returncode=-1,
        stdout=b"",
        stderr=b"",
        communicate_raises=asyncio.TimeoutError(),
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
            timeout=0.5,
        )
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.error is not None
    assert "timed out" in result.error.lower()
    # The runner must attempt to kill the child so we don't leak.
    assert process.killed is True


# ---------------------------------------------------------------------
# Test 4: non-zero exit -> stderr surfaces in `error`
# ---------------------------------------------------------------------


def test_run_skill_nonzero_exit_surfaces_stderr(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-zero exit code -> success=False, error carries the stderr excerpt."""
    from streamdoc.integrations.agy import runner as runner_mod

    fake_subprocess, _ = make_fake_subprocess(
        returncode=1,
        stdout=b"some progress\n",
        stderr=b"model rejected\n",
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
        )
    )

    assert result.success is False
    assert result.exit_code == 1
    assert result.error is not None
    assert "model rejected" in result.error
    # The raw stdout/stderr are still recorded for debug.
    assert "some progress" in result.stdout
    assert "model rejected" in result.stderr


# ---------------------------------------------------------------------
# Test 5: parse_artifact_path tolerates log noise on the same line
# ---------------------------------------------------------------------


def test_parse_artifact_path_tolerates_noise() -> None:
    """parse_artifact_path handles the spec's noisy fixture + edge cases."""
    from streamdoc.integrations.agy.runner import parse_artifact_path

    # The spec fixture.
    assert (
        parse_artifact_path("... logs ... Artifact: /tmp/x.html ... more")
        == Path("/tmp/x.html")
    )
    # Cleanest case.
    assert parse_artifact_path("Artifact: /tmp/x") == Path("/tmp/x")
    # Mixed case.
    assert parse_artifact_path("ARTIFACT: /tmp/up") == Path("/tmp/up")
    # Multi-line input — the artifact line is the second line.
    assert (
        parse_artifact_path("loading\nArtifact: /tmp/z\ndone")
        == Path("/tmp/z")
    )
    # No match -> None.
    assert parse_artifact_path("nothing here") is None
    # Empty string -> None.
    assert parse_artifact_path("") is None
    # Trailing whitespace on the path.
    assert parse_artifact_path("Artifact:   /tmp/ws   \n") == Path("/tmp/ws")


# ---------------------------------------------------------------------
# Test 6: AGYNotInstalledError when find_agy_binary returns None
# ---------------------------------------------------------------------


def test_run_skill_raises_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Direct run_skill call with no binary raises AGYNotInstalledError.

    The orchestrator catches this and converts it to a non-raising
    AgyUploadResult, so this test pins the runner's preflight contract
    in isolation.
    """
    from streamdoc.integrations.agy import runner as runner_mod
    from streamdoc.integrations.agy.exceptions import AGYNotInstalledError

    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", lambda *a, **kw: None)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    with pytest.raises(AGYNotInstalledError):
        asyncio.run(
            runner_mod.run_skill(
                report_paths=[input_pdf],
                skill="web-video-presentation",
                model="kimi-k2.7",
                prompt="hi",
            )
        )


# ---------------------------------------------------------------------
# Test 7: empty report_paths raises AGYInvocationError
# ---------------------------------------------------------------------


def test_run_skill_empty_report_paths_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty report_paths -> AGYInvocationError before any subprocess is spawned."""
    from streamdoc.integrations.agy import runner as runner_mod
    from streamdoc.integrations.agy.exceptions import AGYInvocationError

    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    # Should never be called — the preflight check catches empty paths first.
    monkeypatch.setattr("asyncio.create_subprocess_exec", lambda *a, **kw: None)

    with pytest.raises(AGYInvocationError, match="no report paths"):
        asyncio.run(
            runner_mod.run_skill(
                report_paths=[],
                skill="web-video-presentation",
                model="kimi-k2.7",
                prompt="hi",
            )
        )


# ---------------------------------------------------------------------
# Test 8: FileNotFoundError during subprocess exec
# ---------------------------------------------------------------------


def test_run_skill_filenotfounderror_during_exec(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When asyncio.create_subprocess_exec raises FileNotFoundError, return a soft-failure result."""
    from streamdoc.integrations.agy import runner as runner_mod

    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    # Simulate the binary existing per shutil.which but failing at exec().
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        lambda *a, **kw: (_ for _ in ()).throw(
            FileNotFoundError(2, "No such file or directory", "/fake/agy")
        ),
    )

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
        )
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.error is not None
    assert "failed to exec agy" in result.error
    assert "/fake/agy" in result.error


# ---------------------------------------------------------------------
# Test 9: generic Exception during communicate()
# ---------------------------------------------------------------------


def test_run_skill_generic_communicate_exception(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-TimeoutError exception from communicate() -> success=False, child killed."""
    from streamdoc.integrations.agy import runner as runner_mod

    fake_subprocess, process = make_fake_subprocess(
        returncode=-1,
        stdout=b"",
        stderr=b"",
        communicate_raises=RuntimeError("something bad"),
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
        )
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.error is not None
    assert "communicate failed" in result.error
    assert "something bad" in result.error
    # The runner must attempt to kill the child.
    assert process.killed is True


# ---------------------------------------------------------------------
# Test 10: exit 0, artifact parsed but file does not exist on disk
# ---------------------------------------------------------------------


def test_run_skill_exit_zero_artifact_file_missing(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exit 0, Artifact: points to a path that does not exist -> success=True but artifact_path=None."""
    from streamdoc.integrations.agy import runner as runner_mod

    nonexistent = tmp_path / "nonexistent.html"
    # Do NOT create the file — we want to test the missing-file branch.

    fake_subprocess, _ = make_fake_subprocess(
        returncode=0,
        stdout=b"Artifact: " + str(nonexistent).encode("utf-8") + b"\n",
        stderr=b"",
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
        )
    )

    # success is True (exit 0), but artifact_path is None because the file is missing.
    assert result.success is True
    assert result.artifact_path is None
    assert result.exit_code == 0
    assert result.error is not None
    assert "does not exist" in result.error


# ---------------------------------------------------------------------
# Test 11: exit 0, no Artifact: line in stdout
# ---------------------------------------------------------------------


def test_run_skill_exit_zero_no_artifact_line(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exit 0 but no Artifact: line -> success=True, artifact_path=None, warning in error."""
    from streamdoc.integrations.agy import runner as runner_mod

    fake_subprocess, _ = make_fake_subprocess(
        returncode=0,
        stdout=b"agy finished successfully\n",
        stderr=b"",
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")

    result = asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
        )
    )

    assert result.success is True
    assert result.artifact_path is None
    assert result.exit_code == 0
    assert result.error is not None
    assert "did not contain" in result.error or "Artifact" in result.error


# ---------------------------------------------------------------------
# Test 12: npx binary case in _build_command
# ---------------------------------------------------------------------


def test_build_command_prompt_model_and_add_dir() -> None:
    """The agy command uses --prompt, --add-dir, and --model."""
    from streamdoc.integrations.agy.runner import _build_command

    cmd = _build_command(
        binary="/fake/agy",
        report_paths=[Path("/tmp/r.pdf")],
        skill="web-video-presentation",
        model="kimi-k2.7",
        prompt="hello",
    )
    assert cmd[0] == "/fake/agy"
    # Reason: --dangerously-skip-permissions is always first so agy can
    # auto-approve tools in print mode.
    assert "--dangerously-skip-permissions" in cmd
    assert "--prompt" in cmd
    prompt_idx = cmd.index("--prompt")
    assert cmd[prompt_idx + 1] == "hello"
    assert "--add-dir" in cmd
    assert "--model" in cmd


# ---------------------------------------------------------------------
# Test 13: multiple report paths produce multiple --add-dir flags
# ---------------------------------------------------------------------


def test_build_command_multiple_add_dirs() -> None:
    """Each unique report parent directory produces one --add-dir pair."""
    from streamdoc.integrations.agy.runner import _build_command

    paths = [Path("/tmp/a.pdf"), Path("/tmp/b.pdf"), Path("/other/c.pdf")]
    cmd = _build_command(
        binary="/fake/agy",
        report_paths=paths,
        skill="s",
        model=None,
        prompt="hi",
    )
    # Count --add-dir occurrences. There are 2 unique report parent dirs
    # plus optionally 1 for the agy skills install directory (added so the
    # agent can read SKILL.md files). Verify the report parents are present.
    dir_indices = [i for i, v in enumerate(cmd) if v == "--add-dir"]
    parents = {p.parent for p in paths}
    added_dirs = {Path(cmd[idx + 1]) for idx in dir_indices}
    # Reason: the two report parent dirs must always be present.
    assert parents.issubset(added_dirs)
    # Reason: at least the report parents are added; the skills dir may
    # add one more when it exists on disk.
    assert len(dir_indices) >= 2


# ---------------------------------------------------------------------
# Test 14: cwd parameter is passed to the subprocess
# ---------------------------------------------------------------------


def test_run_skill_passes_cwd_to_subprocess(
    make_fake_subprocess: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When cwd is provided, it is forwarded to asyncio.create_subprocess_exec."""
    from streamdoc.integrations.agy import runner as runner_mod

    artifact = tmp_path / "out.html"
    artifact.write_bytes(b"<html/>")
    fake_subprocess, _ = make_fake_subprocess(
        returncode=0,
        stdout=b"Artifact: " + str(artifact).encode("utf-8") + b"\n",
        stderr=b"",
    )
    monkeypatch.setattr(runner_mod, "find_agy_binary", lambda: "/fake/agy")
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_subprocess)

    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF")
    work_dir = tmp_path / "work"

    asyncio.run(
        runner_mod.run_skill(
            report_paths=[input_pdf],
            skill="web-video-presentation",
            model="kimi-k2.7",
            prompt="hi",
            cwd=work_dir,
        )
    )

    # The cwd kwarg should have been forwarded to create_subprocess_exec.
    assert fake_subprocess.call_count == 1
    kwargs = fake_subprocess.call_args.kwargs
    assert kwargs.get("cwd") == str(work_dir)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
