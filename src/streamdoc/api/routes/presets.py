"""Preset CRUD routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from streamdoc.api.deps import ensure_db
from streamdoc.api.schemas import PresetCreate, PresetOut, PresetUpdate
from streamdoc.db import session_scope
from streamdoc.models.preset import Preset as PresetModel
from streamdoc.presets import upsert_preset

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/presets", tags=["presets"])


def _sync_scheduler() -> None:
    """Reconcile the live scheduler with the presets table after a mutation.

    Imported lazily to avoid a circular import with the scheduler module.
    """
    try:
        from streamdoc.scheduler import sync_jobs

        sync_jobs()
    except Exception as exc:
        logger.warning("Scheduler sync after preset mutation failed: %s", exc)


def _to_out(p: Any) -> PresetOut:
    """Build PresetOut from a Preset ORM row or any object with preset attributes.

    Uses getattr with safe defaults so this works for DB rows, detached
    instances, and the plain Preset objects created by ``presets.py``.
    """
    return PresetOut(
        id=p.id,
        name=p.name,
        preset_type=getattr(p, "preset_type", "youtube"),
        channel_list_id=p.channel_list_id,
        channel_names=getattr(p, "channel_names", None),
        prompt_md=getattr(p, "prompt_md", None) or "",
        outputs=getattr(p, "outputs", None) or "",
        notebooklm_kind=getattr(p, "notebooklm_kind", None),
        notebooklm_prompt_template=getattr(p, "notebooklm_prompt_template", None),
        design_prompt_template=getattr(p, "design_prompt_template", None),
        notebooklm_retry_failed=getattr(p, "notebooklm_retry_failed", True),
        notebooklm_retry_attempts=getattr(p, "notebooklm_retry_attempts", 1),
        notebooklm_retry_delay_minutes=getattr(p, "notebooklm_retry_delay_minutes", 5.0),
        agy_enabled=getattr(p, "agy_enabled", False),
        agy_skill=getattr(p, "agy_skill", None),
        agy_model=getattr(p, "agy_model", None),
        agy_publish_herenow=getattr(p, "agy_publish_herenow", False),
        agy_prompt_template=getattr(p, "agy_prompt_template", None),
        agy_existing_report=getattr(p, "agy_existing_report", None),
        schedule=getattr(p, "schedule", None),
        schedule_interval_hours=getattr(p, "schedule_interval_hours", None),
        lookback_hours=getattr(p, "lookback_hours", None),
        max_videos=getattr(p, "max_videos", None),
        text_filter=getattr(p, "text_filter", None),
        date_range_days=getattr(p, "date_range_days", None),
        playlist_mode=getattr(p, "playlist_mode", False),
        skip_processed=getattr(p, "skip_processed", True),
        active=getattr(p, "active", True),
        retention_enabled=getattr(p, "retention_enabled", True),
        file_retention_hours=getattr(p, "file_retention_hours", 24.0),
        notebook_retention_hours=getattr(p, "notebook_retention_hours", 24.0),
        social_sources=getattr(p, "social_sources", None),
        social_max_posts=getattr(p, "social_max_posts", None),
        social_lookback_hours=getattr(p, "social_lookback_hours", None),
        cli_tool=getattr(p, "cli_tool", None),
        cli_tool_template=getattr(p, "cli_tool_template", None),
    )


@router.get("", response_model=list[PresetOut])
def list_presets() -> list[PresetOut]:
    """List all presets."""
    ensure_db()
    with session_scope() as s:
        rows = s.query(PresetModel).order_by(PresetModel.name).all()
        return [_to_out(r) for r in rows]


@router.get("/{preset_id}", response_model=PresetOut)
def get_preset(preset_id: str) -> PresetOut:
    """Get a single preset."""
    ensure_db()
    with session_scope() as s:
        p = s.get(PresetModel, preset_id)
        if p is None:
            raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
        return _to_out(p)


@router.post("", response_model=PresetOut)
def create_preset(body: PresetCreate) -> PresetOut:
    """Create a new preset."""
    ensure_db()
    payload = body.model_dump(exclude_none=True)
    p = upsert_preset(payload, name_hint=body.name)
    _sync_scheduler()
    return _to_out(p)


@router.put("/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: str, body: PresetUpdate) -> PresetOut:
    """Update an existing preset."""
    ensure_db()
    with session_scope() as s:
        p = s.get(PresetModel, preset_id)
        if p is None:
            raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
        # Reason: use exclude_unset so a partial PUT only writes fields the
        # client sent. PresetUpdate fields have defaults; without this, omitted
        # fields would be overwritten by their default values.
        update_data = body.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(p, key, val)
        s.flush()
        out = _to_out(p)
    _sync_scheduler()
    return out


@router.delete("/{preset_id}")
def delete_preset(preset_id: str) -> dict[str, str]:
    """Delete a preset."""
    ensure_db()
    with session_scope() as s:
        p = s.get(PresetModel, preset_id)
        if p is None:
            raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
        s.delete(p)
    _sync_scheduler()
    return {"deleted": preset_id}