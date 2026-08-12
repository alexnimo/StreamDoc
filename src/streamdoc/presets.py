"""
Preset loading and upsert logic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from streamdoc.config import settings
from streamdoc.db import session_scope
from streamdoc.models.preset import Preset

logger = logging.getLogger(__name__)


def _coerce_preset(payload: dict[str, Any], name_hint: str | None = None) -> Preset:
    name = str(payload.get("name") or name_hint or "default")
    schedule = payload.get("schedule") or None
    interval_hours = payload.get("schedule_interval_hours")
    # Reason: back-compat — older presets used schedule_interval_hours instead
    # of the canonical schedule string. If no schedule string is set but an
    # interval is, derive an interval schedule so the legacy knob still works.
    if not schedule and interval_hours:
        try:
            schedule = f"interval:{int(float(interval_hours)) * 3600}"
        except (TypeError, ValueError):
            schedule = None
    # Reason: social_sources may arrive as a list from YAML/JSON; store as
    # a JSON string for SQLite compatibility and so the UI can parse it safely.
    social_sources_raw = payload.get("social_sources")
    if isinstance(social_sources_raw, list):
        social_sources = json.dumps(social_sources_raw) or None
    else:
        social_sources = social_sources_raw or None

    return Preset(
        id=name,
        name=name,
        preset_type=payload.get("preset_type") or "youtube",
        channel_list_id=payload.get("channel_list_id") or payload.get("channels") or None,
        channel_names=payload.get("channel_names") or None,
        prompt_md=payload.get("prompt_md") or payload.get("prompt") or "",
        outputs=payload.get("outputs") or payload.get("output_targets") or "pdf,markdown,notebooklm",
        notebooklm_kind=payload.get("notebooklm_kind") or payload.get("notebooklm_output") or None,
        notebooklm_prompt_template=payload.get("notebooklm_prompt_template") or None,
        notebooklm_retry_failed=bool(payload.get("notebooklm_retry_failed", True)),
        notebooklm_retry_attempts=int(payload.get("notebooklm_retry_attempts", 1)) if payload.get("notebooklm_retry_attempts") is not None else 1,
        notebooklm_retry_delay_minutes=_coerce_float(payload.get("notebooklm_retry_delay_minutes"), 5.0),
        agy_enabled=bool(payload.get("agy_enabled", False)),
        agy_skill=payload.get("agy_skill") or None,
        agy_model=payload.get("agy_model") or None,
        agy_publish_herenow=bool(payload.get("agy_publish_herenow", False)),
        agy_prompt_template=payload.get("agy_prompt_template") or None,
        agy_existing_report=payload.get("agy_existing_report") or None,
        schedule=schedule,
        schedule_interval_hours=interval_hours,
        lookback_hours=payload.get("lookback_hours"),
        max_videos=payload.get("max_videos"),
        text_filter=payload.get("text_filter"),
        date_range_days=payload.get("date_range_days"),
        playlist_mode=bool(payload.get("playlist_mode", False)),
        skip_processed=bool(payload.get("skip_processed", True)),
        active=bool(payload.get("active", True)),
        retention_enabled=bool(payload.get("retention_enabled", True)),
        file_retention_hours=_coerce_float(payload.get("file_retention_hours"), 24.0),
        notebook_retention_hours=_coerce_float(payload.get("notebook_retention_hours"), 24.0),
        social_sources=social_sources,
        social_max_posts=int(payload["social_max_posts"]) if payload.get("social_max_posts") is not None else None,
        social_lookback_hours=int(payload["social_lookback_hours"]) if payload.get("social_lookback_hours") is not None else None,
        cli_tool=payload.get("cli_tool") or None,
        cli_tool_template=payload.get("cli_tool_template") or None,
    )


def _coerce_float(value: Any, default: float) -> float | None:
    """Coerce a value to float, returning default when None or invalid.

    Args:
        value: Raw value from YAML/JSON/dict.
        default: Fallback when value is None.

    Returns:
        Parsed float or default.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_preset(name: str) -> Preset:
    """Load a preset by its id/name and return a detached copy.

    Args:
        name: Preset id.

    Returns:
        A :class:`Preset` instance detached from the ORM session.

    Raises:
        ValueError: if no preset with the given name exists.
    """
    with session_scope() as s:
        p = s.get(Preset, name)
        if p is None:
            raise ValueError(f"Preset not found: {name}")
        s.refresh(p)
        return clone_preset(p)


def prompt_args_for_preset(preset: Preset, backend: str) -> dict[str, str | None]:
    """Build mutually-exclusive prompt arguments for a preset and backend.

    Priority:
        1. ``{backend}_prompt_template`` (template name) if set.
        2. ``prompt_md`` (custom raw text) if non-empty.
        3. ``None`` for both (the upload layer will use its default).

    Args:
        preset: Preset configuration.
        backend: Either ``"notebooklm"`` or ``"agy"``.

    Returns:
        Dict with ``prompt_template`` and ``custom_prompt`` keys.
    """
    template_field = f"{backend}_prompt_template"
    template_name = getattr(preset, template_field, None)
    custom_prompt = (preset.prompt_md or "").strip() or None

    if template_name:
        # Reason: when a template is selected, the custom prompt is ignored.
        # The backend renders the template at runtime, so we do not need to
        # embed the prompt text here.
        return {"prompt_template": template_name, "custom_prompt": None}

    if custom_prompt:
        return {"prompt_template": None, "custom_prompt": custom_prompt}

    # Reason: neither template nor custom prompt is set; let the upload
    # layer fall back to its default template.
    return {"prompt_template": None, "custom_prompt": None}


