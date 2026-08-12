"""Subprocess invocation for the agy CLI.

The runner is the *only* module that talks to the agy subprocess;
:func:`streamdoc.core.agy_upload.upload_to_agy` calls
:func:`run_skill` (and the here.now publish path calls
:func:`streamdoc.integrations.agy.herenow.publish` which calls
:func:`run_skill` again). stdout/stderr are captured so the
orchestrator can surface them in ``AgyUploadResult.errors`` without
the fetch pipeline ever blocking on the subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from streamdoc.config import settings
from streamdoc.integrations.agy.discovery import find_agy_binary
from streamdoc.integrations.agy.exceptions import (
    AGYInvocationError,
    AGYNotInstalledError,
)

logger = logging.getLogger(__name__)


ARTIFACT_PREFIX: str = "Artifact:"  # agy stdout convention per the POR-27 PRD


@dataclass
class AgyRunResult:
    """Result of a single ``agy`` invocation.

    Attributes:
        success: True iff the subprocess exited 0 AND we could find an
            ``Artifact: <path>`` line in stdout (or stdout had no error
            and no expectation to find an artifact).
        artifact_path: Local path parsed from stdout, or None if no
            ``Artifact:`` line was found.
        stdout: Raw stdout (UTF-8 best-effort decoded).
        stderr: Raw stderr.
        exit_code: Process exit code. ``-1`` indicates the subprocess
            was killed by us (e.g. on timeout).
        error: Human-readable error message, or None on success.
        prompt_file: Path to the temp file the prompt was written to,
            or None if the run was skipped. Used by the test suite to
            assert on what the CLI would have seen.
    """

    success: bool
    artifact_path: Path | None
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None
    prompt_file: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }


# --- stdout parsers ----------------------------------------------------------

# Reason: per the POR-27 T2 acceptance criterion, the parser must
# tolerate "Artifact: <path>" with leading and trailing log noise on
# the same line (the test fixture is "... Artifact: /tmp/y ...
# extra"). We do NOT anchor the start of the line with `^` because
# the CLI banner and progress lines often sit on the same line as
# the artifact announcement. We use a leading `\b` (word boundary)
# to avoid matching e.g. "MyArtifact: /tmp/x", but we do NOT add a
# trailing `\b` because the `:` is a non-word character and
# ``\b:`` would fail (a `\b` requires a word/non-word transition on
# both sides, and the char after `:` in any match is either a space
# or end-of-line, which is non-word — so `:` itself is a boundary
# and we don't need an explicit one). The path is captured as
# everything from "Artifact:" to end-of-line, and the caller extracts
# the first whitespace-free token.
_ARTIFACT_RE = re.compile(
    rf"\b{re.escape(ARTIFACT_PREFIX)}\s*(?P<rest>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_artifact_path(stdout: str) -> Path | None:
    """Find the first ``Artifact: <path>`` line in ``stdout``.

    Tolerant of:
      * leading/trailing whitespace on the line and on the path
      * mixed case (``artifact:`` / ``ARTIFACT:`` both match)
      * trailing log noise on the same line (anything after the path is
        ignored; the path is the longest non-whitespace run after
        ``Artifact:``)
      * extra log noise around the line (we only need the first match)

    Returns ``None`` when no ``Artifact:`` line is present.
    """
    match = _ARTIFACT_RE.search(stdout or "")
    if not match:
        return None
    # Take the first whitespace-free token of the captured rest. This
    # is what makes the parser tolerant of trailing log noise (e.g.
    # "... Artifact: /tmp/x  elapsed=1.2s" still yields "/tmp/x").
    rest = (match.group("rest") or "").strip()
    if not rest:
        return None
    first_token = rest.split()[0]
    return Path(first_token)


# --- model discovery ---------------------------------------------------------

# Reason: the real agy CLI exposes ``agy models`` (plain text, one model
# per line).  We keep the list as a constant so it is easy to extend if
# upstream adds a machine-readable variant.
_MODEL_COMMAND_CANDIDATES = [
    ["models"],
    ["models", "--json"],
]


def _parse_model_list(text: str) -> list[str]:
    """Try to extract a list of model identifiers from CLI output.

    Tries JSON parsing first, then falls back to line-by-line parsing
    where each non-empty line is a model id.
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [str(m).strip() for m in data if str(m).strip()]
    if isinstance(data, dict):
        # Common shapes: {"models": [...]}, {"models": {"id": ...}}
        models = data.get("models", [])
        if isinstance(models, list):
            return [str(m).strip() for m in models if str(m).strip()]
        if isinstance(models, dict):
            return [str(k).strip() for k in models if str(k).strip()]
        # Some CLIs nest under a "data" key.
        data_list = data.get("data", [])
        if isinstance(data_list, list):
            return [
                str(m.get("id", m)).strip()
                for m in data_list
                if str(m.get("id", m)).strip()
            ]
    # Plain text: one model id per line, ignoring comments and banners.
    # Reason: the real `agy models` command prints "<id>\t<description>"
    # (e.g. "gemini-3.6-flash-high\tGemini 3.6 Flash (High)") preceded
    # by a "Fetching available models..." banner line. For tab-separated
    # lines the id is the part before the tab. For lines without a tab we
    # only accept the whole line when it is a single whitespace-free token
    # (a bare model id) — this drops banner/header lines like "Fetching
    # available models..." which contain spaces.
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "*", ">")):
            continue
        if "\t" in line:
            candidate = line.split("\t", 1)[0].strip()
            if candidate and " " not in candidate:
                out.append(candidate)
        elif " " not in line:
            # Reason: a bare model id line (no spaces, no tab) — accept
            # verbatim. Any line with spaces and no tab is a banner or
            # description and is skipped.
            out.append(line)
    return out


