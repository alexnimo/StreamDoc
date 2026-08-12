"""CLI Tool Integration Layer.

Pluggable abstraction for CLI-based generation backends (agy, Claude Code, Codex, etc.).
"""

from __future__ import annotations

from streamdoc.integrations.cli_tools.base import (
    BaseCLITool,
    CLIToolInstallStatus,
    CLIToolRegistry,
    CLIToolResult,
    find_binary,
)
from streamdoc.integrations.cli_tools.agy import AgyCLI

# Module-level registry singleton
registry = CLIToolRegistry()

# Register built-in tools
registry.register(AgyCLI.name, AgyCLI)

# Convenience functions
def register(name: str, cls: type[BaseCLITool]) -> None:
    """Register a CLI tool class."""
    registry.register(name, cls)


def get_tool(name: str) -> BaseCLITool | None:
    """Get a CLI tool instance by name."""
    return registry.get_tool(name)


def list_tools() -> list[str]:
    """List registered tool names."""
    return registry.list_tools()


__all__ = [
    "BaseCLITool",
    "CLIToolInstallStatus",
    "CLIToolRegistry",
    "CLIToolResult",
    "find_binary",
    "registry",
    "register",
    "get_tool",
    "list_tools",
    "AgyCLI",
]