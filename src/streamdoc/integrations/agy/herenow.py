"""Publish an agy-produced HTML artifact to here.now and capture the URL.

The here.now publish flow is a *second* agy skill invocation chained
on top of the content-generation skill. When
``preset.agy_publish_herenow`` is set, the orchestrator runs the
content skill (e.g. ``web-video-presentation``) and then runs
:func:`publish` against the produced artifact with the
``herenow-publish`` skill. here.now is anonymous in v1 (per the
POR-27 PRD "Out of Scope" section — no authenticated here.now
uploads), so the URL we get back is the only "destination" the
orchestrator records.

The herenow skill is expected to print a single line of the form
``Published: <url>`` on stdout. :func:`parse_published_url` is
tolerant of surrounding log noise (progress lines, agy banner, etc.)
and returns the first match it finds.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from streamdoc.integrations.agy.exceptions import AGYPublishError
from streamdoc.integrations.agy.runner import AgyRunResult, run_skill

logger = logging.getLogger(__name__)


HERENOW_SKILL_DEFAULT: str = "herenow-publish"
PUBLISHED_PREFIX: str = "Published:"


@dataclass
class HerenowResult:
    """Result of a here.now publish attempt.

    Attributes:
        success: True iff the herenow-publish skill exited 0 AND we
            could parse a URL from stdout.
        url: The published here.now URL, or None.
        stdout: Raw stdout from the publish invocation.
        stderr: Raw stderr.
        exit_code: Process exit code.
        error: Human-readable error message, or None on success.
    """

    success: bool
    url: str | None
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "url": self.url,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }


# Reason: per the POR-27 T2 acceptance criterion, the parser must
# tolerate "Published: <url>" with leading and trailing log noise on
# the same line (the test fixture is "... Published: https://here.now/x ...").
# We do NOT anchor the start of the line with `^` because the CLI
# banner and progress lines often sit on the same line as the publish
# announcement. A leading `\b` (word boundary) avoids matching e.g.
# "Unpublished: <url>". We do NOT add a trailing `\b` because `:` is a
# non-word character (and `\b:` would not match). The URL is captured
# as everything from "Published:" to end-of-line, and the caller
# extracts the first http(s):// token.
_PUBLISHED_RE = re.compile(
    rf"\b{re.escape(PUBLISHED_PREFIX)}\s*(?P<rest>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_published_url(stdout: str) -> str | None:
    """Find the first ``Published: <http(s)://...>`` line in ``stdout``.

    Tolerant of leading/trailing whitespace, mixed case, surrounding
    log noise on the same line, and surrounding log noise around the
    line. Returns ``None`` if no such line is present.

    Only ``http://`` and ``https://`` URLs are accepted — protects
    against a misbehaving skill printing a relative path or a
    ``file://`` URL.
    """
    match = _PUBLISHED_RE.search(stdout or "")
    if not match:
        return None
    rest = (match.group("rest") or "").strip()
    if not rest:
        return None
    # Pull the first http(s)://... token; ignore any trailing log noise
    # on the line.
    for token in rest.split():
        if token.startswith("http://") or token.startswith("https://"):
            # Trim trailing punctuation that the CLI may have left
            # (e.g. "https://x.com." -> "https://x.com") — but only the
            # last char if it's a sentence terminator.
            return token.rstrip(".,;")
    return None


def _ensure_skill_installed(skill: str) -> bool:
    """Best-effort install of the herenow skill.

    Returns True if the skill is present in the install dir after the
    call, False otherwise. The install helper raises
    :class:`FileNotFoundError` if the vendored asset is missing (T5
    not landed yet) — we swallow that here because the operator may
    have already installed the skill out of band, and the publish
    invocation itself is what matters.
    """
    try:
        from streamdoc.integrations.agy.skills import install
        install(skill)
        return True
    except FileNotFoundError as exc:
        logger.info(
            "herenow skill %r not vendored (%s); assuming operator-installed",
            skill, exc,
        )
        return False
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("herenow skill install attempt failed: %s", exc)
        return False


def _wrap_run_error(result: AgyRunResult) -> HerenowResult:
    """Translate a failed :class:`AgyRunResult` into a :class:`HerenowResult`."""
    return HerenowResult(
        success=False,
        url=None,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        error=result.error or f"herenow skill exited {result.exit_code}",
    )


async def publish(
    artifact_path: Path,
    skill: str | None = None,
    timeout: float | None = None,
    cwd: Path | None = None,
) -> HerenowResult:
    """Publish ``artifact_path`` to here.now via the agy herenow-publish skill.

    Args:
        artifact_path: Local path to the HTML artifact produced by the
            content skill. Must exist on disk; the function returns
            ``success=False`` (does not raise) if it does not.
        skill: Override for the herenow skill name. Defaults to
            :data:`HERENOW_SKILL_DEFAULT` (``herenow-publish``).
        timeout: Per-invocation timeout in seconds; defaults to
            ``settings.agy_default_wait_timeout``.
        cwd: Optional working directory for the subprocess.

    Returns:
        :class:`HerenowResult`. On a successful publish, ``url`` is
        the here.now public link. On any failure, ``success`` is False
        and ``error`` is a human-readable message.

    Raises:
        AGYPublishError: when the herenow-publish skill exits 0 but
            stdout does not contain a parseable ``Published:`` URL.
        AGYNotInstalledError: propagates from :func:`run_skill` when
            no agy binary is on PATH.
        AGYInvocationError: propagates from :func:`run_skill` on a
            hard preflight failure.
    """
    skill = skill or HERENOW_SKILL_DEFAULT

    if not artifact_path.exists():
        return HerenowResult(
            success=False,
            url=None,
            stdout="",
            stderr="",
            exit_code=-1,
            error=f"artifact not found: {artifact_path}",
        )

    _ensure_skill_installed(skill)

    # Reason: keep the prompt small + focused — the herenow skill knows
    # what to do with the artifact path; the CLI surfaces are documented
    # in the PRD's "Further Notes" section. The first sentence activates
    # the skill and points the agent at its SKILL.md; the second gives
    # the artifact path; the third asks for the canonical "Published:"
    # line so parse_published_url is guaranteed something to find.
    prompt = (
        f"Use the '{skill}' skill for this task. Read and follow the "
        f"instructions in .agents/skills/{skill}/SKILL.md before acting.\n"
        f"Publish the HTML artifact at {artifact_path} to here.now.\n"
        "When the site is live, print exactly one stdout line prefixed with "
        "'Published:' followed by the public https:// URL "
        "(e.g. 'Published: https://bright-canvas-a7k2.here.now/')."
    )

    result = await run_skill(
        report_paths=[artifact_path],
        skill=skill,
        model="",
        prompt=prompt,
        cwd=cwd,
        timeout=timeout,
    )

    if not result.success:
        return _wrap_run_error(result)

    url = parse_published_url(result.stdout)
    if url is None:
        # Reason: exit 0 but no Published: line — treat as a publish
        # error so the orchestrator surfaces it. Per the spec the
        # publish failure should NOT fail the overall upload, but the
        # operator deserves a clear message.
        preview = (result.stdout or "")[:512]
        raise AGYPublishError(
            "could not parse 'Published: <url>' from agy herenow stdout: "
            f"{preview!r}"
        )

    return HerenowResult(
        success=True,
        url=url,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        error=None,
    )


__all__ = [
    "HERENOW_SKILL_DEFAULT",
    "PUBLISHED_PREFIX",
    "HerenowResult",
    "parse_published_url",
    "publish",
]
