"""
SocialPost ORM model for social sentiment deduplication and retention.
"""
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint

from streamdoc.db import Base


class SocialPost(Base):
    __tablename__ = "social_posts"

    __table_args__ = (
        UniqueConstraint(
            "platform", "source_id", "preset_name",
            name="uq_social_posts_platform_source_preset",
        ),
        Index("idx_social_posts_platform_source_id", "platform", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Reason: platform identifier (reddit, stocktwits, x) for multi-source dedup.
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    # Reason: unique post ID from the source platform (e.g. Reddit post ID,
    # StockTwits message ID, X tweet ID). Used alongside platform + preset_name
    # to deduplicate posts across runs.
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    preset_name: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[str] = mapped_column(Text, default="")
    # Reason: explicit marker that this post has been processed. False for
    # records that exist only as placeholders or failed mid-pipeline.
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Reason: track whether the post was successfully processed and sent to
    # destination (ready, failed, pending).
    output_status: Mapped[str] = mapped_column(Text, default="pending")
    # Reason: store the raw post data as JSON so we can reprocess or debug
    # without re-fetching from the source API.
    raw_data: Mapped[str | None] = mapped_column(Text, default=None)