_MODEL_CACHE: list[str] | None = None


def resolve_agy_model(model: str | None, timeout: float = 8.0) -> str:
    """Return a model string known to be accepted by the installed agy CLI.

    If ``model`` is empty, agy's own default is preserved (no ``--model``
    flag).  If a non-empty model is requested and the agy CLI is reachable,
    the requested id is used only when it appears in the CLI's model list.
    Otherwise a fast fallback is chosen from the discovered list: we prefer
    a ``flash-low`` model (cheapest + fastest for one-shot generation),
    then any ``flash`` model, then the first discovered model.

    Args:
        model: Requested model id, or empty/None to use the agy default.
        timeout: How long to wait for ``agy models`` output.

    Returns:
        A model id to pass to ``--model``, or an empty string to omit the flag.
    """
    if not model:
        return ""

    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = list_models(timeout=timeout)

    available = _MODEL_CACHE
    if not available or model in available:
        return model

    # Reason: prefer a fast/cheap model as the fallback so a stale
    # configured model (e.g. "gemini-2.5-pro" after an upgrade) does not
    # silently route to the most expensive model on the list.
    fallback = _pick_fast_fallback(available)
    logger.warning(
        "requested agy model %r not in available list; falling back to %r",
        model, fallback,
    )
    return fallback


def _pick_fast_fallback(models: list[str]) -> str:
    """Pick a fast/cheap model from ``models`` as a safe fallback.

    Preference order:
      1. Any model containing ``flash-low`` (fastest + cheapest).
      2. Any model containing ``flash``.
      3. The first model in the list (already sorted by :func:`list_models`).
    """
    for m in models:
        if "flash-low" in m:
            return m
    for m in models:
        if "flash" in m:
            return m
    return models[0]


def list_models(timeout: float = 8.0) -> list[str]:
    """Return the list of models supported by the installed agy CLI.

    Falls back to the operator-supplied allowlist in
    ``settings.agy_supported_models`` when the agy CLI is not installed or
    its ``models`` command cannot be probed.  We intentionally do *not*
    invent a static list of models, because the real set depends on the
    installed agy version and API keys.

    Args:
        timeout: Per-candidate timeout in seconds.

    Returns:
        Sorted list of unique model identifiers.
    """
    binary = find_agy_binary()
    return _list_models_from_binary(binary, timeout)


def _list_models_from_binary(binary: str | None, timeout: float) -> list[str]:
    candidates: list[str] = []
    if binary:
        for suffix in _MODEL_COMMAND_CANDIDATES:
            cmd = [binary, *suffix]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    stdin=subprocess.DEVNULL,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                logger.debug("agy model probe failed for %s: %s", cmd, exc)
                continue
            if proc.returncode == 0:
                parsed = _parse_model_list(proc.stdout)
                if parsed:
                    candidates = parsed
                    break

    # Reason: CLI model list wins.  Only if the CLI is unavailable or the
    # command is unrecognized do we use the operator-curated allowlist.
    # We no longer fall back to a hard-coded default list to avoid showing
    # non-existent models.
    if not candidates:
        env_list = (settings.agy_supported_models or "").strip()
        if env_list:
            candidates = [m.strip() for m in env_list.split(",") if m.strip()]

    seen: set[str] = set()
    out: list[str] = []
    for m in candidates:
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return sorted(out)


