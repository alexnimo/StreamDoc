"""Job tracking ORM model.

Every preset run creates a Job record that tracks:
- Run status (running, completed, failed, partial)
- Generated report file paths
- Destination send results (success / failure per destination)
- Errors encountered

This enables retry/resend without re-processing videos.
"""
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base


class Job(Base):
    """Track a single preset run for retry/resend and audit purposes."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    preset_name: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="running")
    created_at: Mapped[str] = mapped_column(default="")
    completed_at: Mapped[str | None] = mapped_column(default=None)
    artifact_count: Mapped[int] = mapped_column(default=0)
    report_paths: Mapped[str] = mapped_column(default="")  # JSON list of paths
    destinations: Mapped[str] = mapped_column(default="")  # JSON dict
    errors: Mapped[str] = mapped_column(default="")  # JSON list
    details: Mapped[str] = mapped_column(default="")  # JSON dict with videos, artifacts, stats
