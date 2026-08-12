"""
Preset ORM model.
"""
from dataclasses import dataclass

from sqlalchemy import Boolean, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base


@dataclass
class SocialSourceConfig:
    """Typed representation of a single social source entry.

    Stored as JSON objects inside the preset's ``social_sources`` column.
    Example: ``{"platform": "reddit", "identifier": "wallstreetbets", "max_posts": 100}``

    Attributes:
        platform: Platform identifier (``reddit``, ``stocktwits``, ``x``).
        identifier: Platform-specific source descriptor (subreddit, ticker, query).
        max_posts: Optional per-source post cap (overrides preset-level cap).
        resolved_name: Optional human-readable display name resolved from the
            identifier (e.g. subreddit title, stock name). Stored so the UI
            can show it without re-resolving on every load.
        resolved_id: Optional canonical identifier returned by the resolver.
    """

    platform: str
    identifier: str
    max_posts: int | None = None
    resolved_name: str | None = None
    resolved_id: str | None = None


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    # Reason: discriminator field to branch the runner pipeline. "youtube"
    # uses the existing video fetch/transcribe/frame pipeline; "social" uses
    # the social sentiment collector pipeline.
    preset_type: Mapped[str] = mapped_column(Text, default="youtube")
    channel_list_id: Mapped[str | None] = mapped_column(default=None)
    # Reason: store resolved channel names alongside IDs so the UI can display
    # human-readable names without re-resolving on every page load.
    channel_names: Mapped[str | None] = mapped_column(default=None)
    prompt_md: Mapped[str] = mapped_column(Text, default="")
    outputs: Mapped[str] = mapped_column(default="pdf,markdown,notebooklm")
    notebooklm_kind: Mapped[str | None] = mapped_column(default=None)
    # Reason: allow each preset to use a specific NotebookLM prompt template
    # (e.g. "Crypto Daily Brief") instead of always falling back to the
    # global default (settings.notebooklm_default_prompt). When None or
    # empty, the global default is used.
    notebooklm_prompt_template: Mapped[str | None] = mapped_column(default=None)
    # Reason: optional retry for NotebookLM generation failures. Sometimes
    # a failed slide deck succeeds on a later attempt, so the pipeline can
    # automatically resubmit the same prompt in the same notebook.
    notebooklm_retry_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    notebooklm_retry_attempts: Mapped[int] = mapped_column(Integer, default=1)
    notebooklm_retry_delay_minutes: Mapped[float | None] = mapped_column(Float, default=5.0)
    # Reason: parallel Antigravity (agy) generation backend columns. Mirrors the
    # notebooklm_* shape so the future _send_reports backend discriminator in
    # fetch.py can branch on either backend with the same surface. Defaults are
    # additive and nullable so existing presets are unaffected. The "agy" token
    # is also added to the ``outputs`` comma-separated string alongside
    # "notebooklm" when the operator selects the agy backend.
    agy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    agy_skill: Mapped[str | None] = mapped_column(default=None)
    agy_model: Mapped[str | None] = mapped_column(default=None)
    agy_publish_herenow: Mapped[bool] = mapped_column(Boolean, default=False)
    agy_prompt_template: Mapped[str | None] = mapped_column(default=None)
    # Reason: optional path to a pre-existing report file (PDF/MD) under
    # data/Outputs/<preset_name>/ to send to agy instead of generating a
    # fresh one each run. Useful for testing the agy pipeline without
    # re-running the full fetch/transcribe pipeline. When set, the agy
    # uploader uses this file directly and skips artifact selection.
    agy_existing_report: Mapped[str | None] = mapped_column(Text, default=None)
    schedule: Mapped[str | None] = mapped_column(default=None)
    schedule_interval_hours: Mapped[int | None] = mapped_column(Integer, default=12)
    lookback_hours: Mapped[int | None] = mapped_column(Integer, default=None)
    max_videos: Mapped[int | None] = mapped_column(Integer, default=None)
    text_filter: Mapped[str | None] = mapped_column(default=None)
    date_range_days: Mapped[int | None] = mapped_column(Integer, default=None)
    playlist_mode: Mapped[bool] = mapped_column(default=False)
    skip_processed: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    # Reason: per-preset retention controls. retention_enabled toggles
    # whether cleanup applies to this preset at all. When False, files
    # and notebooks are kept indefinitely. The _hours fields control the
    # retention period when enabled. Default 24h matches the product spec.
    retention_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    file_retention_hours: Mapped[float | None] = mapped_column(Float, default=24.0)
    notebook_retention_hours: Mapped[float | None] = mapped_column(Float, default=24.0)
    # Reason: social sentiment pipeline fields. social_sources is a JSON
    # array of platform identifiers (e.g. ["reddit","stocktwits","x"]).
    # social_max_posts caps the number of posts collected per run.
    # social_lookback_hours controls how far back to collect posts.
    social_sources: Mapped[str | None] = mapped_column(Text, default=None)
    social_max_posts: Mapped[int | None] = mapped_column(Integer, default=None)
    social_lookback_hours: Mapped[int | None] = mapped_column(Integer, default=None)
    # Reason: CLI tool integration. cli_tool names the external binary
    # (e.g. "agy") to invoke for processing. cli_tool_template is the
    # template file passed to the tool for formatting output.
    cli_tool: Mapped[str | None] = mapped_column(Text, default=None)
    cli_tool_template: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[str] = mapped_column(default="")
    updated_at: Mapped[str] = mapped_column(default="")
