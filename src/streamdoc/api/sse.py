"""SSE event stream manager for real-time job progress updates.

Uses asyncio queues to broadcast progress events from background tasks
to connected SSE clients.

Thread safety: ``publish()`` and ``complete()`` are called from background
threads (preset job workers), while ``subscribe()`` and ``unsubscribe()``
are called from the async event loop (FastAPI route handlers). A
``threading.Lock`` protects the shared ``_subscribers`` dict, and
``call_soon_threadsafe`` is used to safely put events onto asyncio queues
from non-event-loop threads.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvent:
    """A single progress event for SSE streaming.

    Attributes:
        job_id: The job this event belongs to.
        step: Current step name (e.g. "downloading", "transcribing").
        message: Human-readable progress message.
        progress: Optional 0-100 percentage.
        video_title: Title of the video being processed, if applicable.
        status: "running", "completed", "failed", "info".
        timestamp: ISO timestamp of the event.
    """
    job_id: str
    step: str = ""
    message: str = ""
    progress: float | None = None
    video_title: str | None = None
    status: str = "running"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sse(self) -> str:
        """Format as an SSE data line."""
        data = {
            "job_id": self.job_id,
            "step": self.step,
            "message": self.message,
            "progress": self.progress,
            "video_title": self.video_title,
            "status": self.status,
            "timestamp": self.timestamp,
        }
        return json.dumps(data)


class SSEManager:
    """Manages SSE event queues for active jobs.

    Each job_id gets a list of subscriber queues. When a progress event
    is published, it's sent to all subscriber queues for that job_id.

    Thread safety: A ``threading.Lock`` protects ``_subscribers`` from
    concurrent modification. Events are dispatched to asyncio queues
    using ``call_soon_threadsafe`` when called from a non-event-loop thread.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[ProgressEvent | None]]] = {}
        # Reason: protect _subscribers from concurrent access by multiple
        # background job threads publishing events simultaneously.
        self._lock = threading.Lock()

    def subscribe(self, job_id: str) -> asyncio.Queue[ProgressEvent | None]:
        """Subscribe to events for a job. Returns a queue to await on.

        Must be called from the event loop thread (FastPI route handler).
        """
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        with self._lock:
            if job_id not in self._subscribers:
                self._subscribers[job_id] = []
            self._subscribers[job_id].append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[ProgressEvent | None]) -> None:
        """Remove a subscriber queue.

        Must be called from the event loop thread (FastAPI route handler).
        """
        with self._lock:
            if job_id in self._subscribers:
                try:
                    self._subscribers[job_id].remove(queue)
                except ValueError:
                    pass
                if not self._subscribers[job_id]:
                    del self._subscribers[job_id]

    def publish(self, event: ProgressEvent) -> None:
        """Publish an event to all subscribers of the event's job_id.

        Thread-safe: can be called from any thread (background job workers).
        Uses ``call_soon_threadsafe`` to safely put events onto asyncio
        queues that belong to the event loop thread.
        """
        with self._lock:
            subs = list(self._subscribers.get(event.job_id, []))

        for queue in subs:
            try:
                # Reason: if we're in the event loop thread, put_nowait is safe.
                # If we're in a background thread, we need call_soon_threadsafe
                # to avoid concurrent access to the queue's internal state.
                try:
                    asyncio.get_running_loop()
                    # Reason: we're in an event loop — use put_nowait directly
                    queue.put_nowait(event)
                except RuntimeError:
                    # Reason: no running event loop in this thread — we're
                    # in a background thread. Use call_soon_threadsafe on
                    # the shared async loop to safely put the event.
                    from streamdoc.async_utils import _ensure_loop
                    loop = _ensure_loop()
                    loop.call_soon_threadsafe(self._safe_put, queue, event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for job %s, dropping event", event.job_id)

    def complete(self, job_id: str) -> None:
        """Signal completion to all subscribers of a job.

        Thread-safe: can be called from any thread.
        """
        with self._lock:
            subs = list(self._subscribers.get(job_id, []))
            if job_id in self._subscribers:
                del self._subscribers[job_id]

        for queue in subs:
            try:
                try:
                    asyncio.get_running_loop()
                    queue.put_nowait(None)
                except RuntimeError:
                    from streamdoc.async_utils import _ensure_loop
                    loop = _ensure_loop()
                    loop.call_soon_threadsafe(self._safe_put, queue, None)
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _safe_put(queue: asyncio.Queue[ProgressEvent | None], item: ProgressEvent | None) -> None:
        """Safely put an item onto a queue from the event loop thread.

        Args:
            queue: The asyncio queue to put onto.
            item: The event or None (for completion signal).
        """
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass


# Global singleton
sse_manager = SSEManager()


def emit_progress(
    job_id: str,
    step: str = "",
    message: str = "",
    progress: float | None = None,
    video_title: str | None = None,
    status: str = "running",
) -> None:
    """Convenience function to publish a progress event."""
    event = ProgressEvent(
        job_id=job_id,
        step=step,
        message=message,
        progress=progress,
        video_title=video_title,
        status=status,
    )
    sse_manager.publish(event)
