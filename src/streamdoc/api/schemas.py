"""Pydantic request/response schemas for the StreamDoc API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
class PresetOut(BaseModel):
    id: str
    name: str
    preset_type: str = "youtube"
    channel_list_id: str | None = None
    channel_names: str | None = None
    prompt_md: str = ""
    outputs: str = "pdf,markdown,notebooklm"
    notebooklm_kind: str | None = None
    notebooklm_prompt_template: str | None = None
    notebooklm_retry_failed: bool = True
    notebooklm_retry_attempts: int = 1
    notebooklm_retry_delay_minutes: float = 5.0
    # Reason: Antigravity (agy) generation backend fields. Add to the outputs
    # string ("pdf,markdown,agy") and set agy_enabled=True to route a preset
    # through agy instead of NotebookLM. Mirror the notebooklm_* shape so
    # the future _send_reports discriminator can branch on either backend.
    agy_enabled: bool = False
    agy_skill: str | None = None
    agy_model: str | None = None
    agy_publish_herenow: bool = False
    agy_prompt_template: str | None = None
    agy_existing_report: str | None = None
    schedule: str | None = None
    schedule_interval_hours: int | None = None
    lookback_hours: int | None = None
    max_videos: int | None = None
    text_filter: str | None = None
    date_range_days: int | None = None
    playlist_mode: bool = False
    skip_processed: bool = True
    active: bool = True
    retention_enabled: bool = True
    file_retention_hours: float | None = 24.0
    notebook_retention_hours: float | None = 24.0
    social_sources: str | None = None
    social_max_posts: int | None = None
    social_lookback_hours: int | None = None
    cli_tool: str | None = None
    cli_tool_template: str | None = None


class PresetCreate(BaseModel):
    name: str
    preset_type: str = "youtube"
    channel_list_id: str | None = None
    channel_names: str | None = None
    prompt_md: str = ""
    outputs: str = "pdf,markdown,notebooklm"
    notebooklm_kind: str | None = None
    notebooklm_prompt_template: str | None = None
    notebooklm_retry_failed: bool = True
    notebooklm_retry_attempts: int = 1
    notebooklm_retry_delay_minutes: float = 5.0
    agy_enabled: bool = False
    agy_skill: str | None = None
    agy_model: str | None = None
    agy_publish_herenow: bool = False
    agy_prompt_template: str | None = None
    agy_existing_report: str | None = None
    schedule: str | None = None
    schedule_interval_hours: int | None = 12
    lookback_hours: int | None = None
    max_videos: int | None = None
    text_filter: str | None = None
    date_range_days: int | None = None
    playlist_mode: bool = False
    skip_processed: bool = True
    active: bool = True
    retention_enabled: bool = True
    file_retention_hours: float | None = 24.0
    notebook_retention_hours: float | None = 24.0
    social_sources: str | None = None
    social_max_posts: int | None = None
    social_lookback_hours: int | None = None
    cli_tool: str | None = None
    cli_tool_template: str | None = None


class PresetUpdate(BaseModel):
    name: str | None = None
    preset_type: str | None = None
    channel_list_id: str | None = None
    channel_names: str | None = None
    prompt_md: str | None = None
    outputs: str | None = None
    notebooklm_kind: str | None = None
    notebooklm_prompt_template: str | None = None
    notebooklm_retry_failed: bool = True
    notebooklm_retry_attempts: int = 1
    notebooklm_retry_delay_minutes: float = 5.0
    agy_enabled: bool | None = None
    agy_skill: str | None = None
    agy_model: str | None = None
    agy_publish_herenow: bool | None = None
    agy_prompt_template: str | None = None
    agy_existing_report: str | None = None
    schedule: str | None = None
    schedule_interval_hours: int | None = None
    lookback_hours: int | None = None
    max_videos: int | None = None
    text_filter: str | None = None
    date_range_days: int | None = None
    playlist_mode: bool | None = None
    skip_processed: bool | None = None
    active: bool | None = None
    retention_enabled: bool | None = None
    file_retention_hours: float | None = None
    notebook_retention_hours: float | None = None
    social_sources: str | None = None
    social_max_posts: int | None = None
    social_lookback_hours: int | None = None
    cli_tool: str | None = None
    cli_tool_template: str | None = None


# ---------------------------------------------------------------------------
# Social Sentiment
# ---------------------------------------------------------------------------
class SocialSource(BaseModel):
    """Describes one social platform source for a social preset."""
    platform: str
    enabled: bool = True
    query: str | None = None


class CLIToolOut(BaseModel):
    """Output schema for CLI tool info."""
    name: str
    binary_path: str | None = None
    version: str | None = None
    installed: bool = False
    install_instructions: str | None = None
    install_url: str | None = None


class CLIToolInstallStatusOut(BaseModel):
    """Response model for CLI tool install status."""
    name: str
    installed: bool
    version: str | None = None
    binary_path: str | None = None
    install_instructions: str | None = None
    install_url: str | None = None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class JobOut(BaseModel):
    id: str
    preset_name: str
    status: str
    created_at: str
    completed_at: str | None = None
    artifact_count: int = 0
    # Reason: destination values may be strings (e.g. "success: ...") or
    # lists of strings (e.g. notebooklm_errors accumulates multiple errors),
    # so the value type must be permissive to avoid ValidationError.
    destinations: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class JobRetryResponse(BaseModel):
    results: dict[str, str]


class JobResendRequest(BaseModel):
    destination: str


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
class FetchRequest(BaseModel):
    lookback_hours: int | None = None


class FetchResponse(BaseModel):
    job_id: str
    preset: str
    message: str = "Fetch started"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
class ScheduleAddRequest(BaseModel):
    preset: str
    schedule: str


class ScheduleJobOut(BaseModel):
    id: str
    preset: str
    schedule: str
    trigger: str


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
class CleanupRequest(BaseModel):
    dry_run: bool = False


class CleanupResponse(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# NotebookLM
# ---------------------------------------------------------------------------
class NotebookLMAuthStatus(BaseModel):
    profile: str
    storage_path: str
    configured: bool
    is_valid: bool
    is_fresh: bool
    message: str


class NotebookLMNotebookOut(BaseModel):
    id: str
    title: str
    sources_count: int = 0


class NotebookLMNotebookCreate(BaseModel):
    title: str


class NotebookLMShareResponse(BaseModel):
    url: str | None = None


class NotebookLMContentGenerateRequest(BaseModel):
    notebook_id: str
    content_type: str = "slide_deck"
    prompt_template: str | None = None
    custom_prompt: str | None = None
    title: str | None = None
    wait: bool = True
    download: bool = True
    output_dir: str = "data/Outputs/notebooklm"


class NotebookLMBatchRequest(BaseModel):
    notebook_id: str
    types: str = "slide_deck,infographic"
    prompt_template: str | None = None
    custom_prompt: str | None = None
    output_dir: str = "data/Outputs/notebooklm"


class NotebookLMUploadRequest(BaseModel):
    notebook_id: str
    file_path: str
    title: str | None = None


class NotebookLMContentOut(BaseModel):
    id: str
    notebook_id: str
    notebook_title: str = ""
    preset_name: str = ""
    status: str = "active"
    is_permanent: bool = False
    expires_at: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class NotebookLMRetentionExtendRequest(BaseModel):
    hours: float = 48.0


class NotebookLMCleanupRequest(BaseModel):
    dry_run: bool = False
    skip_remote: bool = False


class NotebookLMCleanupResponse(BaseModel):
    total_checked: int = 0
    deleted_notebooks: list[str] = Field(default_factory=list)
    deleted_artifacts: list[str] = Field(default_factory=list)
    deleted_local_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Antigravity (agy)
# ---------------------------------------------------------------------------
class AgyStatusOut(BaseModel):
    installed: bool
    binary: str | None = None
    agy_version: str | None = None
    install_url: str | None = None


class AgySkillInfo(BaseModel):
    name: str
    available: bool
    installed: bool


class AgySkillsOut(BaseModel):
    skills: list[AgySkillInfo] = Field(default_factory=list)


class AgySkillInstallRequest(BaseModel):
    name: str


class AgySkillInstallResponse(BaseModel):
    installed: list[str] = Field(default_factory=list)


class AgyModelsOut(BaseModel):
    models: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsOut(BaseModel):
    env: str = "local"
    secret_key: str = "***"
    db_path: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    media_root: str = ""
    output_root: str = ""
    model_root: str = ""
    youtube_api_key: str | None = None
    notebooklm_enabled: bool = True
    notebooklm_mode: str = "storage_state"
    notebooklm_storage_state_path: str = ""
    notebooklm_profile: str = "default"
    notebooklm_templates_dir: str = ""
    notebooklm_sample_prompts_dir: str = ""
    notebooklm_default_retention_hours: float = 24.0
    notebooklm_auto_upload: bool = True
    notebooklm_default_content_types: str = "slide_deck,infographic"
    notebooklm_default_prompt: str = "financial_extraction"
    notebooklm_browser: str = "chromium"
    notebooklm_log_level: str = "WARNING"
    notebooklm_cdp_url: str | None = None
    notebooklm_upload_mode: str = "smart"
    notebooklm_max_bundle_size_mb: int = 190
    notebooklm_max_bundle_files: int = 50
    notebooklm_upload_text_only: bool = False
    yt_dlp_path: str | None = None
    yt_dlp_bypass_mode: str = "default"
    yt_dlp_cookiejar_path: str | None = None
    yt_dlp_cookies_browser: str | None = "chrome"
    yt_dlp_cookies_browser_profile: str | None = None
    yt_dlp_user_agent: str | None = None
    yt_dlp_extra_args: str | None = None
    yt_dlp_js_runtimes: str | None = None
    yt_dlp_hls_fallback_enabled: bool = True
    yt_dlp_update_strategy: str = "managed"
    video_resolution: str = "1080"
    video_format_fallback: bool = True
    frame_max_count: int = 200
    frame_min_interval_s: float = 10.0
    frame_hash_algo: str = "phash"
    frame_hash_threshold: int = 8
    frame_long_edge: int = 1280
    frame_jpeg_quality: int = 84
    frame_dedup_mode: str = "window"
    frame_dedup_window: int = 5
    frame_dedup_pipeline: str = "motion,phash,ssim,variance"
    frame_motion_threshold: float = 3.0
    frame_ssim_threshold: float = 0.90
    frame_hist_threshold: float = 0.95
    frame_dedup_ssim_window: int = 3
    output_formats: str = "pdf,markdown,notebooklm"
    presets_path: str = "config/presets"
    transcript_languages: str = "en,he,ar"
    whisper_model: str = "small"
    tool_update_enabled: bool = True
    tool_update_check_on_startup: bool = True
    tool_update_cadence: str = "weekly"
    tool_auto_update_yt_dlp: bool = True
    tool_auto_update_ffmpeg: bool = False
    tool_auto_update_whisper: bool = False
    scheduler_jobstore: str = "sqlite"
    scheduler_jobstore_path: str = ""
    retention_media_hours: float = 24.0
    retention_reports_hours: float = 168.0
    retention_cleanup_enabled: bool = True
    retention_dry_run: bool = False
    # Reason: surface POR-27 agy + notify env vars on the Settings page so
    # operators can configure them without editing .env by hand. User
    # story #20 calls this out explicitly.
    agy_enabled: bool = False
    agy_install_dir: str = ".agents/skills"
    agy_global_dir: str = "~/.gemini/config/skills"
    agy_default_skill: str = "web-video-presentation"
    agy_default_model: str | None = None
    agy_supported_models: str = ""
    agy_templates_dir: str = "config/prompts/agy"
    agy_sample_prompts_dir: str = "assets/prompts/agy"
    agy_default_wait_timeout: float = 600.0
    agy_output_dir: str = "data/Outputs/agy"
    agy_auto_provision_skills: bool = True
    agy_skills_auto_update: bool = False
    agy_skills_update_sources: str = "heredotnow/skill--skill here-now"
    notify_telegram_enabled: bool = False
    notify_telegram_bot_token: str | None = None
    notify_telegram_chat_id: str | None = None
    # Reason: expose social platform configuration so the Settings page can
    # display and edit binary paths, cookies, and platform toggles.
    social_default_lookback_hours: int = 12
    social_default_max_posts: int = 200
    social_reddit_enabled: bool = True
    social_stocktwits_enabled: bool = True
    social_x_enabled: bool = True
    twitter_cli_binary_path: str | None = None
    rdt_cli_binary_path: str | None = None
    reddit_cookie: str | None = None
    curl_cffi_impersonate: str = "chrome133a"
    stocktwits_api_base: str = "https://api.stocktwits.com/api/2/"


class SettingsUpdate(BaseModel):
    """Partial settings update — only provided fields are written to .env."""
    env: str | None = None
    secret_key: str | None = None
    db_path: str | None = None
    api_host: str | None = None
    api_port: int | None = None
    media_root: str | None = None
    output_root: str | None = None
    model_root: str | None = None
    youtube_api_key: str | None = None
    notebooklm_enabled: bool | None = None
    notebooklm_mode: str | None = None
    notebooklm_storage_state_path: str | None = None
    notebooklm_profile: str | None = None
    notebooklm_default_retention_hours: float | None = None
    notebooklm_auto_upload: bool | None = None
    notebooklm_default_content_types: str | None = None
    notebooklm_default_prompt: str | None = None
    notebooklm_browser: str | None = None
    notebooklm_log_level: str | None = None
    notebooklm_cdp_url: str | None = None
    notebooklm_upload_mode: str | None = None
    notebooklm_max_bundle_size_mb: int | None = None
    notebooklm_max_bundle_files: int | None = None
    notebooklm_upload_text_only: bool | None = None
    yt_dlp_path: str | None = None
    yt_dlp_bypass_mode: str | None = None
    yt_dlp_cookiejar_path: str | None = None
    yt_dlp_cookies_browser: str | None = None
    yt_dlp_cookies_browser_profile: str | None = None
    yt_dlp_user_agent: str | None = None
    yt_dlp_extra_args: str | None = None
    yt_dlp_js_runtimes: str | None = None
    yt_dlp_hls_fallback_enabled: bool | None = None
    yt_dlp_update_strategy: str | None = None
    video_resolution: str | None = None
    video_format_fallback: bool | None = None
    frame_max_count: int | None = None
    frame_min_interval_s: float | None = None
    frame_hash_algo: str | None = None
    frame_hash_threshold: int | None = None
    frame_long_edge: int | None = None
    frame_jpeg_quality: int | None = None
    frame_dedup_mode: str | None = None
    frame_dedup_window: int | None = None
    frame_dedup_pipeline: str | None = None
    frame_motion_threshold: float | None = None
    frame_ssim_threshold: float | None = None
    frame_hist_threshold: float | None = None
    frame_dedup_ssim_window: int | None = None
    output_formats: str | None = None
    presets_path: str | None = None
    transcript_languages: str | None = None
    whisper_model: str | None = None
    tool_update_enabled: bool | None = None
    tool_update_check_on_startup: bool | None = None
    tool_update_cadence: str | None = None
    tool_auto_update_yt_dlp: bool | None = None
    tool_auto_update_ffmpeg: bool | None = None
    tool_auto_update_whisper: bool | None = None
    scheduler_jobstore: str | None = None
    scheduler_jobstore_path: str | None = None
    retention_media_hours: float | None = None
    retention_reports_hours: float | None = None
    retention_cleanup_enabled: bool | None = None
    retention_dry_run: bool | None = None
    agy_enabled: bool | None = None
    agy_install_dir: str | None = None
    agy_global_dir: str | None = None
    agy_default_skill: str | None = None
    agy_default_model: str | None = None
    agy_supported_models: str | None = None
    agy_templates_dir: str | None = None
    agy_sample_prompts_dir: str | None = None
    agy_default_wait_timeout: float | None = None
    agy_output_dir: str | None = None
    agy_auto_provision_skills: bool | None = None
    agy_skills_auto_update: bool | None = None
    agy_skills_update_sources: str | None = None
    notify_telegram_enabled: bool | None = None
    notify_telegram_bot_token: str | None = None
    notify_telegram_chat_id: str | None = None
    social_default_lookback_hours: int | None = None
    social_default_max_posts: int | None = None
    social_reddit_enabled: bool | None = None
    social_stocktwits_enabled: bool | None = None
    social_x_enabled: bool | None = None
    twitter_cli_binary_path: str | None = None
    rdt_cli_binary_path: str | None = None
    reddit_cookie: str | None = None
    curl_cffi_impersonate: str | None = None
    stocktwits_api_base: str | None = None


# ---------------------------------------------------------------------------
# Social platform configuration / auth status
# ---------------------------------------------------------------------------
class TwitterStatusOut(BaseModel):
    """Authentication and connectivity status for X (Twitter)."""

    binary_found: bool = False
    version: str | None = None
    authenticated: bool = False
    last_check: str = ""
    message: str = ""


class RedditStatusOut(BaseModel):
    """Authentication and connectivity status for Reddit."""

    binary_found: bool = False
    version: str | None = None
    authenticated: bool = False
    last_check: str = ""
    message: str = ""


class StocktwitsStatusOut(BaseModel):
    """Connectivity status for the Stocktwits public API."""

    api_reachable: bool = False
    last_check: str = ""
    rate_limit_remaining: str | None = None
    message: str = ""


class SocialStatusOut(BaseModel):
    """Combined social platform status."""

    twitter: TwitterStatusOut = Field(default_factory=TwitterStatusOut)
    reddit: RedditStatusOut = Field(default_factory=RedditStatusOut)
    stocktwits: StocktwitsStatusOut = Field(default_factory=StocktwitsStatusOut)


class SocialAuthResponse(BaseModel):
    """Response from a social auth initiation request."""

    platform: str
    started: bool
    message: str


class SocialTestResponse(BaseModel):
    """Response from a social connectivity test request."""

    platform: str
    success: bool
    message: str


class SocialSourceResolveRequest(BaseModel):
    """Request to resolve/normalize a social source identifier."""

    platform: str
    identifier: str


class SocialSourceResolveResponse(BaseModel):
    """Response from resolving a social source identifier."""

    platform: str
    identifier: str
    resolved_identifier: str
    display_name: str
    exists: bool


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardStats(BaseModel):
    total_presets: int = 0
    active_presets: int = 0
    jobs_24h: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    videos_processed: int = 0
    notebooklm_notebooks: int = 0
    notebooklm_enabled: bool = False
    recent_jobs: list[JobOut] = Field(default_factory=list)
    recent_reports: list[ReportSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------
class ChannelResolveRequest(BaseModel):
    identifier: str


class ChannelResolveResponse(BaseModel):
    channel_id: str
    channel_title: str
    source: str = "youtube"


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
class PromptTemplateOut(BaseModel):
    name: str
    description: str
    target_types: list[str] = Field(default_factory=list)
    prompt: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    target_types: list[str] = Field(default_factory=list)
    prompt: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateUpdate(BaseModel):
    description: str | None = None
    target_types: list[str] | None = None
    prompt: str | None = None
    variables: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Single video fetch
# ---------------------------------------------------------------------------
class SingleVideoFetchRequest(BaseModel):
    url: str
    preset_name: str | None = None
    prompt_md: str = ""
    outputs: str = "pdf,markdown"


class SingleVideoFetchResponse(BaseModel):
    job_id: str
    video_id: str
    video_title: str
    message: str = "Fetch started"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportSummary(BaseModel):
    video_id: str
    title: str = ""
    channel_title: str = ""
    preset_name: str = ""
    preset_id: str = ""
    job_id: str = ""
    published_at: str = ""
    has_pdf: bool = False
    has_markdown: bool = False
    has_frames: bool = False
    frame_count: int = 0
    transcript_word_count: int = 0
    duration_seconds: int | None = None
    thumbnail_path: str | None = None
    report_path: str | None = None
    created_at: str = ""


class ReportDetail(BaseModel):
    video_id: str
    title: str = ""
    channel_title: str = ""
    preset_name: str = ""
    published_at: str = ""
    duration_seconds: int | None = None
    frame_count: int = 0
    transcript_word_count: int = 0
    has_pdf: bool = False
    has_markdown: bool = False
    has_frames: bool = False
    markdown_content: str = ""
    frame_paths: list[str] = Field(default_factory=list)
    report_path: str | None = None
    thumbnail_path: str | None = None
    # Reason: include NotebookLM generated content so the report is a
    # combined hub with both local data and generated artifacts.
    notebooklm_url: str | None = None
    notebooklm_generations: list[dict[str, Any]] = Field(default_factory=list)
    # Reason: include Antigravity generated content so the report hub
    # also shows the here.now public link and local artifact path.
    agy_herenow_url: str | None = None
    agy_artifact_path: str | None = None


# ---------------------------------------------------------------------------
# NotebookLM auth login
# ---------------------------------------------------------------------------
class NotebookLMLoginRequest(BaseModel):
    headless: bool = False


class NotebookLMCookieLoginRequest(BaseModel):
    cookie_header: str


class NotebookLMLoginResponse(BaseModel):
    success: bool
    message: str
    storage_path: str | None = None


# ---------------------------------------------------------------------------
# Plugin / tool status
# ---------------------------------------------------------------------------
class PluginStatusOut(BaseModel):
    """Status of a single runtime plugin (yt-dlp, ffmpeg, whisper)."""
    name: str
    display_name: str
    installed_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    auto_update_enabled: bool = False
    binary_path: str | None = None
    last_checked: str | None = None
    last_updated: str | None = None
    update_message: str | None = None


class PluginUpdateResultOut(BaseModel):
    """Result of a plugin update or check action."""
    plugin: str
    action: str
    from_version: str | None = None
    to_version: str | None = None
    success: bool
    message: str
    timestamp: str


class PluginUpdateLogOut(BaseModel):
    """A single entry in the plugin update history log."""
    timestamp: str
    plugin: str
    action: str
    from_version: str | None = None
    to_version: str | None = None
    success: bool
    message: str
