"""Cleanup routes — run retention cleanup."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import CleanupRequest, CleanupResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post("", response_model=CleanupResponse)
def run_cleanup(body: CleanupRequest):
    """Run retention cleanup manually."""
    ensure_db()
    from streamdoc.core.cleanup import run_cleanup as _run
    counts = _run(dry_run=body.dry_run)
    if not counts:
        counts = {}
    return CleanupResponse(counts=counts)
