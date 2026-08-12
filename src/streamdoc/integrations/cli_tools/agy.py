"""Antigravity (agy) CLI Tool Adapter.

Wraps the existing streamdoc.integrations.agy package behind the
BaseCLITool interface for use with the generic CLI tool registry.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from streamdoc.config import settings
from streamdoc.integrations.agy import (
    AgyRunResult,
    PromptManager,
    find_agy_binary,
    install_url,
    is_available,
    resolve_agy_model,
    run_skill,
)
from streamdoc.integrations.agy import (
    skills as agy_skills,
)
from streamdoc.integrations.agy.exceptions import AGYIntegrationError
from streamdoc.integrations.cli_tools.base import (
    BaseCLITool,
    CLIToolInstallStatus,
    CLIToolResult,
)

logger = logging.getLogger(__name__)

# Default skill used when no template specifies one
DEFAULT_SKILL = "web-video-presentation"

# Reason: the CLI Tools page shows a link to the official install docs
# instead of a non-functional Install button. The agy CLI must be
# installed by the operator; StreamDoc does not auto-install third-party
# binaries.
AGY_INSTALL_INSTRUCTIONS = "Install the agy CLI from the official documentation."
AGY_INSTALL_URL = "https://antigravity.google/docs/cli/install"


class AgyCLI(BaseCLITool):
    """Antigravity (agy) CLI tool adapter.

    Delegates to streamdoc.integrations.agy for detection, skill management,
    and skill execution.
    """

    name = "agy"

    def is_installed(self) -> bool:
        """Check if agy binary is available on PATH."""
        return is_available()

    def detect(self) -> CLIToolInstallStatus:
        """Detailed detection with binary path and version."""
        binary_path = find_agy_binary()
        version = None
        if binary_path:
            try:
                result = subprocess.run(
                    [binary_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                elif result.stderr:
                    version = result.stderr.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

        return CLIToolInstallStatus(
            name=self.name,
            installed=binary_path is not None,
            binary_path=binary_path,
            version=version,
            install_instructions=AGY_INSTALL_INSTRUCTIONS if not binary_path else None,
            install_url=install_url() if not binary_path else None,
        )

    def ensure_installed(self, prompt: bool = True) -> CLIToolInstallStatus:
        """Return install guidance; does not auto-install."""
        status = self.detect()
        if not status.installed:
            # Could add interactive prompt here if prompt=True
            pass
        return status

    async def run(
        self,
        report_paths: list[Path],
        template: str | None,
        out_dir: Path,
    ) -> CLIToolResult:
        """Run agy skill against the given reports.

        Args:
            report_paths: Source PDF/MD files to process.
            template: Skill name or template identifier. If None, uses default skill.
            out_dir: Output directory for generated artifact.

        Returns:
            CLIToolResult with success status and artifact path.
        """
        if not report_paths:
            return CLIToolResult(
                success=False,
                error="No report paths provided",
            )

        # Resolve skill name from template or use default
        skill = template or DEFAULT_SKILL

        # Ensure the skill is installed (idempotent copy from assets/skills/agy/)
        try:
            agy_skills.install(skill)
        except FileNotFoundError as exc:
            return CLIToolResult(
                success=False,
                error=f"Skill not found in assets: {exc}",
            )
        except AGYIntegrationError as exc:
            return CLIToolResult(
                success=False,
                error=f"Skill installation failed: {exc}",
            )

        # Resolve prompt: use PromptManager with agy template dirs
        # The template parameter can be a template name (for PromptManager)
        # or we fall back to a default prompt
        prompts = PromptManager(
            settings.agy_templates_dir,
            settings.agy_sample_prompts_dir,
        )

        try:
            # Try to render the template if it exists; fallback to default
            if template:
                prompt_text = prompts.render_prompt(
                    template_name=template,
                    content_type="slide_deck",  # default agy content type
                )
            else:
                prompt_text = prompts.render_prompt(
                    template_name="default",
                    content_type="slide_deck",
                )
        except (KeyError, ValueError):
            # Template not found or invalid - use minimal default prompt
            prompt_text = (
                "Analyze the provided reports and generate a presentation. "
                "Output the result as an HTML artifact with the path prefixed by 'Artifact: '."
            )

        # Resolve to a model the installed agy CLI actually supports.  This
        # keeps settings.agy_default_model from silently failing if the id is
        # stale or a placeholder.
        resolved_model = resolve_agy_model(settings.agy_default_model)

        # Reason: the agy CLI has no dedicated --skill flag; the selected
        # skill and model are communicated through the prompt, along with the
        # list of source reports the agent should read.
        augmented_prompt = (
            f"Skill: {skill}\n"
            f"Model: {resolved_model or 'default'}\n\n"
            f"{prompt_text}\n\n"
            f"Source reports to read:\n"
            + "\n".join(str(p) for p in report_paths)
        )

        # Run the skill
        try:
            result: AgyRunResult = await run_skill(
                report_paths=report_paths,
                skill=skill,
                model=resolved_model,
                prompt=augmented_prompt,
                timeout=settings.agy_default_wait_timeout,
            )
        except AGYIntegrationError as exc:
            return CLIToolResult(
                success=False,
                error=f"agy invocation failed: {exc}",
            )
        except Exception as exc:
            logger.exception("agy run_skill raised unexpected error")
            return CLIToolResult(
                success=False,
                error=f"agy execution error: {exc}",
            )

        if not result.success:
            return CLIToolResult(
                success=False,
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.error or f"agy exited with code {result.exit_code}",
            )

        artifact_path = result.artifact_path
        if artifact_path is None:
            # No artifact path reported but exit code was 0
            return CLIToolResult(
                success=True,
                stdout=result.stdout,
                stderr=result.stderr,
                error="agy succeeded but no artifact path found",
            )

        # Copy artifact to out_dir if different location
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / artifact_path.name
            if artifact_path != dest:
                shutil.copy2(artifact_path, dest)
                artifact_path = dest
        except Exception as exc:
            logger.warning("Failed to copy artifact to out_dir: %s", exc)
            # Keep original path

        return CLIToolResult(
            success=True,
            artifact_path=artifact_path,
            stdout=result.stdout,
            stderr=result.stderr,
            error=None,
        )