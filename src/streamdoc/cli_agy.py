"""CLI subcommand group for the Antigravity (agy) generation backend.

Provides ``streamdoc agy status``, ``streamdoc agy skills``, and
``streamdoc agy run <preset>`` commands. Mirrors the structure of the
``schedule`` and ``job`` groups in :mod:`streamdoc.cli` — each group is a
``@click.group`` and each leaf command is decorated with the parent group.

Usage::

    streamdoc agy status
    streamdoc agy skills list
    streamdoc agy skills install <name>
    streamdoc agy skills install --all
    streamdoc agy skills update [<name>] [--all]
    streamdoc agy run <preset>
"""
from __future__ import annotations

import subprocess
import sys

import click

from streamdoc.config import settings
from streamdoc.integrations.agy import (
    find_agy_binary,
    install,
    install_all,
    list_available,
    list_installed,
    update,
)


@click.group(
    name="agy",
    help="Antigravity (agy) generation backend: status, skills, run.",
    invoke_without_command=True,
)
@click.pass_context
def agy_group(ctx: click.Context) -> None:
    """Top-level agy group. Prints help when called with no subcommand.

    Reason: ``invoke_without_command=True`` lets us print the help text
    rather than doing nothing silently when the user runs ``streamdoc agy``
    without a subcommand. This matches Click's best-practice for groups.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@agy_group.command("status")
def agy_status() -> None:
    """Print agy binary availability, version, and installed skills."""
    binary = find_agy_binary()
    if binary is None:
        click.echo("Antigravity: not installed")
        return

    click.echo(f"Antigravity: installed at {binary}")

    # Reason: try to read a version string from the binary. Any failure
    # (binary not executable, --version flag not supported, timeout) should
    # fall back gracefully rather than crash the status command.
    version = "(unknown)"
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        if first_line:
            version = first_line
    except Exception:
        pass
    click.echo(f"Version: {version}")

    installed = list_installed()
    if installed:
        click.echo(f"Installed skills ({len(installed)}):")
        for s in installed:
            click.echo(f"  - {s.name}")
    else:
        click.echo("Installed skills: none")


# ---------------------------------------------------------------------------
# skills (sub-group)
# ---------------------------------------------------------------------------

@agy_group.group("skills")
def skills_group() -> None:
    """Manage agy skills: list, install, update."""


@skills_group.command("list")
def skills_list() -> None:
    """List available skills with their installation status."""
    available = list_available()
    if not available:
        click.echo("No skills found in assets/skills/agy/ (T5 asset drop not yet present).")
        return

    installed_names = {s.name for s in list_installed()}

    # Reason: compute column width from the longest skill name so the two
    # columns line up neatly regardless of name length.
    col_width = max(len(s.name) for s in available) if available else 0

    click.echo(f"{'Skill':<{col_width}}  Status")
    click.echo("-" * (col_width + 10))
    for s in sorted(available, key=lambda x: x.name):
        status_glyph = "✓ installed" if s.name in installed_names else "✗ not installed"
        click.echo(f"{s.name:<{col_width}}  {status_glyph}")


@skills_group.command("install")
@click.argument("name", required=False, default=None)
@click.option("--all", "install_all_flag", is_flag=True, help="Install every available skill.")
def skills_install(name: str | None, install_all_flag: bool) -> None:
    """Install one or all agy skills from the vendored assets.

    Examples::

        streamdoc agy skills install web-video-presentation
        streamdoc agy skills install --all
    """
    if install_all_flag:
        installed_paths = install_all()
        if not installed_paths:
            click.echo("No skills to install (assets/skills/agy/ is empty or missing).")
            return
        for dest in installed_paths:
            click.echo(f"Installed: {dest}")
        return

    if not name:
        raise click.UsageError("Provide a skill name or use --all to install everything.")

    try:
        dest = install(name)
        click.echo(f"Installed: {dest}")
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise click.ClickException(f"Skill {name!r} not found in vendored assets.") from exc


@skills_group.command("update")
@click.argument("name", required=False, default=None)
@click.option("--all", "update_all_flag", is_flag=True, help="Update every installed skill.")
def skills_update(name: str | None, update_all_flag: bool) -> None:
    """Re-install one or all skills from the vendored assets (force overwrite).

    Reason: ``update`` is semantically ``install(..., force=True)`` — it
    overwrites the destination with the latest vendored version. The same
    source tree is used; this is idempotent with respect to the version
    shipped in the current checkout.

    Examples::

        streamdoc agy skills update web-video-presentation
        streamdoc agy skills update --all
    """
    if update_all_flag:
        # Reason: update(name=None) calls install_all() with force=True
        # semantics, which now returns the list of installed destination paths.
        result = update(name=None)
        paths = result if isinstance(result, list) else [result]
        if not paths:
            click.echo("No skills updated (assets/skills/agy/ is empty or missing).")
            return
        for p in paths:
            click.echo(f"Updated: {p}")
        return

    if not name:
        raise click.UsageError("Provide a skill name or use --all to update everything.")

    try:
        result = update(name=name)
        click.echo(f"Updated: {result}")
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise click.ClickException(f"Skill {name!r} not found in vendored assets.") from exc


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@agy_group.command("run")
@click.argument("preset", required=True)
def agy_run(preset: str) -> None:
    """Run agy against an existing preset's latest reports.

    Loads the preset from the database by ID, resolves the prompt via the
    configured template or prompt_md, invokes the agy skill, and prints the
    resulting artifact path and here.now URL (if published).

    Example::

        streamdoc agy run my-preset
    """
    # Reason: lazy imports keep startup fast and match the style used by
    # the schedule/job commands in cli.py. The DB is only initialised when
    # this command is actually executed.
    from streamdoc.db import init_db
    from streamdoc.presets import load_preset, prompt_args_for_preset

    init_db()

    try:
        loaded_preset = load_preset(preset)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    # Reason: upload_to_agy needs a job_id for log correlation; we use a
    # placeholder string since the CLI run doesn't create a full pipeline job.
    job_id = f"cli-agy-{preset}"

    from streamdoc.async_utils import run_async
    from streamdoc.core.agy_upload import _DEFAULT_AGY_CONTENT_TYPE, upload_to_agy
    from streamdoc.core.fetch import _design_prompt_for_preset

    prompt_args = prompt_args_for_preset(loaded_preset, "agy")

    # Resolve source PDFs for this preset.
    from pathlib import Path
    out_dir = Path(settings.output_root) / loaded_preset.name
    if not out_dir.exists():
        raise click.ClickException(
            f"No output directory found for preset {preset!r} at {out_dir}. "
            "Run 'streamdoc fetch' first."
        )
    report_paths = sorted(
        p for p in out_dir.glob("*.pdf") if p.stem != "FULL_REPORT"
    )
    if not report_paths:
        raise click.ClickException(
            f"No PDF reports found in {out_dir}. Run 'streamdoc fetch' first."
        )

    result = run_async(upload_to_agy(
        report_paths=report_paths,
        preset_name=loaded_preset.name,
        job_id=job_id,
        skill=getattr(loaded_preset, "agy_skill", None),
        model=getattr(loaded_preset, "agy_model", None),
        prompt_template=prompt_args["prompt_template"],
        custom_prompt=prompt_args["custom_prompt"],
        design_prompt=_design_prompt_for_preset(loaded_preset, _DEFAULT_AGY_CONTENT_TYPE),
        publish_herenow=getattr(loaded_preset, "agy_publish_herenow", False),
    ))

    if not result.success:
        error_msg = "; ".join(result.errors) if result.errors else "agy upload failed"
        click.echo(f"Error: {error_msg}", err=True)
        sys.exit(1)

    click.echo("Success!")
    if result.artifact_path:
        click.echo(f"Artifact: {result.artifact_path}")
    if result.herenow_url:
        click.echo(f"Published: {result.herenow_url}")
    if result.errors:
        # Reason: non-fatal errors (e.g. publish step failed but content
        # was produced) should be surfaced so the operator can investigate.
        for err in result.errors:
            click.echo(f"Warning: {err}", err=True)


__all__ = ["agy_group"]
