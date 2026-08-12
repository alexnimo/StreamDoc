"""Base classes and data structures for the CLI Tool Integration Layer."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CLIToolInstallStatus:
    """Result of detecting/installing a CLI tool.

    Attributes:
        name: Tool identifier (e.g., "agy").
        installed: True if the binary is available on PATH.
        binary_path: Absolute path to the binary if found.
        version: Version string if detectable.
        install_instructions: Human-readable install guidance (None if installed).
        install_url: Optional URL to official install documentation.
    """

    name: str
    installed: bool
    binary_path: str | None = None
    version: str | None = None
    install_instructions: str | None = None
    install_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "installed": self.installed,
            "binary_path": self.binary_path,
            "version": self.version,
            "install_instructions": self.install_instructions,
            "install_url": self.install_url,
        }


@dataclass
class CLIToolResult:
    """Result of running a CLI tool against report files.

    Attributes:
        success: True if the tool completed successfully and produced an artifact.
        artifact_path: Path to the generated output file (HTML, PDF, etc.).
        stdout: Raw stdout from the tool.
        stderr: Raw stderr from the tool.
        error: Human-readable error message on failure.
    """

    success: bool
    artifact_path: Path | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


class BaseCLITool(ABC):
    """Abstract base class for pluggable CLI tool integrations.

    Each concrete tool (agy, claude-code, codex, etc.) implements this interface.
    The registry uses these to dispatch destination sends generically.
    """

    # Class attribute: unique tool identifier
    name: str

    @abstractmethod
    def is_installed(self) -> bool:
        """Fast check: is the tool binary available on PATH?

        Returns:
            True if the tool can be invoked immediately.
        """

    @abstractmethod
    def detect(self) -> CLIToolInstallStatus:
        """Detailed detection of the tool.

        Returns:
            CLIToolInstallStatus with binary_path, version, and install instructions.
        """

    @abstractmethod
    def ensure_installed(self, prompt: bool = True) -> CLIToolInstallStatus:
        """Return installation guidance; does NOT auto-install third-party binaries.

        Args:
            prompt: If True, return user-friendly instructions. If False,
                    return non-interactive/CI-friendly guidance.

        Returns:
            CLIToolInstallStatus with install_instructions populated if not installed.
        """

    @abstractmethod
    async def run(
        self,
        report_paths: list[Path],
        template: str | None,
        out_dir: Path,
    ) -> CLIToolResult:
        """Run the CLI tool against the given report files.

        Args:
            report_paths: Source files to process (PDF, Markdown, etc.).
            template: Tool-specific template/skill identifier. If None, uses
                      the tool's default.
            out_dir: Directory where the tool should write its output artifact.

        Returns:
            CLIToolResult with artifact_path on success, error details on failure.
        """


class CLIToolRegistry:
    """Registry for BaseCLITool implementations.

    Allows dynamic registration and lookup of CLI tool adapters.
    """

    def __init__(self) -> None:
        self._tools: dict[str, type[BaseCLITool]] = {}

    def register(self, name: str, cls: type[BaseCLITool]) -> None:
        """Register a CLI tool class.

        Args:
            name: Tool identifier (must match cls.name).
            cls: Subclass of BaseCLITool.

        Raises:
            TypeError: If cls is not a BaseCLITool subclass.
            ValueError: If cls.name != name.
        """
        if not issubclass(cls, BaseCLITool):
            raise TypeError(f"{cls} must be a subclass of BaseCLITool")
        if cls.name != name:
            raise ValueError(f"Tool class name '{cls.name}' must match registry key '{name}'")
        self._tools[name] = cls

    def get_tool(self, name: str) -> type[BaseCLITool] | None:
        """Get a registered tool class by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def instantiate(self, name: str, **kwargs: Any) -> BaseCLITool | None:
        """Create an instance of a registered tool."""
        cls = self.get_tool(name)
        if cls is None:
            return None
        return cls(**kwargs)


def find_binary(name: str) -> str | None:
    """Find a binary on PATH using shutil.which."""
    import shutil
    return shutil.which(name)


__all__ = [
    "BaseCLITool",
    "CLIToolRegistry",
    "CLIToolInstallStatus",
    "CLIToolResult",
    "find_binary",
]