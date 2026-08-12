"""Settings routes — get/update StreamDoc configuration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import SettingsOut, SettingsUpdate
from streamdoc.config import Settings, settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    """Get all current settings."""
    fields = SettingsOut.model_fields.keys()
    data: dict[str, Any] = {}
    for field in fields:
        val = getattr(settings, field, None)
        if field == "secret_key" and val:
            val = "***"
        # Reason: never return Telegram bot tokens to the UI; treat them
        # like secret_key. The chat id is less sensitive but also not
        # needed in the browser.
        if field == "notify_telegram_bot_token" and val:
            val = "***"
        data[field] = val
    return SettingsOut.model_validate(data)


@router.put("")
def update_settings(body: SettingsUpdate) -> dict[str, Any]:
    """Update settings by writing to .env file and reloading."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    env_path = Path(".env")
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Build a map of existing env keys
    existing: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            existing[key] = i

    # Update or append each field
    for field_name, value in update_data.items():
        env_key = f"STREAMDOC_{field_name.upper()}"
        env_val = str(value)
        if env_key in existing:
            lines[existing[env_key]] = f"{env_key}={env_val}"
        else:
            lines.append(f"{env_key}={env_val}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Updated .env with %d settings", len(update_data))

    # Reason: BaseSettings only loads .env at startup. Re-instantiate from
    # the updated file and copy values into the running global settings
    # object so subsequent API calls see the new configuration immediately.
    try:
        reloaded = Settings()
        for key in settings.model_fields:
            setattr(settings, key, getattr(reloaded, key))
        logger.info("Reloaded settings into memory")
    except Exception as exc:
        logger.warning("Settings written to .env but could not reload in memory: %s", exc)

    return {"updated": list(update_data.keys()), "count": len(update_data)}
