"""Thread-safe utilities for running async code from synchronous contexts.

Problem: ``asyncio.run()`` creates and destroys a new event loop each call.
When called from multiple threads simultaneously (e.g., parallel preset
jobs running in FastAPI's thread pool), this causes:
- ``RuntimeError: asyncio.run() cannot be called from a running event loop``
- Race conditions in event loop creation
- Potential deadlocks

Solution: A single shared event loop running in a dedicated background thread.
All async calls from sync contexts submit coroutines to this loop via
``run_coroutine_threadsafe()`` and wait for the result.

This is the recommended pattern from the Python asyncio docs for
"calling async code from threads that don't have an event loop".
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Reason: module-level singletons for the shared event loop and its thread.
# The lock protects initialization; once started, the loop runs in its own
# thread and accepts coroutines via run_coroutine_threadsafe (which is
# explicitly thread-safe per the asyncio docs).
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Get or create the shared background event loop.

    Returns:
        The shared asyncio event loop running in a dedicated thread.
    """
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop

        # Reason: create a new event loop in a dedicated daemon thread.
        # Daemon thread means it won't prevent process exit.
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop_runner,
            args=(_loop,),
            name="streamdoc-async-loop",
            daemon=True,
        )
        _loop_thread.start()
        logger.debug("Shared async event loop started in background thread")
        return _loop


def _loop_runner(loop: asyncio.AbstractEventLoop) -> None:
    """Run the event loop until the process exits.

    Args:
        loop: The event loop to run.
    """
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    except Exception as exc:
        logger.error("Shared async event loop crashed: %s", exc, exc_info=True)
    finally:
        try:
            loop.close()
        except Exception:
            pass


def run_async(coro: Awaitable[T]) -> T:
    """Run a coroutine from a synchronous context, thread-safely.

    This replaces ``asyncio.run()`` for all calls made from background
    threads (e.g., preset jobs running in FastAPI's thread pool).

    Args:
        coro: A coroutine to execute on the shared event loop.

    Returns:
        The result of the coroutine.

    Raises:
        Any exception raised by the coroutine.
    """
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    # Reason: wait indefinitely — the caller's thread is already blocking
    # (it's a background job thread, not the main event loop).
    return future.result()


def shutdown_async_loop() -> None:
    """Shut down the shared event loop.

    Intended to be called on application shutdown.
    """
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            _loop.call_soon_threadsafe(_loop.stop)
        if _loop_thread is not None:
            _loop_thread.join(timeout=5.0)
        _loop = None
        _loop_thread = None
        logger.debug("Shared async event loop shut down")