def clone_preset(p: Preset) -> Preset:
    """Create a detached copy of a Preset instance.

    Reason: SQLAlchemy instances attached to a closed session can raise
    DetachedInstanceError later. Returning a fresh, unmanaged Preset with
    the same column values avoids that without needing to keep the session
    open.
    """
    return Preset(
        id=p.id,
        name=p.name,
        preset_type=getattr(p, "preset_type", "youtube"),
        channel_list_id=p.channel_list_id,
        channel_names=getattr(p, "channel_names", None),
        prompt_md=p.prompt_md,
        outputs=p.outputs,
        notebooklm_kind=p.notebooklm_kind,
        notebooklm_prompt_template=getattr(p, "notebooklm_prompt_template", None),
        notebooklm_retry_failed=getattr(p, "notebooklm_retry_failed", True),
        notebooklm_retry_attempts=getattr(p, "notebooklm_retry_attempts", 1),
        notebooklm_retry_delay_minutes=getattr(p, "notebooklm_retry_delay_minutes", 5.0),
        agy_enabled=getattr(p, "agy_enabled", False),
        agy_skill=getattr(p, "agy_skill", None),
        agy_model=getattr(p, "agy_model", None),
        agy_publish_herenow=getattr(p, "agy_publish_herenow", False),
        agy_prompt_template=getattr(p, "agy_prompt_template", None),
        agy_existing_report=getattr(p, "agy_existing_report", None),
        schedule=p.schedule,
        schedule_interval_hours=p.schedule_interval_hours,
        lookback_hours=p.lookback_hours,
        max_videos=p.max_videos,
        text_filter=p.text_filter,
        date_range_days=p.date_range_days,
        playlist_mode=p.playlist_mode,
        skip_processed=p.skip_processed,
        active=p.active,
        retention_enabled=getattr(p, "retention_enabled", True),
        file_retention_hours=p.file_retention_hours,
        notebook_retention_hours=p.notebook_retention_hours,
        social_sources=getattr(p, "social_sources", None),
        social_max_posts=getattr(p, "social_max_posts", None),
        social_lookback_hours=getattr(p, "social_lookback_hours", None),
        cli_tool=getattr(p, "cli_tool", None),
        cli_tool_template=getattr(p, "cli_tool_template", None),
    )




def upsert_preset(payload: dict[str, Any], name_hint: str | None = None) -> Preset:
    p = _coerce_preset(payload, name_hint)
    with session_scope() as s:
        existing = s.get(Preset, p.id)
        if existing is None:
            s.add(p)
            s.flush()
            result = p
        else:
            existing.name = p.name
            existing.preset_type = p.preset_type
            existing.channel_list_id = p.channel_list_id
            existing.channel_names = p.channel_names
            existing.prompt_md = p.prompt_md
            existing.outputs = p.outputs
            existing.notebooklm_kind = p.notebooklm_kind
            existing.notebooklm_prompt_template = p.notebooklm_prompt_template
            existing.notebooklm_retry_failed = p.notebooklm_retry_failed
            existing.notebooklm_retry_attempts = p.notebooklm_retry_attempts
            existing.notebooklm_retry_delay_minutes = p.notebooklm_retry_delay_minutes
            existing.agy_enabled = p.agy_enabled
            existing.agy_skill = p.agy_skill
            existing.agy_model = p.agy_model
            existing.agy_publish_herenow = p.agy_publish_herenow
            existing.agy_prompt_template = p.agy_prompt_template
            existing.agy_existing_report = getattr(p, "agy_existing_report", None)
            existing.schedule = p.schedule
            existing.schedule_interval_hours = p.schedule_interval_hours
            existing.lookback_hours = p.lookback_hours
            existing.max_videos = p.max_videos
            existing.text_filter = p.text_filter
            existing.date_range_days = p.date_range_days
            existing.playlist_mode = p.playlist_mode
            existing.skip_processed = p.skip_processed
            existing.active = p.active
            existing.retention_enabled = p.retention_enabled
            existing.file_retention_hours = p.file_retention_hours
            existing.notebook_retention_hours = p.notebook_retention_hours
            existing.social_sources = p.social_sources
            existing.social_max_posts = p.social_max_posts
            existing.social_lookback_hours = p.social_lookback_hours
            existing.cli_tool = p.cli_tool
            existing.cli_tool_template = p.cli_tool_template
            s.flush()
            result = existing
        return clone_preset(result)


def load_preset_file(path: Path) -> Preset:
    text = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    if isinstance(payload, list):
        if not payload:
            raise ValueError(f"Empty preset list: {path}")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError(f"Unsupported preset format in {path}")
    return upsert_preset(payload, name_hint=path.stem)


def autoload_presets() -> list[Preset]:
    presets_dir = Path(settings.presets_path)
    if not presets_dir.exists() or not presets_dir.is_dir():
        return []
    out: list[Preset] = []
    for child in sorted(presets_dir.iterdir()):
        if child.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            out.append(load_preset_file(child))
        except Exception as exc:
            logger.warning("Failed to load preset %s: %s", child, exc)
    return out