# --- command builder ---------------------------------------------------------


def _build_command(
    binary: str,
    report_paths: list[Path],
    skill: str,
    model: str | None,
    prompt: str,
) -> list[str]:
    """Assemble the argv for the agy subprocess.

    The real agy CLI accepts ``--prompt`` (alias for ``--print``) with the
    prompt text as the next argument, ``--model`` for the model id, and
    ``--add-dir`` to add directories to the workspace so the agent can read
    the source reports.

    ``--dangerously-skip-permissions`` is mandatory in print mode: without
    it agy cannot prompt for tool permissions (read_file / write_file /
    shell) and silently produces no output, which presents as a broken
    pipeline. The subprocess is always invoked with a curated prompt and
    constrained ``--add-dir`` workspace, so auto-approving tools is safe.
    """
    cmd: list[str] = [binary, "--dangerously-skip-permissions", "--prompt", prompt]

    # Reason: the prompt mentions the report paths; we add each report's
    # parent directory to the agy workspace so the files are visible.
    parent_dirs = {p.parent for p in report_paths}
    for directory in parent_dirs:
        cmd += ["--add-dir", str(directory)]

    # Reason: add the agy skills install directory so the agent can read
    # the SKILL.md for the named skill (and any bundled helper scripts
    # like the herenow-publish publish.sh). Discovery is routed through
    # the same install_dir() the rest of the integration uses.
    try:
        from streamdoc.integrations.agy.discovery import install_dir
        skills_dir = install_dir()
        if skills_dir.exists():
            cmd += ["--add-dir", str(skills_dir)]
    except Exception:  # pragma: no cover — defensive
        logger.debug("could not add agy skills dir to workspace", exc_info=True)

    if model:
        cmd += ["--model", model]

    return cmd


# --- runner ------------------------------------------------------------------


