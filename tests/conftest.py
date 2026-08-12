"""Shared test infrastructure for the POR-27 T6 test suite.

Exposes reusable helpers for mocking subprocess invocations consistently
across the agy runner, skills, herenow, and notify tests. Also registers
the ``live`` marker that gates opt-in integration tests.

Usage in a sibling test file::

    def test_foo(make_fake_subprocess, monkeypatch, tmp_path):
        # Create a mock subprocess in 1-2 lines.
        patcher, proc = make_fake_subprocess(
            returncode=0, stdout=b"Artifact: /tmp/x.html\\n", stderr=b""
        )
        monkeypatch.setattr("asyncio.create_subprocess_exec", patcher)
        # ... run code under test ...
        assert patcher.call_args.args[0] == "/fake/agy"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# pytest configuration
# ---------------------------------------------------------------------------

pytest_plugins: list[str] = []


def pytest_configure(config: Any) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "live: tests that require network access and working yt-dlp",
    )


# ---------------------------------------------------------------------------
# Shared mock-subprocess helpers
# ---------------------------------------------------------------------------


class FakeProcess:
    """Minimal stand-in for ``asyncio.subprocess.Process``.

    The runner only ever calls ``communicate()`` (awaitable) and
    ``kill()`` / ``wait()`` on it, so we just need those four methods
    plus a ``returncode`` attribute.  ``stdout`` / ``stderr`` are not
    consumed by the runner (it reads from ``communicate()``'s return
    value), so we leave them as None.

    Attributes:
        returncode: The exit code the process reports.
        killed: True after ``kill()`` was called.
        waited: True after ``wait()`` was called.
    """

    def __init__(
        self,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
        communicate_raises: BaseException | None = None,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._communicate_raises = communicate_raises
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._communicate_raises is not None:
            raise self._communicate_raises
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return 0


async def _await_fake(process: FakeProcess) -> FakeProcess:
    """Coroutine that returns a fake process.

    The production code does ``await asyncio.create_subprocess_exec(...)``,
    so the patched symbol must be callable returning an awaitable.
    Wrapping the fake in this trivial async function makes the
    await chain type-correct.
    """
    return process


def _make_fake_subprocess_impl(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    communicate_raises: BaseException | None = None,
) -> tuple[Any, FakeProcess]:
    """Build a patched ``asyncio.create_subprocess_exec`` that returns a fake.

    Returns a ``(patcher, process)`` tuple so the test can::

        patcher, proc = make_fake_subprocess(returncode=0, stdout=b"...")
        monkeypatch.setattr("asyncio.create_subprocess_exec", patcher)
        # ... run code ...
        assert patcher.call_args is not None
        assert proc.killed is True

    The patcher captures every call's args so tests can assert the
    exact command shape via ``patcher.call_args``.
    """
    process = FakeProcess(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        communicate_raises=communicate_raises,
    )
    patcher = MagicMock(side_effect=lambda *a, **kw: _await_fake(process))
    return patcher, process


# ---------------------------------------------------------------------------
# pytest fixtures (auto-discovered — no import needed)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pot_effective_mode() -> Any:
    """Reset the POT provider's effective bypass mode before each test.

    Reason: ``pot_provider._effective_bypass_mode`` is a module-level
    cache that persists across tests. Without resetting, a test that
    triggers a fallback would leak its effective mode into subsequent
    tests, causing them to use the wrong bypass mode.
    """
    from streamdoc.core import pot_provider

    pot_provider._effective_bypass_mode = None
    pot_provider._we_started_container = False
    yield
    pot_provider._effective_bypass_mode = None
    pot_provider._we_started_container = False


@pytest.fixture
def make_fake_subprocess() -> Any:
    """Fixture that returns the ``_make_fake_subprocess_impl`` factory.

    Usage in a test::

        def test_foo(make_fake_subprocess, monkeypatch):
            patcher, proc = make_fake_subprocess(returncode=0, stdout=b"...")
            monkeypatch.setattr("asyncio.create_subprocess_exec", patcher)
            # ... run code ...
            assert patcher.call_args is not None
    """
    return _make_fake_subprocess_impl
