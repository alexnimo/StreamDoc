"""API routes for CLI Tool management.

Provides endpoints to list, detect, and get installation guidance for
registered CLI tools (agy, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import CLIToolInstallStatusOut, CLIToolOut
from streamdoc.integrations.cli_tools import registry

router = APIRouter(prefix="/cli-tools", tags=["cli-tools"])


@router.get("", response_model=list[CLIToolOut])
def list_cli_tools() -> list[CLIToolOut]:
    """List all registered CLI tools with their install status."""
    tools = []
    for name in registry.list_tools():
        cls = registry.get_tool(name)
        if cls is None:
            continue
        tool = cls()
        status = tool.detect()
        tools.append(
            CLIToolOut(
                name=status.name,
                installed=status.installed,
                binary_path=status.binary_path,
                version=status.version,
                install_instructions=status.install_instructions,
                install_url=status.install_url,
            )
        )
    return tools


@router.post("/{name}/detect", response_model=CLIToolInstallStatusOut)
def detect_cli_tool(name: str) -> CLIToolInstallStatusOut:
    """Run detailed detection for a specific CLI tool."""
    cls = registry.get_tool(name)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"CLI tool '{name}' not registered")
    tool = cls()
    status = tool.detect()
    return CLIToolInstallStatusOut(
        name=status.name,
        installed=status.installed,
        binary_path=status.binary_path,
        version=status.version,
        install_instructions=status.install_instructions,
        install_url=status.install_url,
    )


@router.post("/{name}/install", response_model=CLIToolInstallStatusOut)
def install_cli_tool(name: str) -> CLIToolInstallStatusOut:
    """Get installation guidance for a CLI tool.

    Does NOT auto-install third-party binaries; returns instructions
    for the operator to run manually.
    """
    cls = registry.get_tool(name)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"CLI tool '{name}' not registered")
    tool = cls()
    status = tool.ensure_installed(prompt=False)
    return CLIToolInstallStatusOut(
        name=status.name,
        installed=status.installed,
        binary_path=status.binary_path,
        version=status.version,
        install_instructions=status.install_instructions,
        install_url=status.install_url,
    )