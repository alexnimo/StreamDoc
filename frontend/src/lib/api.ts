const API_BASE = '/api'

async function fetchJSON<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // Dashboard
  getStats: () => fetchJSON<DashboardStats>('/dashboard/stats'),

  // Presets
  listPresets: () => fetchJSON<Preset[]>('/presets'),
  getPreset: (id: string) => fetchJSON<Preset>(`/presets/${id}`),
  createPreset: (data: Partial<Preset>) =>
    fetchJSON<Preset>('/presets', { method: 'POST', body: JSON.stringify(data) }),
  updatePreset: (id: string, data: Partial<Preset>) =>
    fetchJSON<Preset>(`/presets/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePreset: (id: string) =>
    fetchJSON<{ deleted: string }>(`/presets/${id}`, { method: 'DELETE' }),

  // Channel resolution
  resolveChannel: (identifier: string) =>
    fetchJSON<ChannelResolveResponse>('/channels/resolve', {
      method: 'POST',
      body: JSON.stringify({ identifier }),
    }),

  // Fetch
  startFetch: (preset: string, lookbackHours?: number) =>
    fetchJSON<{ job_id: string; preset: string; message: string }>(
      `/fetch/${preset}`,
      { method: 'POST', body: JSON.stringify({ lookback_hours: lookbackHours }) },
    ),
  fetchSingleVideo: (data: SingleVideoFetchRequest) =>
    fetchJSON<SingleVideoFetchResponse>('/fetch/single', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Reports
  listReports: (preset?: string, limit?: number) =>
    fetchJSON<ReportSummary[]>(`/reports${preset ? `?preset=${preset}` : ''}${limit ? `${preset ? '&' : '?'}limit=${limit}` : ''}`),
  getReport: (videoId: string) =>
    fetchJSON<ReportDetail>(`/reports/${videoId}`),
  downloadReport: (videoId: string, format: string) =>
    `${API_BASE}/reports/download/${videoId}?format=${format}`,
  downloadGeneration: (generationId: string) =>
    `${API_BASE}/reports/generation/${generationId}/download`,
  downloadJobArtifact: (jobId: string, contentType: string) =>
    `${API_BASE}/reports/job/${jobId}/artifact/${contentType}/download`,

  // Prompt templates
  listPrompts: () => fetchJSON<PromptTemplate[]>('/prompts'),
  getPrompt: (name: string) => fetchJSON<PromptTemplate>(`/prompts/${name}`),
  createPrompt: (data: PromptTemplateCreate) =>
    fetchJSON<PromptTemplate>('/prompts', { method: 'POST', body: JSON.stringify(data) }),
  updatePrompt: (name: string, data: Partial<PromptTemplateCreate>) =>
    fetchJSON<PromptTemplate>(`/prompts/${name}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePrompt: (name: string) =>
    fetchJSON<{ deleted: string }>(`/prompts/${name}`, { method: 'DELETE' }),

  // Jobs
  listJobs: (limit = 20, status?: string) =>
    fetchJSON<Job[]>(`/jobs?limit=${limit}${status ? `&status=${status}` : ''}`),
  getJob: (id: string) => fetchJSON<Job>(`/jobs/${id}`),
  retryJob: (id: string) =>
    fetchJSON<{ results: Record<string, string> }>(`/jobs/${id}/retry`, { method: 'POST' }),
  resendJob: (id: string, destination: string) =>
    fetchJSON<{ results: Record<string, string> }>(
      `/jobs/${id}/resend`,
      { method: 'POST', body: JSON.stringify({ destination }) },
    ),
  cancelJob: (id: string) =>
    fetchJSON<{ status: string; job_id: string }>(`/jobs/${id}/cancel`, { method: 'POST' }),

  // Scheduler
  listScheduledJobs: () => fetchJSON<ScheduledJob[]>('/scheduler/jobs'),
  addScheduledJob: (preset: string, schedule: string) =>
    fetchJSON<ScheduledJob>('/scheduler/jobs', {
      method: 'POST',
      body: JSON.stringify({ preset, schedule }),
    }),
  removeScheduledJob: (preset: string) =>
    fetchJSON<{ removed: string }>(`/scheduler/jobs/${preset}`, { method: 'DELETE' }),
  runOnce: (preset: string) =>
    fetchJSON<{ preset: string; status: string }>(`/scheduler/run/${preset}`, { method: 'POST' }),

  // Cleanup
  runCleanup: (dryRun: boolean) =>
    fetchJSON<{ counts: Record<string, number> }>('/cleanup', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun }),
    }),

  // NotebookLM
  getNotebookLMAuthStatus: () =>
    fetchJSON<NotebookLMAuthStatus>('/notebooklm/auth/status'),
  loginNotebookLM: (headless?: boolean) =>
    fetchJSON<NotebookLMLoginResponse>('/notebooklm/auth/login', {
      method: 'POST',
      body: JSON.stringify({ headless: headless ?? false }),
    }),
  loginNotebookLMWithCookies: (cookieHeader: string) =>
    fetchJSON<NotebookLMLoginResponse>('/notebooklm/auth/login-cookie', {
      method: 'POST',
      body: JSON.stringify({ cookie_header: cookieHeader }),
    }),
  logoutNotebookLM: () =>
    fetchJSON<{ deleted: boolean }>('/notebooklm/auth/logout', { method: 'POST' }),
  listNotebooks: () => fetchJSON<Notebook[]>('/notebooklm/notebooks'),
  createNotebook: (title: string) =>
    fetchJSON<Notebook>('/notebooklm/notebooks', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  deleteNotebook: (id: string) =>
    fetchJSON<{ deleted: string }>(`/notebooklm/notebooks/${id}`, { method: 'DELETE' }),
  shareNotebook: (id: string) =>
    fetchJSON<{ url: string | null }>(`/notebooklm/notebooks/${id}/share`, { method: 'POST' }),
  generateContent: (data: NotebookLMGenerateRequest) =>
    fetchJSON<Record<string, unknown>>('/notebooklm/content/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  batchGenerate: (data: NotebookLMBatchRequest) =>
    fetchJSON<Record<string, unknown>>('/notebooklm/content/batch', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  uploadContent: (data: NotebookLMUploadRequest) =>
    fetchJSON<Record<string, unknown>>('/notebooklm/content/upload', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listRetention: () => fetchJSON<RetentionContent[]>('/notebooklm/retention'),
  cleanupRetention: (dryRun: boolean, skipRemote: boolean) =>
    fetchJSON<RetentionCleanupResult>('/notebooklm/retention/cleanup', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun, skip_remote: skipRemote }),
    }),
  extendRetention: (id: string, hours: number) =>
    fetchJSON<Record<string, unknown>>(`/notebooklm/retention/${id}/extend`, {
      method: 'POST',
      body: JSON.stringify({ hours }),
    }),
  makePermanent: (id: string) =>
    fetchJSON<Record<string, unknown>>(`/notebooklm/retention/${id}/permanent`, {
      method: 'POST',
    }),

  // NotebookLM generations (async tracking)
  listGenerations: (status?: string) =>
    fetchJSON<GenerationRecord[]>(`/notebooklm/generations${status ? `?status=${status}` : ''}`),
  pollGenerations: () =>
    fetchJSON<{ message: string }>('/notebooklm/generations/poll', { method: 'POST' }),

  // Settings
  getSettings: () => fetchJSON<Settings>('/settings'),
  updateSettings: (data: Record<string, unknown>) =>
    fetchJSON<{ updated: string[]; count: number }>('/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Social configuration
  getSocialStatus: () => fetchJSON<SocialStatus>('/social/status'),
  authSocialPlatform: (platform: string) =>
    fetchJSON<SocialAuthResponse>(`/social/auth/${platform}`, { method: 'POST' }),
  testSocialPlatform: (platform: string) =>
    fetchJSON<SocialTestResponse>(`/social/test/${platform}`, { method: 'POST' }),
  resolveSocialSource: (platform: string, identifier: string) =>
    fetchJSON<SocialSourceResolveResponse>('/social/resolve', {
      method: 'POST',
      body: JSON.stringify({ platform, identifier }),
    }),

  // Antigravity (agy)
  agy: {
    status: () => fetchJSON<Record<string, unknown>>('/agy/status'),
    listSkills: () => fetchJSON<AgySkillInfo[]>('/agy/skills'),
    listAvailableSkills: () => fetchJSON<AgySkillInfo[]>('/agy/skills/available'),
    installSkill: (name: string) =>
      fetchJSON<Record<string, unknown>>('/agy/skills/install', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
    installAll: () =>
      fetchJSON<Record<string, unknown>>('/agy/skills/install-all', { method: 'POST' }),
    updateFromUpstream: () =>
      fetchJSON<Record<string, unknown>>('/agy/skills/update-from-upstream', { method: 'POST' }),
    supportedModels: async (): Promise<string[]> => {
      const response = await fetchJSON<{ models: string[] }>('/agy/models')
      return response.models || []
    },
    listPresetReports: (presetName: string) =>
      fetchJSON<AgyReportFile[]>(`/agy/reports/${encodeURIComponent(presetName)}`),
  },

  // CLI Tools
  listCliTools: () => fetchJSON<CLITool[]>('/cli-tools'),
  detectCliTool: (name: string) =>
    fetchJSON<CLITool>(`/cli-tools/${name}/detect`, { method: 'POST' }),
  installCliTool: (name: string) =>
    fetchJSON<CLITool>(`/cli-tools/${name}/install`, { method: 'POST' }),

  // Plugins / Tools (yt-dlp, ffmpeg, whisper)
  listPlugins: () => fetchJSON<PluginStatus[]>('/tools/plugins'),
  checkAllPlugins: () =>
    fetchJSON<PluginStatus[]>('/tools/plugins/check', { method: 'POST' }),
  checkPlugin: (name: string) =>
    fetchJSON<PluginStatus>(`/tools/plugins/${name}/check`, { method: 'POST' }),
  updatePlugin: (name: string) =>
    fetchJSON<PluginUpdateResult>(`/tools/plugins/${name}/update`, { method: 'POST' }),
  getPluginLogs: (limit = 50) =>
    fetchJSON<PluginUpdateLog[]>(`/tools/logs?limit=${limit}`),
  getPotStatus: () => fetchJSON<PotProviderStatus>('/tools/pot-status'),

  // Notifications
  getNotifications: () => fetchJSON<NotificationList>('/notifications'),
}

// SSE stream URL helper
export function sseUrl(jobId: string): string {
  return `${API_BASE}/fetch/${jobId}/stream`
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface DashboardStats {
  total_presets: number
  active_presets: number
  jobs_24h: number
  jobs_completed: number
  jobs_failed: number
  videos_processed: number
  notebooklm_notebooks: number
  notebooklm_enabled: boolean
  recent_jobs: Job[]
  recent_reports: ReportSummary[]
}

export interface ChannelResolveResponse {
  channel_id: string
  channel_title: string
  source: string
}

export interface PromptTemplate {
  name: string
  description: string
  target_types: string[]
  prompt: string
  variables: Record<string, unknown>
}

export interface PromptTemplateCreate {
  name: string
  description: string
  target_types: string[]
  prompt: string
  variables: Record<string, unknown>
}

export interface SingleVideoFetchRequest {
  url: string
  preset_name?: string
  prompt_md?: string
  outputs?: string
}

export interface SingleVideoFetchResponse {
  job_id: string
  video_id: string
  video_title: string
  message: string
}

export interface ReportSummary {
  video_id: string
  title: string
  channel_title: string
  preset_name: string
  preset_id: string
  job_id: string
  published_at: string
  has_pdf: boolean
  has_markdown: boolean
  has_frames: boolean
  frame_count: number
  transcript_word_count: number
  duration_seconds: number | null
  thumbnail_path: string | null
  report_path: string | null
  created_at: string
}

export interface ReportDetail {
  video_id: string
  title: string
  channel_title: string
  preset_name: string
  published_at: string
  duration_seconds: number | null
  frame_count: number
  transcript_word_count: number
  has_pdf: boolean
  has_markdown: boolean
  has_frames: boolean
  markdown_content: string
  frame_paths: string[]
  report_path: string | null
  thumbnail_path: string | null
  notebooklm_url: string | null
  notebooklm_generations: NotebookLMGenerationInfo[]
  agy_herenow_url: string | null
  agy_artifact_path: string | null
}

export interface NotebookLMGenerationInfo {
  id: string
  content_type: string
  status: string
  local_path: string | null
  notebook_id: string
}

export interface NotebookLMLoginResponse {
  success: boolean
  message: string
  storage_path: string | null
}

export interface Preset {
  id: string
  name: string
  preset_type: string  // "youtube" | "social"
  channel_list_id: string | null
  channel_names: string | null
  prompt_md: string
  // Social preset fields (only used when preset_type="social")
  social_sources: string | null  // JSON array: [{"platform": "reddit", "identifier": "...", "max_posts": 100}]
  social_max_posts: number | null
  social_lookback_hours: number | null
  outputs: string
  notebooklm_kind: string | null
  notebooklm_prompt_template: string | null
  notebooklm_retry_failed: boolean
  notebooklm_retry_attempts: number
  notebooklm_retry_delay_minutes: number
  agy_enabled: boolean
  agy_skill: string | null
  agy_model: string | null
  agy_publish_herenow: boolean
  agy_prompt_template: string | null
  agy_existing_report: string | null
  schedule: string | null
  schedule_interval_hours: number | null
  lookback_hours: number | null
  max_videos: number | null
  text_filter: string | null
  date_range_days: number | null
  playlist_mode: boolean
  skip_processed: boolean
  active: boolean
  retention_enabled: boolean
  file_retention_hours: number | null
  notebook_retention_hours: number | null
}

export interface Job {
  id: string
  preset_name: string
  status: string
  created_at: string
  completed_at: string | null
  artifact_count: number
  destinations: Record<string, string>
  errors: string[]
  details: {
    videos?: Array<{
      video_id: string
      title: string
      channel_title: string
      duration_seconds: number | null
      frame_count: number
      transcript_word_count: number
    }>
    stats?: {
      total_videos: number
      total_duration_seconds: number
      total_frames: number
      total_transcript_words: number
    }
    artifacts?: Array<{
      video_id: string
      title: string
      md_path: string | null
      pdf_path: string | null
      status: string
    }>
    integrations?: Record<string, string>
  }
}

export interface ScheduledJob {
  id: string
  preset: string
  schedule: string
  trigger: string
}

export interface NotebookLMAuthStatus {
  profile: string
  storage_path: string
  configured: boolean
  is_valid: boolean
  is_fresh: boolean
  message: string
}

export interface Notebook {
  id: string
  title: string
  sources_count: number
}

export interface NotebookLMGenerateRequest {
  notebook_id: string
  content_type: string
  prompt_template?: string
  custom_prompt?: string
  title?: string
  wait?: boolean
  download?: boolean
  output_dir?: string
}

export interface NotebookLMBatchRequest {
  notebook_id: string
  types: string
  prompt_template?: string
  custom_prompt?: string
  output_dir?: string
}

export interface NotebookLMUploadRequest {
  notebook_id: string
  file_path: string
  title?: string
}

export interface RetentionContent {
  id: string
  notebook_id: string
  notebook_title: string
  preset_name: string
  status: string
  is_permanent: boolean
  expires_at: string | null
  artifacts: Record<string, unknown>[]
}

export interface RetentionCleanupResult {
  total_checked: number
  deleted_notebooks: string[]
  deleted_artifacts: string[]
  deleted_local_files: string[]
  errors: string[]
}

export interface SSEEvent {
  job_id: string
  step: string
  message: string
  progress: number | null
  video_title: string | null
  status: string
  timestamp: string
}

export interface GenerationRecord {
  id: string
  job_id: string
  notebook_id: string
  task_id: string
  content_type: string
  status: string // pending | in_progress | completed | failed
  artifact_id: string
  local_path: string
  error: string
  created_at: string
  updated_at: string
}

export interface Settings {
  env: string
  secret_key: string
  db_path: string
  api_host: string
  api_port: number
  media_root: string
  output_root: string
  model_root: string
  youtube_api_key: string | null
  notebooklm_enabled: boolean
  notebooklm_mode: string
  notebooklm_storage_state_path: string
  notebooklm_profile: string
  notebooklm_templates_dir: string
  notebooklm_sample_prompts_dir: string
  notebooklm_default_retention_hours: number
  notebooklm_auto_upload: boolean
  notebooklm_default_content_types: string
  notebooklm_default_prompt: string
  notebooklm_upload_mode: string
  notebooklm_max_bundle_size_mb: number
  notebooklm_max_bundle_files: number
  notebooklm_upload_text_only: boolean
  yt_dlp_path: string | null
  yt_dlp_bypass_mode: string
  yt_dlp_cookiejar_path: string | null
  yt_dlp_cookies_browser: string | null
  yt_dlp_cookies_browser_profile: string | null
  yt_dlp_user_agent: string | null
  yt_dlp_extra_args: string | null
  yt_dlp_update_strategy: string
  video_resolution: string
  video_format_fallback: boolean
  frame_max_count: number
  frame_min_interval_s: number
  frame_hash_algo: string
  frame_hash_threshold: number
  frame_long_edge: number
  frame_jpeg_quality: number
  frame_dedup_mode: string
  frame_dedup_window: number
  frame_dedup_pipeline: string
  frame_motion_threshold: number
  frame_ssim_threshold: number
  frame_hist_threshold: number
  frame_dedup_ssim_window: number
  output_formats: string
  presets_path: string
  transcript_languages: string
  whisper_model: string
  tool_update_enabled: boolean
  tool_update_check_on_startup: boolean
  tool_update_cadence: string
  tool_auto_update_yt_dlp: boolean
  tool_auto_update_ffmpeg: boolean
  tool_auto_update_whisper: boolean
  scheduler_jobstore: string
  scheduler_jobstore_path: string
  retention_media_hours: number
  retention_reports_hours: number
  retention_cleanup_enabled: boolean
  retention_dry_run: boolean
  agy_enabled: boolean
  agy_install_dir: string
  agy_global_dir: string
  agy_default_skill: string
  agy_default_model: string | null
  agy_supported_models: string
  agy_templates_dir: string
  agy_sample_prompts_dir: string
  agy_default_wait_timeout: number
  agy_output_dir: string
  agy_auto_provision_skills: boolean
  agy_skills_auto_update: boolean
  agy_skills_update_sources: string
  notify_telegram_enabled: boolean
  notify_telegram_bot_token: string | null
  notify_telegram_chat_id: string | null
  [key: string]: string | boolean | number | null
}

export interface AgySkillInfo {
  name: string
  available: boolean
  installed: boolean
}

export interface AgyReportFile {
  name: string
  path: string
  size_bytes: number
  modified: string
}

export interface SocialSourceResolveResponse {
  platform: string
  identifier: string
  resolved_identifier: string
  display_name: string
  exists: boolean
}

export interface CLITool {
  name: string
  installed: boolean
  binary_path: string | null
  version: string | null
  install_instructions: string | null
  install_url: string | null
}

export interface PluginStatus {
  name: string
  display_name: string
  installed_version: string | null
  latest_version: string | null
  update_available: boolean
  auto_update_enabled: boolean
  binary_path: string | null
  last_checked: string | null
  last_updated: string | null
  update_message: string | null
}

export interface PluginUpdateResult {
  plugin: string
  action: string
  from_version: string | null
  to_version: string | null
  success: boolean
  message: string
  timestamp: string
}

export interface PluginUpdateLog {
  timestamp: string
  plugin: string
  action: string
  from_version: string | null
  to_version: string | null
  success: boolean
  message: string
}

export interface TwitterStatus {
  binary_found: boolean
  version: string | null
  authenticated: boolean
  last_check: string
  message: string
}

export interface RedditStatus {
  binary_found: boolean
  version: string | null
  authenticated: boolean
  last_check: string
  message: string
}

export interface StocktwitsStatus {
  api_reachable: boolean
  last_check: string
  rate_limit_remaining: string | null
  message: string
}

export interface PotProviderStatus {
  status: string
  running: boolean
  reachable: boolean
  bypass_mode: string
  url: string
  docker_available: boolean
  message: string
}

export interface SocialStatus {
  twitter: TwitterStatus
  reddit: RedditStatus
  stocktwits: StocktwitsStatus
}

export interface SocialAuthResponse {
  platform: string
  started: boolean
  message: string
}

export interface SocialTestResponse {
  platform: string
  success: boolean
  message: string
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------
export interface NotificationItem {
  id: string
  type: 'plugin_update' | 'job_completed' | 'job_failed' | 'notebooklm_auth'
  title: string
  message: string
  severity: 'info' | 'warning' | 'error'
  timestamp: string
  action_url: string | null
  action_label: string | null
}

export interface NotificationList {
  notifications: NotificationItem[]
  unread_count: number
}