async def run_skill(
    report_paths: list[Path],
    skill: str,
    model: str,
    prompt: str,
    cwd: Path | None = None,
    timeout: float | None = None,
    keep_prompt_file: bool = False,
) -> AgyRunResult:
    """Invoke agy with the given inputs and return the parsed result.

    Args:
        report_paths: Source files to feed into agy (one ``--input`` flag
            per path). Must be non-empty — the runner raises
            :class:`AGYInvocationError` otherwise (defensive; a no-input
            invocation would just confuse the CLI).
        skill: Skill name to activate (matches a folder under
            ``assets/skills/agy/``).
        model: Model id. Pass an empty string to omit the ``--model``
            flag and let the CLI pick its default.
        prompt: Free-form prompt text. Written to a temp file and
            passed via ``--prompt-file``.
        cwd: Optional working directory for the subprocess.
        timeout: Per-invocation timeout in seconds. Defaults to
            ``settings.agy_default_wait_timeout`` (10 minutes).
        keep_prompt_file: If True, do not delete the temporary prompt
            file after the run. Used by tests that assert on the file
            contents. Production callers should leave this False.

    Returns:
        :class:`AgyRunResult` — the orchestrator decides what to do
        with it. ``run_skill`` itself never raises on non-zero exit
        codes; it raises only on hard preflight failures.

    Raises:
        AGYNotInstalledError: when no agy binary is on PATH.
        AGYInvocationError: when ``report_paths`` is empty.
    """
    binary = find_agy_binary()
    if not binary:
        raise AGYNotInstalledError("agy binary not found")

    if not report_paths:
        raise AGYInvocationError("no report paths provided to agy")

    # Reason: validate the requested model against the agy CLI's own list.
    # An outdated setting like "gemini-2.5-pro" is silently upgraded to the
    # first model the CLI advertises, while an empty/None value still omits
    # the --model flag so the CLI uses its default.
    resolved_model = resolve_agy_model(model)

    # Reason: the prompt may contain arbitrary newlines, quotes, and
    # code blocks; --prompt-file avoids all shell-escape pitfalls. We
    # use delete=False so the subprocess can read the file on Windows,
    # then unlink it in the finally block below.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    prompt_path: Path | None = None
    result: AgyRunResult | None = None
    try:
        tmp.write(prompt)
        tmp.close()
        prompt_path = Path(tmp.name)

        effective_timeout = float(timeout) if timeout else float(settings.agy_default_wait_timeout)
        model_arg = resolved_model or None  # treat "" / None the same
        cmd = _build_command(binary, report_paths, skill, model_arg, prompt)
        logger.info(
            "agy run: binary=%s skill=%s model=%s inputs=%d timeout=%.1fs",
            binary, skill, model_arg, len(report_paths), effective_timeout,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )
        except FileNotFoundError as exc:
            # Reason: shutil.which said the binary exists, but exec() can't
            # find it (e.g. PATH changed between discovery and exec, or the
            # binary lacks +x). Treat as invocation error so the orchestrator
            # wraps it.
            result = AgyRunResult(
                success=False,
                artifact_path=None,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                error=f"failed to exec agy: {exc}",
                prompt_file=prompt_path,
            )
        else:
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=effective_timeout
                )
            except TimeoutError:
                logger.warning("agy run timed out after %.1fs; killing", effective_timeout)
                try:
                    proc.kill()
                except ProcessLookupError:  # pragma: no cover — already exited
                    pass
                try:
                    await proc.wait()
                except Exception:  # pragma: no cover — defensive
                    pass
                result = AgyRunResult(
                    success=False,
                    artifact_path=None,
                    stdout="",
                    stderr="",
                    exit_code=-1,
                    error=f"agy timed out after {effective_timeout:.1f}s",
                    prompt_file=prompt_path,
                )
            except Exception as exc:
                # Reason: anything else from communicate() (e.g. CancelledError
                # when the parent task is cancelled) — kill the child and
                # surface the error.
                try:
                    proc.kill()
                except ProcessLookupError:  # pragma: no cover
                    pass
                result = AgyRunResult(
                    success=False,
                    artifact_path=None,
                    stdout="",
                    stderr=str(exc),
                    exit_code=-1,
                    error=f"agy communicate failed: {exc}",
                    prompt_file=prompt_path,
                )
            else:
                stdout = (stdout_b or b"").decode("utf-8", errors="replace")
                stderr = (stderr_b or b"").decode("utf-8", errors="replace")
                exit_code = proc.returncode if proc.returncode is not None else -1

                if exit_code != 0:
                    # Reason: surface stderr in `error` (capped to 2KB so a
                    # runaway log doesn't bloat the job report), but keep the
                    # full stdout so a developer can still find the artifact.
                    error_msg = stderr[:2048] or f"agy exited with code {exit_code}"
                    result = AgyRunResult(
                        success=False,
                        artifact_path=None,
                        stdout=stdout,
                        stderr=stderr,
                        exit_code=exit_code,
                        error=error_msg,
                        prompt_file=prompt_path,
                    )
                else:
                    artifact = parse_artifact_path(stdout)
                    if artifact is not None and not artifact.exists():
                        # Reason: the CLI claimed an artifact but the file is
                        # not on disk — treat as a soft failure.
                        result = AgyRunResult(
                            success=True,
                            artifact_path=None,
                            stdout=stdout,
                            stderr=stderr,
                            exit_code=exit_code,
                            error=(
                                f"agy reported artifact at {artifact} but file does not exist; "
                                "check the working directory passed to run_skill"
                            ),
                            prompt_file=prompt_path,
                        )
                    elif artifact is None:
                        # Reason: exit 0 but no Artifact: line — flag as
                        # success with a warning.
                        result = AgyRunResult(
                            success=True,
                            artifact_path=None,
                            stdout=stdout,
                            stderr=stderr,
                            exit_code=exit_code,
                            error="agy exited 0 but stdout did not contain an 'Artifact:' line",
                            prompt_file=prompt_path,
                        )
                    else:
                        result = AgyRunResult(
                            success=True,
                            artifact_path=artifact,
                            stdout=stdout,
                            stderr=stderr,
                            exit_code=exit_code,
                            error=None,
                            prompt_file=prompt_path,
                        )
    finally:
        # Reason: always clean up the temporary prompt file unless the caller
        # explicitly asked to keep it (tests). missing_ok=True handles the
        # case where the file was never written.
        if prompt_path and not keep_prompt_file:
            try:
                prompt_path.unlink(missing_ok=True)
            except Exception:  # pragma: no cover — best effort cleanup
                pass

    if result is None:  # pragma: no cover — defensive
        raise AGYInvocationError("agy run produced no result")

    if not keep_prompt_file:
        # The prompt file has been deleted; don't expose a stale path.
        result.prompt_file = None

    return result


__all__ = [
    "ARTIFACT_PREFIX",
    "AgyRunResult",
    "_build_command",
    "list_models",
    "parse_artifact_path",
    "run_skill",
]
