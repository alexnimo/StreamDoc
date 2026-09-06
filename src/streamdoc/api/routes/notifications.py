"""API routes for the notification bell.

Provides a single endpoint that aggregates notifications from plugin
updates, NotebookLM auth status, and recent job completions/failures.
The frontend polls this periodically and displays results in a bell
dropdown in the top nav.
"""

from __future__ import annotations

from fastapi import APIRouter

from streamdoc.api.schemas import NotificationListOut, NotificationOut
from streamdoc.core.notifications import get_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_notifications() -> NotificationListOut:
    """Return all active notifications.

    The frontend tracks dismissed notification IDs in localStorage and
    filters them client-side, so the backend returns the full set each time.
    """
    notifications = await get_notifications()
    return NotificationListOut(
        notifications=notifications,
        unread_count=len(notifications),
    )
