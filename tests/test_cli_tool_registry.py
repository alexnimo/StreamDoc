"""Tests for the CLI Tool Registry and AgyCLI adapter.

These tests use mocks and do NOT call the real agy binary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamdoc.integrations.cli_tools import (
    BaseCLITool,
    CLIToolInstallStatus,
    CLIToolRegistry,
    CLIToolResult,
    registry,
)
from streamdoc.integrations.cli_tools.agy import AgyCLI


class FakeCLITool(BaseCLITool):
    """Fake tool for testing registry dispatch."""

    name = "fake"

    def __init__(self, installed: bool = True, should_fail: bool = False):
        self._installed = installed
        self._should_fail = should_fail
        self.detect_called = False
        self.run_called = False
        self.run_args = None

    def is_installed(self) -> bool:
        return self._installed

    def detect(self) -> CLIToolInstallStatus:
        self.detect_called = True
        return CLIToolInstallStatus(
            name=self.name,
            installed=self._installed,
            binary_path="/fake/path/fake" if self._installed else None,
            version="1.0.0" if self._installed else None,
            install_instructions="Install fake" if not self._installed else None,
        )

    def ensure_installed(self, prompt: bool = True) -> CLIToolInstallStatus:
        return self.detect()

    async def run(
        self,
        report_paths: list[Path],
        template: str | None,
        out_dir: Path,
    ) -> CLIToolResult:
        self.run_called = True
        self.run_args = (report_paths, template, out_dir)
        if self._should_fail:
            return CLIToolResult(
                success=False,
                error="Fake tool failed",
            )
        return CLIToolResult(
            success=True,
            artifact_path=out_dir / "output.html",
            stdout="fake output",
            stderr="",
        )


def test_registry_register_and_get():
    """Register a fake tool and assert get_tool returns it."""
    reg = CLIToolRegistry()
    reg.register("fake", FakeCLITool)

    cls = reg.get_tool("fake")
    assert cls is FakeCLITool

    # Test duplicate registration with wrong class raises
    with pytest.raises(ValueError):
        class BadTool(BaseCLITool):
            name = "bad"
        reg.register("fake", BadTool)

    # Test non-BaseCLITool subclass raises
    with pytest.raises(TypeError):
        reg.register("notatool", str)


def test_registry_list_tools():
    """list_tools returns all registered names."""
    reg = CLIToolRegistry()

    class Tool1(BaseCLITool):
        name = "tool1"

    class Tool2(BaseCLITool):
        name = "tool2"

    reg.register("tool1", Tool1)
    reg.register("tool2", Tool2)

    assert set(reg.list_tools()) == {"tool1", "tool2"}


def test_registry_instantiate():
    """instantiate creates an instance of the registered tool."""
    reg = CLIToolRegistry()
    reg.register("fake", FakeCLITool)

    tool = reg.instantiate("fake", installed=False)
    assert isinstance(tool, FakeCLITool)
    assert tool._installed is False

    # Non-existent tool returns None
    assert reg.instantiate("nonexistent") is None


def test_fake_tool_is_installed():
    """FakeCLITool.is_installed reflects constructor arg."""
    tool = FakeCLITool(installed=True)
    assert tool.is_installed() is True

    tool = FakeCLITool(installed=False)
    assert tool.is_installed() is False


def test_fake_tool_detect():
    """FakeCLITool.detect returns proper status and marks called."""
    tool = FakeCLITool(installed=True)
    status = tool.detect()

    assert tool.detect_called is True
    assert status.name == "fake"
    assert status.installed is True
    assert status.binary_path == "/fake/path/fake"
    assert status.version == "1.0.0"
    assert status.install_instructions is None


def test_fake_tool_detect_not_installed():
    """detect on uninstalled tool returns install instructions."""
    tool = FakeCLITool(installed=False)
    status = tool.detect()

    assert status.installed is False
    assert status.binary_path is None
    assert status.version is None
    assert status.install_instructions == "Install fake"


def test_fake_tool_run_success():
    """FakeCLITool.run returns success with artifact path."""
    tool = FakeCLITool(installed=True)

    async def run_test():
        return await tool.run([Path("report.pdf")], "template1", Path("/tmp/out"))

    result = asyncio.run(run_test())

    assert tool.run_called is True
    assert result.success is True
    assert result.artifact_path == Path("/tmp/out/output.html")
    assert result.stdout == "fake output"
    assert result.error is None


def test_fake_tool_run_failure():
    """FakeCLITool.run returns failure when configured to fail."""
    tool = FakeCLITool(installed=True, should_fail=True)

    async def run_test():
        return await tool.run([Path("report.pdf")], None, Path("/tmp/out"))

    result = asyncio.run(run_test())

    assert result.success is False
    assert result.error == "Fake tool failed"


@patch("streamdoc.integrations.cli_tools.agy.find_agy_binary")
@patch("streamdoc.integrations.cli_tools.agy.is_available")
@patch("streamdoc.integrations.cli_tools.agy.run_skill", new_callable=AsyncMock)
@patch("streamdoc.integrations.cli_tools.agy.agy_skills.install")
@patch("streamdoc.integrations.cli_tools.agy.PromptManager.render_prompt")
def test_agy_cli_detect(
    mock_render_prompt,
    mock_install,
    mock_run_skill,
    mock_is_available,
    mock_find_binary,
):
    """AgyCLI.detect uses find_agy_binary and subprocess for version."""
    mock_find_binary.return_value = "/usr/local/bin/agy"
    mock_is_available.return_value = True

    tool = AgyCLI()
    status = tool.detect()

    assert status.name == "agy"
    assert status.installed is True
    assert status.binary_path == "/usr/local/bin/agy"
    mock_find_binary.assert_called_once()
    # detect() calls find_agy_binary() directly, not is_available()


@patch("streamdoc.integrations.cli_tools.agy.find_agy_binary")
@patch("streamdoc.integrations.cli_tools.agy.is_available")
def test_agy_cli_detect_not_installed(mock_is_available, mock_find_binary):
    """AgyCLI.detect returns install instructions when not installed."""
    mock_is_available.return_value = False
    mock_find_binary.return_value = None

    tool = AgyCLI()
    status = tool.detect()

    assert status.name == "agy"
    assert status.installed is False
    assert status.binary_path is None
    assert status.install_instructions is not None
    assert status.install_url == "https://antigravity.google/docs/cli/install"


@patch("streamdoc.integrations.cli_tools.agy.run_skill", new_callable=AsyncMock)
@patch("streamdoc.integrations.cli_tools.agy.agy_skills.install")
@patch("streamdoc.integrations.cli_tools.agy.PromptManager.render_prompt")
@patch("streamdoc.integrations.cli_tools.agy.find_agy_binary")
@patch("streamdoc.integrations.cli_tools.agy.is_available")
def test_agy_cli_run_success(
    mock_is_available,
    mock_find_binary,
    mock_render_prompt,
    mock_install,
    mock_run_skill,
):
    """AgyCLI.run delegates to run_skill and maps result."""
    mock_is_available.return_value = True
    mock_find_binary.return_value = "/usr/local/bin/agy"
    mock_render_prompt.return_value = "test prompt"

    # Mock run_skill to return a successful result
    from streamdoc.integrations.agy.runner import AgyRunResult
    mock_run_skill.return_value = AgyRunResult(
        success=True,
        artifact_path=Path("/tmp/artifact.html"),
        stdout="agy stdout",
        stderr="",
        exit_code=0,
    )

    tool = AgyCLI()

    async def run_test():
        return await tool.run(
            report_paths=[Path("report.pdf")],
            template="web-video-presentation",
            out_dir=Path("/tmp/out"),
        )

    result = asyncio.run(run_test())

    assert result.success is True
    # Artifact copy fails silently when source doesn't exist, returns original path
    assert result.artifact_path == Path("/tmp/artifact.html")
    assert result.stdout == "agy stdout"
    mock_run_skill.assert_awaited_once()
    mock_install.assert_called_once_with("web-video-presentation")


@patch("streamdoc.integrations.cli_tools.agy.run_skill", new_callable=AsyncMock)
@patch("streamdoc.integrations.cli_tools.agy.agy_skills.install")
@patch("streamdoc.integrations.cli_tools.agy.PromptManager.render_prompt")
@patch("streamdoc.integrations.cli_tools.agy.find_agy_binary")
@patch("streamdoc.integrations.cli_tools.agy.is_available")
def test_agy_cli_run_skill_failure(
    mock_is_available,
    mock_find_binary,
    mock_render_prompt,
    mock_install,
    mock_run_skill,
):
    """AgyCLI.run returns failure when run_skill fails."""
    mock_is_available.return_value = True
    mock_find_binary.return_value = "/usr/local/bin/agy"
    mock_render_prompt.return_value = "test prompt"

    from streamdoc.integrations.agy.runner import AgyRunResult
    mock_run_skill.return_value = AgyRunResult(
        success=False,
        artifact_path=None,
        stdout="",
        stderr="agy error",
        exit_code=1,
        error="agy failed",
    )

    tool = AgyCLI()

    async def run_test():
        return await tool.run(
            report_paths=[Path("report.pdf")],
            template=None,
            out_dir=Path("/tmp/out"),
        )

    result = asyncio.run(run_test())

    assert result.success is False
    assert "agy failed" in result.error


@patch("streamdoc.integrations.cli_tools.agy.run_skill", new_callable=AsyncMock)
@patch("streamdoc.integrations.cli_tools.agy.agy_skills.install")
@patch("streamdoc.integrations.cli_tools.agy.PromptManager.render_prompt")
@patch("streamdoc.integrations.cli_tools.agy.find_agy_binary")
@patch("streamdoc.integrations.cli_tools.agy.is_available")
def test_agy_cli_run_missing_skill(
    mock_is_available,
    mock_find_binary,
    mock_render_prompt,
    mock_install,
    mock_run_skill,
):
    """AgyCLI.run returns failure when skill not found in assets."""
    mock_is_available.return_value = True
    mock_find_binary.return_value = "/usr/local/bin/agy"
    mock_install.side_effect = FileNotFoundError("Skill not found")

    tool = AgyCLI()

    async def run_test():
        return await tool.run(
            report_paths=[Path("report.pdf")],
            template="nonexistent",
            out_dir=Path("/tmp/out"),
        )

    result = asyncio.run(run_test())

    assert result.success is False
    assert "Skill not found in assets" in result.error


def test_global_registry_has_agy():
    """The module-level registry has agy registered."""
    assert "agy" in registry.list_tools()
    agy_cls = registry.get_tool("agy")
    assert agy_cls is AgyCLI


def test_convenience_functions():
    """register, get_tool, list_tools work on the global registry."""
    from streamdoc.integrations.cli_tools import register, get_tool, list_tools

    class TempTool(BaseCLITool):
        name = "temp"

    initial = set(list_tools())
    register("temp", TempTool)
    try:
        assert "temp" in list_tools()
        assert get_tool("temp") is TempTool
    finally:
        # Clean up
        registry._tools.pop("temp", None)
        assert set(list_tools()) == initial


if __name__ == "__main__":
    pytest.main([__file__, "-v"])