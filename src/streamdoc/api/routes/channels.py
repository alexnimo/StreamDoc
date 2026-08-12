"""Channel resolution routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import ChannelResolveRequest, ChannelResolveResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("/resolve", response_model=ChannelResolveResponse)
def resolve_channel(body: ChannelResolveRequest):
    """Resolve a YouTube channel name, handle, URL, or channel ID to a canonical channel.

    Accepts:
      - Full URLs: https://www.youtube.com/@handle
      - Bare channel IDs: UCMno7bbQKigk6RxiO0uv78g
      - Handles: @TradersHelpingTraders
      - Channel names: TradersHelpingTraders
      - Playlist URLs: https://www.youtube.com/playlist?list=PLxxxx

    Returns the canonical channel ID, title, and source.
    """
    from streamdoc.core.channel import resolve_channel as _resolve

    try:
        ch = _resolve(body.identifier.strip())
        return ChannelResolveResponse(
            channel_id=ch.id,
            channel_title=ch.title,
            source=ch.source,
        )
    except Exception as exc:
        logger.warning("Channel resolution failed for %s: %s", body.identifier, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Could not resolve channel: {exc}",
        ) from exc
