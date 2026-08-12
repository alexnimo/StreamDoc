"""Shared dependencies for FastAPI routes."""
from __future__ import annotations

from streamdoc.config import settings
from streamdoc.db import init_db


def get_settings():
    """Return the current settings instance."""
    return settings


def ensure_db() -> None:
    """Ensure the database is initialized."""
    init_db()
