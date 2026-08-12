from __future__ import annotations

import logging

import click

from streamdoc.core.fetch import run_fetch
from streamdoc.db import init_db

logger = logging.getLogger(__name__)


@click.group()
def main() -> None:
    pass


# Import and add NotebookLM commands
try:
    from streamdoc.cli_notebooklm import notebooklm_group
    main.add_command(notebooklm_group)
except ImportError:
    pass  # NotebookLM not available

# Import and add Antigravity (agy) commands
try:
    from streamdoc.cli_agy import agy_group
    main.add_command(agy_group)
except ImportError:
    pass  # agy not available


@main.command()
@click.argument("preset")
@click.option("--lookback-hours", type=int, default=None, help="Override preset lookback window.")
def fetch(preset: str, lookback_hours: int | None) -> None:
    """Fetch media for a preset."""
    init_db()
    policy = None
    if lookback_hours is not None:
        from streamdoc.core.fetch import FetchPolicy
        policy = FetchPolicy(lookback_hours=lookback_hours)
    try:
        artifacts = run_fetch(preset, policy=policy)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Processed {len(artifacts)} artifact(s).")


@main.group()
def schedule() -> None:
    pass


@schedule.command("list")
def schedule_list() -> None:
    from streamdoc.scheduler import list_jobs
    jobs = list_jobs()
    if not jobs:
        click.echo("No scheduled jobs.")
        return
    for job in jobs:
        click.echo(f"{job['id']} | {job['preset']} | trigger={job['trigger']}")


@schedule.command("add")
@click.argument("preset")
@click.argument("schedule")
def schedule_add(preset: str, schedule: str) -> None:
    from streamdoc.scheduler import add_job
    job = add_job(preset, schedule)
    click.echo(f"Added {job['id']}")


@schedule.command("remove")
@click.argument("preset")
def schedule_remove(preset: str) -> None:
    from streamdoc.scheduler import remove_job
    remove_job(preset)
    click.echo(f"Removed job for preset={preset}")


@schedule.command("run")
@click.argument("preset")
def schedule_run_once(preset: str) -> None:
    from streamdoc.scheduler import run_once
    run_once(preset)
    click.echo(f"Ran preset={preset}")


@main.command()
def update() -> None:
    """Update runtime tools (yt-dlp / ffmpeg / whisper)."""
    click.echo("No auto-updater wired yet.")


@main.group()
def job() -> None:
    """Job tracking: list, retry, resend."""
    pass


@job.command("list")
@click.option("--limit", type=int, default=20, help="Number of jobs to show.")
def job_list(limit: int) -> None:
    """List recent jobs."""
    from streamdoc.core.jobs import list_jobs
    init_db()
    jobs = list_jobs(limit=limit)
    if not jobs:
        click.echo("No jobs found.")
        return
    click.echo(f"{'Job ID':<12} {'Preset':<20} {'Status':<12} {'Created':<22} {'Artifacts':<10}")
    click.echo("-" * 80)
    for j in jobs:
        click.echo(
            f"{j['id']:<12} {j['preset_name']:<20} {j['status']:<12} "
            f"{j['created_at']:<22} {j['artifact_count']:<10}"
        )
        errs = j.get('errors', [])
        if errs:
            for e in errs:
                click.echo(f"  ⚠ {e}")


@job.command("retry")
@click.argument("job_id")
def job_retry(job_id: str) -> None:
    """Retry failed destinations for a job."""
    from streamdoc.core.jobs import retry_job
    init_db()
    try:
        results = retry_job(job_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    for dest, result in results.items():
        emoji = "✓" if result.startswith("success") else "✗"
        click.echo(f"{emoji} {dest}: {result}")


@job.command("resend")
@click.argument("job_id")
@click.option("--destination", required=True, help="Destination to resend to (e.g. notebooklm).")
def job_resend(job_id: str, destination: str) -> None:
    """Resend a job's reports to a new destination."""
    from streamdoc.core.jobs import resend_job
    init_db()
    try:
        results = resend_job(job_id, destination)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    for dest, result in results.items():
        emoji = "✓" if result.startswith("success") else "✗"
        click.echo(f"{emoji} {dest}: {result}")


@main.command()
@click.option("--dry-run", is_flag=True, help="Log what would be deleted without deleting.")
def cleanup(dry_run: bool) -> None:
    """Run retention cleanup manually."""
    from streamdoc.core.cleanup import run_cleanup
    init_db()
    counts = run_cleanup(dry_run=dry_run)
    if not counts:
        click.echo("Nothing to clean up.")
        return
    for key, val in counts.items():
        click.echo(f"{key}: {val}")


if __name__ == "__main__":
    main()
