"""
Video and Channel ORM models.
"""
from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(default="")
    source: Mapped[str] = mapped_column(default="youtube")
    handle: Mapped[str | None] = mapped_column(default=None)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(primary_key=True)
    channel_id: Mapped[str] = mapped_column(default="")
    title: Mapped[str] = mapped_column(default="")
    published_at: Mapped[str] = mapped_column(default="")
    duration_seconds: Mapped[int | None] = mapped_column(default=None)
    frame_count: Mapped[int | None] = mapped_column(default=None)
    transcript_word_count: Mapped[int | None] = mapped_column(default=None)
    resolution: Mapped[str | None] = mapped_column(default=None)
    transcript_status: Mapped[str] = mapped_column(default="unknown")
    media_status: Mapped[str] = mapped_column(default="missing")
    output_status: Mapped[str] = mapped_column(default="missing")
    processed_at: Mapped[str | None] = mapped_column(default=None)
