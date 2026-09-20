"""Antigravity (agy) upload integration for the fetch pipeline.

Public entry point: :func:`upload_to_agy`. Mirrors the shape of
:mod:`streamdoc.core.notebooklm_upload` so the fetch pipeline (T3)
can dispatch on the ``outputs`` discriminator with a single branch.

Compared to ``upload_to_notebooklm`` this is intentionally simpler:
agy is a one-shot subprocess, not an async API with notebooks, auth,
and a background poller. There is no auth check, no notebook
creation, no retention-table write in v1 — the only DB-relevant side
effect is a file copy under ``data/Outputs/agy/<preset>/<timestamp>/``
(mirroring the NotebookLM ``data/Outputs/notebooklm/<id>/`` layout).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from streamdoc.config import settings
from streamdoc.core.notify import notify_run_success
from streamdoc.integrations.agy import herenow as herenow_mod
from streamdoc.integrations.agy import runner as runner_mod
from streamdoc.integrations.agy import skills as skills_mod
from streamdoc.integrations.agy.discovery import find_agy_binary
from streamdoc.integrations.agy.exceptions import AGYIntegrationError
from streamdoc.integrations.notebooklm.prompts import ContentType, PromptManager

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from streamdoc.core.fetch import RunArtifact
    from streamdoc.models.preset import Preset

logger = logging.getLogger(__name__)


# Reason: ContentType is a str enum; agy uses the
# ``web_video_presentation`` / ``web_design_engineer`` values that
# already exist in the default agy prompt template shipped under
# ``assets/prompts/agy/default.yaml`` (see T1). We pick
# ``web_video_presentation`` as the default for template rendering
# because it matches the default skill name and is the value the
# content_type placeholder is most often rendered against.
_DEFAULT_AGY_CONTENT_TYPE: ContentType = ContentType.SLIDE_DECK


@dataclass
class AgyUploadResult:
    """Result of :func:`upload_to_agy`.

    Attributes:
        success: True iff the content-generation step succeeded (the
            here.now publish step is best-effort and may fail without
            flipping this flag).
        artifact_path: Local path of the produced artifact, or None
            on failure. Stored under
            ``<agy_output_dir>/<preset_name>/<timestamp>/``.
        herenow_url: Public here.now URL (when ``publish_herenow`` was
            requested and the publish step succeeded).
        skill: Skill name that was invoked.
        model: Model id that was used.
        error: Human-readable error message for the content step.
        errors: Aggregated list of error messages (content + publish).
            Always present; empty list on success.
    """

    success: bool = False
    artifact_path: Path | None = None
    herenow_url: str | None = None
    skill: str | None = None
    model: str | None = None
    error: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "herenow_url": self.herenow_url,
            "skill": self.skill,
            "model": self.model,
            "error": self.error,
            "errors": list(self.errors),
        }


def _build_agy_prompt(
    base_prompt: str,
    skill: str,
    model: str | None,
    report_paths: list[Path],
    is_custom: bool = False,
) -> str:
    """Augment a generated or custom agy prompt with execution context.

    Custom prompts are passed through unchanged so that operator-supplied
    instructions are not silently modified. Generated/template prompts are
    prefixed with the selected skill and model and suffixed with the list of
    source report files so the agy agent knows which files to read.

    The skill is activated by telling the agent to read and follow the
    ``SKILL.md`` for the named skill in the workspace's skills directory
    (added via ``--add-dir`` in :func:`runner._build_command`). agy
    auto-discovers skills under ``.agents/skills/`` but an explicit
    instruction guarantees the agent loads the right one even when several
    skills are installed.
    """
    if is_custom:
        return base_prompt

    source_list = "\n".join(str(p) for p in report_paths) or "No source reports provided."
    return (
        f"Use the '{skill}' skill for this task. Read and follow the "
        f"instructions in .agents/skills/{skill}/SKILL.md before producing "
        f"output.\n"
        f"Model: {model or 'default'}\n\n"
        f"{base_prompt}\n\n"
        f"Source reports to read:\n{source_list}\n\n"
        f"When the artifact is complete, print exactly one line on stdout "
        f"starting with 'Artifact: ' followed by the path to the produced "
        f"file (or directory) so the runner can locate it."
    )


def _resolve_prompt(
    prompt_template: str | None,
    custom_prompt: str | None,
    prompts: PromptManager,
) -> str:
    """Apply the documented prompt resolution priority.

    Mirrors ``upload_to_notebooklm``:
        1. ``prompt_template`` (template name) — render via
           :class:`PromptManager`.
        2. ``custom_prompt`` (raw text) — pass verbatim.
        3. ``settings.agy_default_skill`` (treated as a template name;
           falls through to ``PromptManager``).

    Returns:
        The resolved prompt string (never empty — if nothing is
        configured, the PromptManager's "default" template is used).
    """
    template_name = prompt_template
    if not template_name and not custom_prompt:
        # Reason: the spec's third priority is the settings default
        # template name. settings.agy_default_skill is the SKILL name,
        # not a template name; we treat them as the same here because
        # the assets/prompts/agy/default.yaml template is what the
        # default-skill preset should use.
        template_name = settings.agy_default_skill
        logger.info("agy prompt fallback: using default template %r", template_name)

    if custom_prompt:
        logger.info(
            "agy prompt using custom_prompt (%d chars)", len(custom_prompt)
        )
        return custom_prompt

    if template_name:
        try:
            return prompts.render_prompt(
                template_name=template_name,
                content_type=_DEFAULT_AGY_CONTENT_TYPE,
            )
        except (KeyError, ValueError) as exc:
            # Reason: a configured template name that doesn't exist
            # (KeyError) OR a template whose target_types don't include
            # our default ContentType (ValueError, e.g. the shipped
            # agy assets/prompts/agy/default.yaml declares
            # target_types=[web_video_presentation, web_design_engineer]
            # which are not in the notebooklm ContentType enum, so
            # they get silently dropped at load time) should fall back
            # to "default" rather than fail the run.
            logger.warning(
                "agy prompt template %r unusable (%s); falling back to 'default'",
                template_name, exc,
            )
            # Fall through to the unconditional fallback below.

    # Unconditional fallback: the in-memory PromptManager.DEFAULT_TEMPLATES
    # entry for "default" is guaranteed to support _DEFAULT_AGY_CONTENT_TYPE
    # (ContentType.SLIDE_DECK is listed in its target_types). The on-disk
    # template at assets/prompts/agy/default.yaml OVERRIDES this in-memory
    # one via _load_custom_templates, but only with the agy-specific
    # content types; that override is the very thing that fails. So
    # here we call render_prompt and, if it still raises, drop down to
    # the in-memory template's prompt text directly to guarantee we
    # always return a non-empty string.
    try:
        return prompts.render_prompt(
            template_name="default", content_type=_DEFAULT_AGY_CONTENT_TYPE
        )
    except (KeyError, ValueError) as exc:
        logger.warning(
            "agy prompt default template also unusable (%s); using "
            "in-memory PromptManager.DEFAULT_TEMPLATES['default'] verbatim",
            exc,
        )
        in_mem_default = PromptManager.DEFAULT_TEMPLATES["default"]
        return in_mem_default.prompt.format(
            content_type=_DEFAULT_AGY_CONTENT_TYPE.value,
            **in_mem_default.variables,
        )


def _persist_artifact(
    artifact_path: Path,
    preset_name: str,
) -> Path:
    """Copy the artifact under ``data/Outputs/agy/<preset>/<ts>/``.

    Returns the destination path.
    """
    base = Path(settings.agy_output_dir) / preset_name
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = base / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / artifact_path.name
    shutil.copy2(artifact_path, dest)
    return dest


async def upload_to_agy(
    report_paths: list[Path],
    preset_name: str,
    job_id: str | None = None,
    skill: str | None = None,
    model: str | None = None,
    prompt_template: str | None = None,
    custom_prompt: str | None = None,
    design_prompt: str | None = None,
    publish_herenow: bool = False,
    retention_hours: float | None = None,
    db_session: Session | None = None,
) -> AgyUploadResult:
    """Run an agy skill against ``report_paths`` and optionally publish to here.now.

    Args:
        report_paths: Source files to feed into agy.
        preset_name: Name of the preset being processed (used for
            output directory and log context).
        job_id: Optional job ID for log correlation. Not persisted in
            v1 — included for forward-compat with the T6 retention
            tracking.
        skill: agy skill name. Defaults to
            ``settings.agy_default_skill`` (``web-video-presentation``).
        model: Model id. Defaults to ``settings.agy_default_model``,
            which is ``None`` out of the box (let the CLI pick).
        prompt_template: Template name to render. Highest-priority
            source for the prompt text.
        custom_prompt: Raw prompt text. Second-priority; overrides
            ``prompt_template`` when both are set (caller picks one).
        design_prompt: Rendered design-template text. When set, a
            ``<design>`` block is appended to the FINAL resolved prompt
            on every resolution path (template, custom, fallback). When
            None or blank, the prompt is byte-identical to before.
        publish_herenow: If True, after the content skill succeeds,
            invoke the herenow-publish skill against the produced
            artifact and capture the URL.
        retention_hours: Accepted for API parity with
            :func:`streamdoc.core.notebooklm_upload.upload_to_notebooklm`
            but not used in v1 (agy has no DB retention row yet).
        db_session: Same — accepted for API parity, not used in v1.

    Returns:
        :class:`AgyUploadResult`. The function NEVER raises; the
        fetch pipeline can therefore treat its return value as the
        authoritative record of what happened (success or specific
        failure mode).

    The acceptance criteria for this function (per the POR-27 PRD +
        the T2 spec) are:

        * With agy disabled in settings, return
          ``success=False, errors=["agy integration is disabled"]``.
        * With agy binary missing, return
          ``success=False, errors=["agy not installed"]`` — NO exception
          escapes (the fetch pipeline depends on this guarantee to
          degrade gracefully when the operator has not installed agy).
        * Any AGYIntegrationError raised internally is caught and
          surfaced via ``errors`` rather than re-raised.
    """
    result = AgyUploadResult()

    # 1. Settings gate.
    if not settings.agy_enabled:
        result.errors.append("agy integration is disabled")
        return result

    # 2. Binary availability gate — the load-bearing "no exception"
    # guarantee from the spec.
    if not find_agy_binary():
        result.errors.append("agy not installed")
        return result

    # 3. Resolve skill / model / prompt.
    resolved_skill = skill or settings.agy_default_skill
    # Reason: validate the requested model against the agy CLI so a stale or
    # placeholder default does not fail the subprocess.
    resolved_model = runner_mod.resolve_agy_model(
        model or settings.agy_default_model or None
    ) or None
    result.skill = resolved_skill
    result.model = resolved_model

    prompts = PromptManager(
        settings.agy_templates_dir,
        settings.agy_sample_prompts_dir,
    )
    try:
        if custom_prompt:
            resolved_prompt = custom_prompt
        else:
            resolved_prompt = _resolve_prompt(prompt_template, None, prompts)
        resolved_prompt = _build_agy_prompt(
            resolved_prompt,
            resolved_skill,
            resolved_model,
            report_paths,
            is_custom=bool(custom_prompt),
        )
        # Reason (POR-91 T2): the <design> append happens AFTER the
        # _build_agy_prompt pass-through so it lands on custom prompts too.
        if design_prompt and design_prompt.strip():
            resolved_prompt += f"\n\n<design>\n{design_prompt}\n</design>\n"
    except Exception as exc:
        result.errors.append(f"prompt resolution failed: {exc}")
        return result

    # 4. Ensure the chosen skill is installed (idempotent).
    try:
        skills_mod.install(resolved_skill)
    except FileNotFoundError as exc:
        result.errors.append(f"skill install failed: {exc}")
        return result
    except AGYIntegrationError as exc:
        result.errors.append(f"skill install failed: {exc}")
        return result

    # 5. Run the content skill.
    try:
        run = await runner_mod.run_skill(
            report_paths=report_paths,
            skill=resolved_skill,
            model=resolved_model or "",
            prompt=resolved_prompt,
        )
    except AGYIntegrationError as exc:
        result.errors.append(f"agy invocation failed: {exc}")
        return result
    except Exception as exc:  # pragma: no cover — defensive
        result.errors.append(f"agy invocation raised: {exc}")
        return result

    if not run.success:
        result.error = run.error
        result.errors.append(run.error or f"agy exited {run.exit_code}")
        return result

    if run.artifact_path is None:
        # Reason: exit 0 but no artifact — the run is "successful" in
        # the sense that agy didn't fail, but we have nothing to
        # publish or persist. Surface as an error so the operator
        # knows to look at run.stdout.
        msg = run.error or "agy exited 0 but produced no artifact"
        result.error = msg
        result.errors.append(msg)
        return result

    # 6. Persist the artifact under data/Outputs/agy/<preset>/<ts>/.
    try:
        persisted = _persist_artifact(run.artifact_path, preset_name)
        result.artifact_path = persisted
    except Exception as exc:
        result.errors.append(f"artifact persistence failed: {exc}")
        # Reason: the artifact exists at its original path even though
        # the local copy failed — we still record the original so the
        # operator can find it. But we do NOT proceed to publish,
        # because here.now needs a path we can be sure about.
        result.artifact_path = run.artifact_path
        return result

    # 7. Optional here.now publish step. Best-effort: failures are
    # captured in `errors` but do not flip `success` to False.
    if publish_herenow:
        try:
            publish_result = await herenow_mod.publish(persisted)
        except AGYIntegrationError as exc:
            result.errors.append(f"herenow publish failed: {exc}")
        except Exception as exc:  # pragma: no cover — defensive
            result.errors.append(f"herenow publish raised: {exc}")
        else:
            if publish_result.success:
                result.herenow_url = publish_result.url
            else:
                result.errors.append(
                    publish_result.error
                    or f"herenow publish exited {publish_result.exit_code}"
                )

    result.success = True
    return result


def send_reports_to_agy(
    preset: Preset,
    artifacts: list[RunArtifact],
    job_id: str,
    prompt_template: str | None,
    custom_prompt: str | None,
    candidates_attempted: int = 0,
    design_prompt: str | None = None,
) -> dict[str, str]:
    """Select report files for a preset and upload them to the agy backend.

    This mirrors the logic previously embedded in ``PresetRunner._send_to_agy``
    but lives in the agy integration module so ``fetch.py`` stays focused on
    pipeline orchestration.

    Args:
        preset: Preset configuration. agy fields are read via getattr with
            safe defaults for backward compatibility with older DB rows.
        artifacts: Artifacts produced by the current run. May be empty when
            all videos were already processed and ``skip_processed=True``.
        job_id: Active job ID passed to ``upload_to_agy`` for log correlation.
        prompt_template: Name of the agy prompt template to use (or None).
        custom_prompt: Raw custom prompt text (or None).
        design_prompt: Rendered design-template text forwarded to
            :func:`upload_to_agy` (or None).
        candidates_attempted: Number of videos that entered the processing
            phase. When > 0 and ``artifacts`` is empty, all downloads
            failed — the existing-report fallback must NOT trigger because
            it would upload stale reports from a previous run. When 0 and
            ``artifacts`` is empty, all videos were already processed (or
            no candidates matched) — re-uploading existing reports is the
            intended behaviour.

    Returns:
        Dict of destination name -> result string (keys: ``agy``,
        optionally ``agy_artifact_path``, ``agy_herenow_url``,
        ``agy_errors``).
    """
    destinations: dict[str, str] = {}

    # Reason: use preset.name (display name) for directory paths to match
    # build_outputs, which saves files under output_root/<preset.name>/.
    out_dir = Path(settings.output_root) / preset.name

    # Reason: when the operator has selected an existing report file via
    # preset.agy_existing_report, use it directly instead of the freshly
    # generated artifacts. This is the "send an existing report" testing
    # path: it skips the fetch/transcribe pipeline entirely and feeds the
    # chosen file to agy. The path is validated to exist on disk; a stale
    # or missing path falls through to the normal artifact/existing-PDF
    # selection below so the run still produces something. This check runs
    # before the out_dir.exists() gate so an absolute path outside the
    # preset's own output directory still works.
    existing_report = getattr(preset, "agy_existing_report", None)
    if existing_report:
        existing_path = Path(existing_report)
        if not existing_path.is_absolute():
            # Reason: relative paths are resolved against the preset's
            # output directory so a bare filename ("social-2026-08-10.pdf")
            # picks the file from the preset's own output folder.
            existing_path = out_dir / existing_path
        if existing_path.exists():
            logger.info(
                "Using existing report %s for agy upload (preset=%s)",
                existing_path, preset.name,
            )
            report_paths: list[Path] = [existing_path]
        else:
            logger.warning(
                "agy_existing_report %r not found; falling back to fresh artifacts",
                existing_report,
            )
            report_paths = []
    else:
        if not out_dir.exists():
            return destinations
        # Build report paths from fresh artifacts (PDF preferred, MD fallback).
        report_paths = []
        for a in artifacts:
            if a.pdf_path and a.pdf_path.exists():
                report_paths.append(a.pdf_path)
            elif a.md_path and a.md_path.exists():
                report_paths.append(a.md_path)

    # Reason: when skip_processed=True and all videos were already
    # processed, artifacts is empty. Scan the output directory for
    # existing PDFs so the user can re-run specifically to upload
    # reports to agy. We re-use output_root/<preset.name>/ here
    # (not agy_output_dir) because those are the SOURCE reports
    # produced by build_outputs, not a previously-persisted artifact.
    # HOWEVER: this fallback must only trigger when no candidates entered
    # processing (candidates_attempted == 0). If candidates_attempted > 0
    # and artifacts is empty, it means all downloads/processing FAILED —
    # uploading stale reports from a previous run would be misleading and
    # produce a presentation based on old content.
    if not report_paths and candidates_attempted == 0:
        existing_pdfs = sorted(out_dir.glob("*.pdf"))
        # Reason: exclude FULL_REPORT — aggregate reports should not
        # be fed into agy; only per-video reports should be.
        existing_pdfs = [p for p in existing_pdfs if p.stem != "FULL_REPORT"]
        if existing_pdfs:
            logger.info(
                "No new artifacts, but found %d existing PDF report(s) in %s — uploading to agy",
                len(existing_pdfs),
                out_dir,
            )
            report_paths = existing_pdfs
    elif not report_paths and candidates_attempted > 0:
        # Reason: all candidates failed to process — do NOT upload stale
        # reports. Log a clear warning so the operator knows the run
        # produced nothing and the previous reports were intentionally
        # left untouched.
        logger.warning(
            "Skipping agy upload: %d video(s) entered processing but "
            "all failed — not uploading stale reports from previous runs",
            candidates_attempted,
        )

    if not report_paths:
        logger.warning("No report files found for agy upload")
        return destinations

    try:
        from streamdoc.async_utils import run_async

        result = run_async(
            upload_to_agy(
                report_paths=report_paths,
                preset_name=preset.name,
                job_id=job_id,
                skill=getattr(preset, "agy_skill", None),
                model=getattr(preset, "agy_model", None),
                prompt_template=prompt_template,
                custom_prompt=custom_prompt,
                design_prompt=design_prompt,
                publish_herenow=getattr(preset, "agy_publish_herenow", False),
            )
        )

        if result.success:
            destinations["agy"] = "success"
            if result.artifact_path:
                destinations["agy_artifact_path"] = str(result.artifact_path)
            if result.herenow_url:
                destinations["agy_herenow_url"] = result.herenow_url
            if result.errors:
                destinations["agy_errors"] = "; ".join(result.errors)

            # T4: notify on agy success — failures here MUST NOT affect job status
            try:
                notify_run_success(
                    preset.name,
                    result.herenow_url,
                    str(result.artifact_path) if result.artifact_path else None,
                )
            except Exception as exc:
                logger.warning("notify_run_success (agy) failed: %s", exc)
        else:
            destinations["agy"] = f"error: {'; '.join(result.errors) or 'upload failed'}"
    except Exception as exc:
        destinations["agy"] = f"error: {exc}"
        logger.warning("agy upload failed: %s", exc)

    return destinations


__all__ = [
    "AgyUploadResult",
    "send_reports_to_agy",
    "upload_to_agy",
]
