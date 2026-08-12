"""NotebookLM generation tracking ORM model.

Tracks async content generations (slide_deck, podcast, etc.) that may take
longer than the initial wait timeout. The background poller checks pending
generations and downloads artifacts when they complete.
"""
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base


class Generation(Base):
    """Track a NotebookLM content generation task.

    Attributes:
        id: UUID for this generation record.
        job_id: Associated job ID (FK to jobs.id, not enforced in SQLite).
        notebook_id: NotebookLM notebook ID.
        task_id: NotebookLM generation task ID for polling.
        content_type: Type of content being generated (slide_deck, podcast, etc.).
        status: pending, in_progress, completed, failed.
        artifact_id: NotebookLM artifact ID (filled when complete).
        local_path: Local download path (filled when artifact is downloaded).
        error: Error message if failed.
        created_at: ISO timestamp when record was created.
        updated_at: ISO timestamp when record was last updated.
    """

    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(default="")
    notebook_id: Mapped[str] = mapped_column(default="")
    task_id: Mapped[str] = mapped_column(default="")
    content_type: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="pending")
    artifact_id: Mapped[str] = mapped_column(default="")
    local_path: Mapped[str] = mapped_column(default="")
    error: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default="")
    updated_at: Mapped[str] = mapped_column(default="")
