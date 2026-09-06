from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAMDOC_", env_file=".env")

    env: str = "local"
    secret_key: str = "change-me"
    db_path: str = "data/State/streamdoc.sqlite"
    media_root: str = "data/Media"
    output_root: str = "data/Outputs"
    model_root: str = "data/Models"
    youtube_api_key: str | None = None
    # NotebookLM Integration
    notebooklm_enabled: bool = True  # Installed by default, can disable
    notebooklm_mode: str = "storage_state"
    notebooklm_storage_state_path: str = (
        "data/integrations/notebooklm/storage_state.json"
    )
    notebooklm_profile: str = "default"
    notebooklm_account: str | None = None
    notebooklm_templates_dir: str = "config/prompts/notebooklm"
    # Reason: user-created prompts go to config/ (gitignored), not assets/ (tracked).
    # assets/prompts/notebooklm/ holds shipped sample templates only.
    notebooklm_sample_prompts_dir: str = "assets/prompts/notebooklm"
    notebooklm_default_retention_hours: float = 24.0
    notebooklm_auto_upload: bool = True  # Auto-upload after fetch
    notebooklm_default_content_types: str = "slide_deck,infographic"  # Comma-separated
    notebooklm_default_prompt: str = "financial_extraction"
    notebooklm_default_wait_timeout: float = 600.0  # Generation wait timeout (10 min)

    # Runtime dependency discovery:
    # - yt_dlp_path: explicit binary path
    # - yt_dlp_module_path: optional module-style binary in a managed install
    yt_dlp_path: str | None = None
    yt_dlp_module_path: str | None = None
    # Reason: po_token is the default bypass mode. It uses a PO Token
    # provider container (bgutil-ytdlp-pot-provider) to generate
    # Proof-of-Origin tokens that bypass YouTube's bot detection without
    # needing browser cookies. The container is auto-started on app
    # startup if Docker is available; otherwise the app falls back to
    # the configured fallback mode (default: no-auth).
    # Options: po_token | web_embedded | cookies_from_browser | cookie | default
    # web_embedded: Uses the WEB_EMBEDDED_PLAYER client which bypasses
    #   IP-level 403 blocks on DASH/HTTPS media downloads and gets
    #   full-quality URLs (up to 4K) without PO tokens or cookies.
    #   Requires a JS runtime (node/deno) for n-challenge solving.
    #   Does not work for videos with embedding disabled.
    yt_dlp_bypass_mode: str = "po_token"
    # Reason: ordered comma-separated list of bypass modes to try in
    # sequence. Each mode is tried in order; on retriable failure (403,
    # bot detection, rate limit, cookie DB lock) the next mode is tried.
    # On success or permanent error (private/deleted) the chain stops.
    # When non-empty, this takes precedence over yt_dlp_bypass_mode and
    # yt_dlp_bypass_fallback_mode (those become backward-compat fallbacks
    # used only when the chain is empty).
    # Supported modes:
    #   web_embedded — full quality (up to 4K), no PO token, no cookies;
    #     bypasses IP 403; needs JS runtime; fails on embedding-disabled.
    #   po_token — PO token via bgutil container; needs Docker; SABR-only
    #     on web client (formats may be skipped).
    #   cookie — Netscape jar at yt_dlp_cookiejar_path; needs manual export.
    #   cookies_from_browser — reads live browser session; fails if browser
    #     is running on Windows (cookie DB locked). OPT-IN: ban risk on
    #     personal profiles — use a dedicated browser profile.
    #   hls — web_safari client + HLS formats; bypasses IP 403 but capped
    #     at 480p; needs JS runtime; quality-degraded last resort.
    #   default — yt-dlp built-in client selection; no bypass.
    yt_dlp_bypass_chain: str = "web_embedded,po_token,cookies_from_browser,hls"
    yt_dlp_cookiejar_path: str | None = "data/cookies/youtube.txt"
    yt_dlp_pot_provider: str | None = None
    yt_dlp_user_agent: str | None = None
    yt_dlp_extra_args: str | None = None
    # Reason: yt-dlp 2026.07+ requires an external JavaScript runtime to solve
    # YouTube's n-challenge (EJS system). Without it, yt-dlp reports
    # "JS runtimes: none" and downloads fail with "Sign in to confirm you're
    # not a bot" or "Requested format is not available". The yt-dlp-ejs
    # package (challenge solver scripts) must also be installed.
    # Deno is yt-dlp's default, but Node is more commonly available.
    # Options: node | deno | bun | quickjs | comma-separated list (e.g. "node,deno")
    # Set to empty string to disable (not recommended — downloads will fail).
    yt_dlp_js_runtimes: str = "node"
    # Reason: YouTube periodically IP-blocks DASH/HTTPS media downloads
    # (returns HTTP 403 on the format URL) while HLS (m3u8) formats from
    # the web_safari client remain accessible. When enabled, the download
    # function retries with the web_safari client + HLS format selector
    # after a 403 error on the primary DASH download. HLS is typically
    # limited to 480p, so this is a quality-degraded fallback, not a
    # primary path. Disable if you prefer to fail fast on 403.
    yt_dlp_hls_fallback_enabled: bool = True
    # Reason: when bypass_mode=cookies_from_browser, yt-dlp reads cookies
    # directly from the user's signed-in browser session via
    # --cookies-from-browser. This avoids the need for a separate PO-token
    # service or manually exported cookie jar. Supported browsers: chrome,
    # edge, firefox, brave, chromium, opera, safari, vivaldi.
    # WARNING: using cookies_from_browser with your active/personal browser
    # profile risks getting your YouTube account banned by YouTube's bot
    # detection. This mode is OPT-IN — it is never used as an automatic
    # fallback. Only enable it if you understand the risk, and prefer using
    # a dedicated/separate browser profile (yt_dlp_cookies_browser_profile)
    # rather than your daily-driver profile.
    yt_dlp_cookies_browser: str | None = "chrome"
    # Optional browser profile name (e.g. "Default", "Profile 1").
    yt_dlp_cookies_browser_profile: str | None = None
    # Reason: fallback bypass mode used when the primary mode fails with a
    # transient error (bot detection, rate limiting, HTTP 403, cookie DB lock)
    # or when po_token mode is active but Docker is not available to run the
    # POT provider container. The default is "default" (no-auth) which is
    # safe but may hit bot detection on some videos.
    # Options: po_token | web_embedded | cookie | cookies_from_browser | default | (empty = disabled)
    # WARNING: cookies_from_browser reads from the user's ACTIVE browser
    # profile and can get their YouTube account banned. It should never be
    # used as an automatic fallback — only set it explicitly if you accept
    # the risk and ideally use a dedicated browser profile.
    yt_dlp_bypass_fallback_mode: str | None = "default"
    yt_dlp_update_strategy: str = "managed"  # managed | docker_image | disabled
    # Reason: PO Token provider container settings. We use the official
    # brainicism/bgutil-ytdlp-pot-provider image (TypeScript/Node.js) which
    # matches the version of the bgutil plugin built into yt-dlp. The Rust
    # rewrite (ghcr.io/jim60105/bgutil-pot) uses a different versioning
    # scheme and is INCOMPATIBLE with yt-dlp's built-in plugin — using it
    # causes a major-version mismatch that makes yt-dlp refuse to fetch
    # tokens, silently defeating the entire PO Token bypass.
    # The :latest tag tracks the latest stable release (currently 1.3.1).
    pot_provider_url: str = "http://127.0.0.1:4416"
    pot_provider_image: str = "brainicism/bgutil-ytdlp-pot-provider:latest"
    pot_provider_container_name: str = "streamdoc-pot"
    # Reason: when True, the app automatically starts the POT container
    # on startup if Docker is available and bypass_mode=po_token. Set to
    # False to manage the container manually (e.g. via `just pot-up`).
    pot_auto_start: bool = True

    # Shorts filtering: skip videos on the /shorts/ tab or shorter than this threshold.
    # Duration threshold is a fallback for RSS/API listings where the URL does not
    # indicate whether a video is a Short.
    skip_shorts: bool = True
    shorts_max_seconds: int = 60

    # Video download quality
    video_resolution: str = "1080"  # 1080 | 720 | 480 | best
    video_format_fallback: bool = True  # fallback to next best if preferred not available

    # Frame / visual settings
    frame_max_count: int = 200
    frame_min_interval_s: float = 10.0
    frame_hash_algo: str = "phash"  # phash | dhash | ahash
    frame_hash_threshold: int = 8   # Hamming distance threshold for dedup (lower = stricter)
    frame_long_edge: int = 1280
    frame_jpeg_quality: int = 84
    frame_dedup_mode: str = "window"  # global | window (window compares only to last N frames)
    frame_dedup_window: int = 5       # for window mode: compare against last N kept frames

    # Multi-stage dedup pipeline — comma-separated list of stage names.
    # Available stages: motion, phash, ssim, hist, variance
    # Example: "motion,phash,ssim,variance"  (runs left-to-right)
    frame_dedup_pipeline: str = "motion,phash,ssim,variance"

    # Stage-specific thresholds
    frame_motion_threshold: float = 3.0   # mean abs pixel diff (0-255); below = duplicate
    frame_ssim_threshold: float = 0.90   # SSIM > threshold = duplicate (1.0 = identical)
    frame_hist_threshold: float = 0.95   # histogram correlation > threshold = duplicate
    frame_dedup_ssim_window: int = 3     # SSIM compare to last N kept frames

    # Outputs
    output_formats: str = "pdf,markdown,notebooklm"
    presets_path: str = "config/presets"

    # Transcript prefs
    transcript_languages: str = "en,he,ar"
    whisper_model: str = "small"
    # Reason: Whisper on CPU can be extremely slow for long videos (30+ min
    # for a 20-minute video with the "small" model). This timeout prevents
    # a single slow transcription from blocking the entire job indefinitely.
    # When exceeded, the video is skipped with an empty transcript.
    whisper_timeout_seconds: float = 600.0  # 10 minutes
    # Reason: yt-dlp subtitle fallback. When the youtube-transcript-api
    # fails (e.g. rate-limited or blocked), yt-dlp can fetch the same
    # caption data via the timedtext endpoint using the configured cookie
    # jar / PO-token bypass. This fetches the SAME data the official API
    # would return (no quality difference). Default OFF because fixing the
    # API call makes the official API work for ~90%+ of videos; this is
    # only needed as an edge-case fallback. When OFF, falls back directly
    # to local Whisper transcription.
    use_yt_dlp_subtitles: bool = False

    # Runtime tooling
    tool_update_enabled: bool = True
    tool_update_check_on_startup: bool = True
    tool_update_cadence: str = "weekly"  # daily | weekly | manual
    tool_auto_update_yt_dlp: bool = True
    tool_auto_update_ffmpeg: bool = False
    tool_auto_update_whisper: bool = False
    tool_auto_update_notebooklm: bool = True

    # API / Web GUI
    api_host: str = "0.0.0.0"
    api_port: int = 5454

    # Scheduler
    scheduler_jobstore: str = "sqlite"
    scheduler_jobstore_path: str = "data/State/scheduler.sqlite"
    scheduler_max_workers: int = 3  # Max parallel scheduled preset runs

    # Retention policy (hours)
    retention_media_hours: float = 24.0
    retention_reports_hours: float = 168.0
    retention_cleanup_enabled: bool = True
    retention_dry_run: bool = False
    # Reason: cleanup also runs on a schedule (not just after job completion)
    # so that files and notebooks are deleted even when no jobs complete
    # successfully (e.g., a job hangs or the server restarts).
    retention_cleanup_interval_minutes: float = 60.0

    # NotebookLM / external upload strategy
    notebooklm_upload_mode: str = "smart"  # individual | combined | smart
    notebooklm_max_bundle_size_mb: int = 190
    notebooklm_max_bundle_files: int = 50
    notebooklm_upload_text_only: bool = False

    # Session keepalive — background task interval in minutes.
    # Google's main session cookies (SID, HSID, SAPISID) last 2 years,
    # and the rotation tokens (__Secure-1PSIDTS) are refreshed every
    # ~10 minutes via RotateCookies. We open a long-lived
    # NotebookLMClient with this interval so the upstream keepalive task
    # rotates cookies automatically. If rotation fails, NOTEBOOKLM_HEADLESS_REAUTH
    # lets notebooklm-py 0.8.0+ re-mint cookies from the persistent browser
    # profile. The session persists for up to 2 years as long as the
    # keepalive runs — same as a real Chrome browser.
    notebooklm_keepalive_interval_minutes: float = 30.0
    notebooklm_browser: str = "chromium"  # chromium | chrome | msedge
    notebooklm_log_level: str = "WARNING"  # WARNING | INFO | DEBUG
    # Optional Chrome DevTools Protocol endpoint for unattended re-auth.
    # Start Chrome with --remote-debugging-port=9222 and point this at
    # http://localhost:9222 so headless re-auth can attach to your live
    # signed-in browser instead of the dedicated (and easily stale) profile.
    notebooklm_cdp_url: str | None = None

    # Social sentiment pipeline defaults — POR-11.
    social_default_lookback_hours: int = 12
    social_default_max_posts: int = 200
    social_reddit_enabled: bool = True
    social_stocktwits_enabled: bool = True
    social_x_enabled: bool = True
    twitter_cli_binary_path: str | None = None
    rdt_cli_binary_path: str | None = None
    reddit_cookie: str | None = None
    twitter_auth_token: str | None = None
    twitter_ct0: str | None = None
    social_browser: str = "chromium"
    social_cdp_url: str | None = None
    social_auth_storage_root: str = "data/integrations/social"
    social_login_timeout_seconds: float = 300.0
    social_refresh_timeout_seconds: float = 30.0
    social_auth_refresh_interval_hours: float = 6.0
    curl_cffi_impersonate: str = "chrome133a"
    stocktwits_api_base: str = "https://api.stocktwits.com/api/2/"

    # CLI tool (agy) integration — POR-11.
    cli_tool_default: str | None = None
    agy_binary_path: str | None = None

    # Antigravity (agy) integration — POR-27.
    # Reason: agy is a sibling generation backend to NotebookLM. It is a
    # npm/npx-based CLI invoked as a subprocess; StreamDoc owns the
    # skill installation + prompt plumbing but the operator installs
    # the agy binary itself. All defaults are conservative so existing
    # deployments that never opt in behave exactly as before.
    agy_enabled: bool = False
    # Where StreamDoc writes its vendored skills (`.agents/skills/` is
    # the workspace-shared location, mirrored from the official agy
    # docs). Falls back to the global dir below if it cannot be created.
    agy_install_dir: str = ".agents/skills"
    agy_global_dir: str = "~/.gemini/config/skills"
    # Default agy skill + model when a preset selects agy but doesn't
    # pin either. The default skill is the garden-skills
    # web-video-presentation preset per the POR-27 PRD.
    agy_default_skill: str = "web-video-presentation"
    agy_default_model: str | None = None
    # Comma-separated allowlist of agy model ids exposed in the UI.
    # Empty means "let the CLI validate at invoke time". The CLI is
    # always the source of truth — we just pre-filter in the UI.
    agy_supported_models: str = ""
    # Prompt template dirs: samples are shipped in the repo under
    # assets/prompts/agy/; user overrides go under config/prompts/agy/
    # (gitignored, parallel to the notebooklm split).
    agy_templates_dir: str = "config/prompts/agy"
    agy_sample_prompts_dir: str = "assets/prompts/agy"
    # Per-invocation wait timeout (seconds) when StreamDoc runs agy on
    # behalf of a preset. Mirrors notebooklm_default_wait_timeout.
    agy_default_wait_timeout: float = 600.0
    # Where agy artifacts are stored locally. Mirrors the NotebookLM
    # layout (data/Outputs/notebooklm/<id>/).
    agy_output_dir: str = "data/Outputs/agy"
    # Reason: auto-provision vendored skills on startup so a fresh
    # install or prod deployment has all skills in .agents/skills/
    # without manual action. When True, app startup calls
    # skills.install_all() which copies assets/skills/agy/* into the
    # install dir. Idempotent — existing skills are skipped unless
    # agy_skills_auto_update is also True.
    agy_auto_provision_skills: bool = True
    # Reason: auto-update skills from upstream on startup. When True,
    # startup runs `npx skills add <source>` for each configured source
    # to fetch the latest skill revision, then re-installs the vendored
    # copy. This is the "plugin auto-update" path. When False, skills
    # are only updated via the manual "Update from upstream" button on
    # the Antigravity page (which calls the same npx command on demand).
    agy_skills_auto_update: bool = False
    # Reason: comma-separated list of upstream skill sources for the
    # `npx skills add` command. Each entry is a "<repo>--skill <name>"
    # pair (the npx skills CLI syntax). The here.now skill is the
    # primary upstream; additional sources can be added without code
    # changes. Example: "heredotnow/skill--skill here-now"
    agy_skills_update_sources: str = "heredotnow/skill--skill here-now"

    # Notification — fast-messaging integrations (POR-27).
    # Reason: the PRD's user story #9 calls out Telegram as a
    # post-success notifier. We keep it pluggable + env-gated so
    # operators can opt in without code changes, and the T4 task can
    # add a Notifier registry without touching this schema layer.
    notify_telegram_enabled: bool = False
    notify_telegram_bot_token: str | None = None
    notify_telegram_chat_id: str | None = None


settings = Settings()
