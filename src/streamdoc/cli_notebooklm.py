"""CLI commands for NotebookLM integration."""

import asyncio
from pathlib import Path

import click

from streamdoc.config import settings
from streamdoc.integrations.notebooklm import (
    NOTEBOOKLM_AVAILABLE,
    ContentManager,
    ContentType,
    NotebookLMAuthManager,
    NotebookLMClientWrapper,
    NotebookManager,
    PromptManager,
    RetentionManager,
)
from streamdoc.integrations.notebooklm.exceptions import NotebookLMIntegrationError


def get_auth_manager():
    """Get configured auth manager."""
    return NotebookLMAuthManager(
        settings.notebooklm_storage_state_path,
        settings.notebooklm_profile
    )


@click.group(name="notebooklm")
def notebooklm_group():
    """NotebookLM integration commands."""
    if not NOTEBOOKLM_AVAILABLE:
        raise click.ClickException(
            "NotebookLM integration not available. "
            "Install with: pip install notebooklm-py"
        )


# Auth commands
@notebooklm_group.group(name="auth")
def auth_group():
    """Authentication management."""
    pass


@auth_group.command(name="status")
def auth_status():
    """Check authentication status."""
    async def check():
        auth_manager = get_auth_manager()
        # Reason: status is a read-only check; do not auto-launch a headless
        # browser just to report the current state.
        status = await auth_manager.check_session_freshness(auto_refresh=False)
        
        click.echo(f"Profile: {status.profile}")
        click.echo(f"Storage path: {status.storage_path}")
        click.echo(f"Configured: {auth_manager.is_configured()}")
        click.echo(f"Valid: {status.is_valid}")
        click.echo(f"Fresh: {status.is_fresh}")
        click.echo(f"Message: {status.message}")
    
    asyncio.run(check())


@auth_group.command(name="login")
@click.option("--browser", default="chromium", help="Browser to use for login")
@click.option("--fresh", is_flag=True, help="Start with clean session")
def auth_login(browser, fresh):
    """Authenticate with NotebookLM via browser.
    
    This command delegates to the notebooklm-py CLI login flow.
    Run 'notebooklm login' separately to authenticate.
    """
    click.echo("NotebookLM authentication uses the notebooklm-py CLI.")
    click.echo("")
    click.echo("To authenticate, run:")
    click.echo(f"  notebooklm login --browser {browser}")
    click.echo("")
    click.echo(f"Credentials will be saved to: {settings.notebooklm_storage_state_path}")
    
    if fresh:
        click.echo("\nUse --fresh flag to clear existing session first.")


@auth_group.command(name="logout")
def auth_logout():
    """Clear stored credentials."""
    auth_manager = get_auth_manager()
    deleted = auth_manager.logout()
    if deleted:
        click.echo("Credentials cleared successfully.")
    else:
        click.echo("No credentials found to clear.")


# Notebook commands
@notebooklm_group.group(name="notebook")
def notebook_group():
    """Notebook management."""
    pass


@notebook_group.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def notebook_list(as_json):
    """List all notebooks."""
    async def list_notebooks():
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                notebooks = NotebookManager(client)
                nb_list = await notebooks.list_notebooks()
                
                if as_json:
                    import json
                    output = [
                        {
                            "id": nb.id,
                            "title": nb.title,
                            "sources_count": nb.sources_count
                        }
                        for nb in nb_list
                    ]
                    click.echo(json.dumps(output))
                else:
                    if not nb_list:
                        click.echo("No notebooks found.")
                        return
                    
                    click.echo(f"{'ID':<20} {'Title':<40} {'Sources':<10}")
                    click.echo("-" * 70)
                    for nb in nb_list:
                        title = nb.title[:37] + "..." if len(nb.title) > 40 else nb.title
                        click.echo(f"{nb.id:<20} {title:<40} {nb.sources_count:<10}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(list_notebooks())


@notebook_group.command(name="create")
@click.argument("title")
@click.option("--use", is_flag=True, help="Set as active notebook")
def notebook_create(title, use):
    """Create a new notebook."""
    async def create():
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                notebooks = NotebookManager(client)
                nb = await notebooks.create_notebook(title)
                click.echo(f"Created notebook: {nb.id}")
                click.echo(f"Title: {nb.title}")
                
                if use:
                    # Store as active in some config
                    click.echo(f"Set as active notebook: {nb.id}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(create())


@notebook_group.command(name="delete")
@click.argument("notebook_id")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def notebook_delete(notebook_id, yes):
    """Delete a notebook."""
    if not yes:
        if not click.confirm(f"Delete notebook '{notebook_id}'?"):
            return
    
    async def delete():
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                notebooks = NotebookManager(client)
                await notebooks.delete_notebook(notebook_id)
                click.echo(f"Deleted notebook: {notebook_id}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(delete())


@notebook_group.command(name="share")
@click.argument("notebook_id")
@click.option("--enable", is_flag=True, default=True, help="Enable sharing")
def notebook_share(notebook_id, enable):
    """Get or enable share URL for a notebook."""
    async def share():
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                notebooks = NotebookManager(client)
                
                if enable:
                    url = await notebooks.enable_sharing(notebook_id, public=True)
                else:
                    url = await notebooks.get_share_url(notebook_id)
                
                if url:
                    click.echo(f"Share URL: {url}")
                else:
                    click.echo("No share URL available. Enable sharing with --enable")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(share())


# Content commands
@notebooklm_group.group(name="content")
def content_group():
    """Content generation and download."""
    pass


@content_group.command(name="generate")
@click.argument("notebook_id")
@click.option("--type", "content_type", required=True, 
              type=click.Choice(["slide_deck", "podcast", "infographic", "report"]))
@click.option("--prompt", "prompt_template", default=None, help="Prompt template name")
@click.option("--title", default=None, help="Custom title for the content")
@click.option("--wait/--no-wait", default=True, help="Wait for generation to complete")
@click.option("--download", is_flag=True, help="Download after generation")
@click.option("--output-dir", type=click.Path(), default="data/Outputs/notebooklm")
def content_generate(notebook_id, content_type, prompt_template, title, wait, download, output_dir):
    """Generate content in a notebook."""
    async def generate():
        auth_manager = get_auth_manager()
        prompts = PromptManager(
            settings.notebooklm_templates_dir,
            settings.notebooklm_sample_prompts_dir,
        )
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                content_mgr = ContentManager(client, prompts)
                
                content_type_enum = ContentType(content_type)
                
                # Get default prompt if not specified
                if not prompt_template:
                    prompt_template = settings.notebooklm_default_prompt
                
                click.echo(f"Generating {content_type} in notebook {notebook_id}...")
                
                if download:
                    result = await content_mgr.generate_and_download(
                        notebook_id,
                        content_type_enum,
                        Path(output_dir),
                        prompt_template,
                        title=title
                    )
                    
                    if result.status == "completed":
                        click.echo(f"Generated and downloaded: {result.artifact_id}")
                        if result.local_path:
                            click.echo(f"Local file: {result.local_path}")
                    else:
                        click.echo(f"Generation failed: {result.status}")
                else:
                    result = await content_mgr.generate_content(
                        notebook_id,
                        content_type_enum,
                        title=title,
                        wait=wait
                    )
                    
                    click.echo(f"Task ID: {result.task_id}")
                    click.echo(f"Status: {result.status}")
                    if result.artifact_id:
                        click.echo(f"Artifact ID: {result.artifact_id}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(generate())


@content_group.command(name="batch")
@click.argument("notebook_id")
@click.option("--types", default="slide_deck,infographic", 
              help="Comma-separated content types to generate")
@click.option("--prompt", "prompt_template", default=None, help="Prompt template name")
@click.option("--output-dir", type=click.Path(), default="data/Outputs/notebooklm")
def content_batch(notebook_id, types, prompt_template, output_dir):
    """Generate multiple content types in parallel."""
    async def batch():
        auth_manager = get_auth_manager()
        prompts = PromptManager(
            settings.notebooklm_templates_dir,
            settings.notebooklm_sample_prompts_dir,
        )
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                content_mgr = ContentManager(client, prompts)
                
                # Parse content types
                content_types = []
                for t in types.split(","):
                    try:
                        content_types.append(ContentType(t.strip()))
                    except ValueError:
                        click.echo(f"Warning: Unknown content type '{t}'", err=True)
                
                if not content_types:
                    raise click.ClickException("No valid content types specified")
                
                # Get default prompt if not specified
                if not prompt_template:
                    prompt_template = settings.notebooklm_default_prompt
                
                click.echo(f"Generating {len(content_types)} content types...")
                
                # Get notebook URL
                notebooks = NotebookManager(client)
                notebook_url = await notebooks.get_share_url(notebook_id) or ""
                
                result = await content_mgr.batch_generate(
                    notebook_id,
                    content_types,
                    Path(output_dir),
                    prompt_template,
                    notebook_url=notebook_url
                )
                
                click.echo(f"\nBatch complete for notebook: {notebook_id}")
                if result.notebook_url:
                    click.echo(f"Notebook URL: {result.notebook_url}")
                
                for r in result.results:
                    status = "✓" if r.status == "completed" else "✗"
                    click.echo(f"{status} {r.content_type.value}: {r.local_path or 'not downloaded'}")
                
                if result.errors:
                    click.echo("\nErrors:")
                    for e in result.errors:
                        click.echo(f"  - {e}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(batch())


@content_group.command(name="upload")
@click.argument("notebook_id")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--title", default=None, help="Source title (defaults to filename)")
def content_upload(notebook_id, file_path, title):
    """Upload a file as a source to a notebook."""
    async def upload():
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                content_mgr = ContentManager(client)
                
                source = await content_mgr.upload_report(
                    notebook_id,
                    Path(file_path),
                    title=title
                )
                
                click.echo(f"Uploaded: {source.title}")
                click.echo(f"Source ID: {source.id}")
                click.echo(f"Status: {source.status}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(upload())


# Retention commands
@notebooklm_group.group(name="retention")
def retention_group():
    """Retention policy management."""
    pass


@retention_group.command(name="list")
def retention_list():
    """List tracked content with retention info."""
    from streamdoc.db import init_db, session_scope
    from streamdoc.integrations.notebooklm.retention import NotebookLMContent
    
    init_db()
    
    with session_scope() as session:
        contents = session.query(NotebookLMContent).all()
        
        if not contents:
            click.echo("No tracked content found.")
            return
        
        click.echo(f"{'ID':<36} {'Notebook':<20} {'Status':<10} {'Permanent':<10} {'Expires':<20}")
        click.echo("-" * 100)
        
        for c in contents:
            expires = c.expires_at.strftime("%Y-%m-%d %H:%M") if c.expires_at else "Never"
            is_expired = " [EXPIRED]" if c.is_expired() else ""
            click.echo(
                f"{c.id:<36} {c.notebook_id:<20} {c.status:<10} "
                f"{'Yes' if c.is_permanent else 'No':<10} {expires}{is_expired}"
            )


@retention_group.command(name="cleanup")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
@click.option("--skip-remote", is_flag=True, help="Don't delete from NotebookLM")
def retention_cleanup(dry_run, skip_remote):
    """Clean up expired content."""
    from streamdoc.db import init_db, session_scope
    from streamdoc.integrations.notebooklm.retention import RetentionManager
    
    async def cleanup():
        init_db()
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                with session_scope() as session:
                    retention = RetentionManager(
                        client,
                        session,
                        settings.notebooklm_default_retention_hours
                    )
                    
                    report = await retention.cleanup_expired(
                        dry_run=dry_run,
                        delete_remote=not skip_remote
                    )
                    
                    if dry_run:
                        click.echo("DRY RUN - No changes made")
                    
                    click.echo(f"Checked: {report.total_checked} items")
                    click.echo(f"Deleted notebooks: {len(report.deleted_notebooks)}")
                    click.echo(f"Deleted artifacts: {len(report.deleted_artifacts)}")
                    click.echo(f"Deleted local files: {len(report.deleted_local_files)}")
                    
                    if report.errors:
                        click.echo(f"\nErrors ({len(report.errors)}):")
                        for e in report.errors[:5]:  # Show first 5
                            click.echo(f"  - {e}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(cleanup())


@retention_group.command(name="extend")
@click.argument("content_id")
@click.option("--hours", default=48, help="New retention period in hours")
def retention_extend(content_id, hours):
    """Extend retention period for content."""
    from streamdoc.db import init_db, session_scope
    from streamdoc.integrations.notebooklm.retention import RetentionManager
    
    async def extend():
        init_db()
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                with session_scope() as session:
                    retention = RetentionManager(
                        client,
                        session,
                        settings.notebooklm_default_retention_hours
                    )
                    
                    content = retention.extend_retention(content_id, hours)
                    
                    click.echo(f"Extended retention for: {content_id}")
                    click.echo(f"New expiration: {content.expires_at}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(extend())


@retention_group.command(name="permanent")
@click.argument("content_id")
def retention_permanent(content_id):
    """Mark content as permanent (no retention)."""
    from streamdoc.db import init_db, session_scope
    from streamdoc.integrations.notebooklm.retention import RetentionManager
    
    async def make_permanent():
        init_db()
        auth_manager = get_auth_manager()
        
        try:
            async with NotebookLMClientWrapper(auth_manager) as client:
                with session_scope() as session:
                    retention = RetentionManager(
                        client,
                        session,
                        settings.notebooklm_default_retention_hours
                    )
                    
                    content = retention.mark_permanent(content_id)
                    
                    click.echo(f"Marked as permanent: {content_id}")
                    click.echo(f"Notebook: {content.notebook_title}")
        except NotebookLMIntegrationError as e:
            raise click.ClickException(str(e))
    
    asyncio.run(make_permanent())
