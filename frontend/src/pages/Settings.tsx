import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Save, Loader2, CheckCircle2, Trash2, Eye, Users } from 'lucide-react'
import { api } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { PluginUpdates } from '@/components/PluginUpdates'
import { BypassChainEditor } from '@/components/BypassChainEditor'

interface SettingsState {
  [key: string]: string | boolean | number | null
}

const sections = [
  { id: 'general', label: 'General', fields: ['env', 'secret_key', 'db_path', 'api_host', 'api_port', 'media_root', 'output_root', 'model_root', 'youtube_api_key'] },
  { id: 'ytdlp', label: 'YouTube / yt-dlp', fields: ['yt_dlp_path', 'yt_dlp_bypass_chain', 'yt_dlp_bypass_mode', 'yt_dlp_cookiejar_path', 'yt_dlp_cookies_browser', 'yt_dlp_cookies_browser_profile', 'yt_dlp_user_agent', 'yt_dlp_extra_args', 'yt_dlp_update_strategy', 'video_resolution', 'video_format_fallback'] },
  { id: 'transcript', label: 'Transcript', fields: ['transcript_languages', 'whisper_model'] },
  { id: 'frames', label: 'Frames', fields: ['frame_max_count', 'frame_min_interval_s', 'frame_hash_algo', 'frame_hash_threshold', 'frame_long_edge', 'frame_jpeg_quality', 'frame_dedup_mode', 'frame_dedup_window', 'frame_dedup_pipeline', 'frame_motion_threshold', 'frame_ssim_threshold', 'frame_hist_threshold', 'frame_dedup_ssim_window'] },
  { id: 'outputs', label: 'Outputs', fields: ['output_formats', 'presets_path'] },
  { id: 'retention', label: 'Retention', fields: ['retention_media_hours', 'retention_reports_hours', 'retention_cleanup_enabled', 'retention_dry_run'] },
  { id: 'notebooklm', label: 'NotebookLM', fields: ['notebooklm_enabled', 'notebooklm_mode', 'notebooklm_storage_state_path', 'notebooklm_profile', 'notebooklm_default_retention_hours', 'notebooklm_auto_upload', 'notebooklm_default_content_types', 'notebooklm_default_prompt', 'notebooklm_upload_mode', 'notebooklm_max_bundle_size_mb', 'notebooklm_max_bundle_files', 'notebooklm_upload_text_only'] },
  { id: 'antigravity', label: 'Antigravity', fields: ['agy_enabled', 'agy_install_dir', 'agy_global_dir', 'agy_default_skill', 'agy_default_model', 'agy_supported_models', 'agy_templates_dir', 'agy_sample_prompts_dir', 'agy_default_wait_timeout', 'agy_output_dir', 'agy_auto_provision_skills', 'agy_skills_auto_update', 'agy_skills_update_sources'] },
  { id: 'notifications', label: 'Notifications', fields: ['notify_telegram_enabled', 'notify_telegram_bot_token', 'notify_telegram_chat_id'] },
  { id: 'scheduler', label: 'Scheduler', fields: ['scheduler_jobstore', 'scheduler_jobstore_path'] },
  { id: 'tools', label: 'Runtime Tools', fields: ['tool_update_enabled', 'tool_update_check_on_startup', 'tool_update_cadence', 'tool_auto_update_yt_dlp', 'tool_auto_update_ffmpeg', 'tool_auto_update_whisper'] },
  { id: 'social', label: 'Social', fields: ['social_default_lookback_hours', 'social_default_max_posts', 'social_reddit_enabled', 'social_stocktwits_enabled', 'social_x_enabled', 'twitter_cli_binary_path', 'rdt_cli_binary_path', 'reddit_cookie', 'curl_cffi_impersonate', 'stocktwits_api_base'] },
]

const boolFields = new Set([
  'video_format_fallback', 'retention_cleanup_enabled', 'retention_dry_run',
  'notebooklm_enabled', 'notebooklm_auto_upload', 'notebooklm_upload_text_only',
  'agy_enabled', 'notify_telegram_enabled',
  'tool_update_enabled', 'tool_update_check_on_startup', 'tool_auto_update_yt_dlp',
  'tool_auto_update_ffmpeg', 'tool_auto_update_whisper',
  'social_reddit_enabled', 'social_stocktwits_enabled', 'social_x_enabled',
])

const selectFields: Record<string, string[]> = {
  yt_dlp_bypass_mode: ['default', 'web_embedded', 'po_token', 'cookie', 'cookies_from_browser', 'hls'],
  yt_dlp_cookies_browser: ['chrome', 'edge', 'firefox', 'brave', 'chromium', 'opera', 'vivaldi'],
  frame_hash_algo: ['phash', 'dhash', 'ahash'],
  frame_dedup_mode: ['global', 'window'],
  notebooklm_mode: ['storage_state', 'cookies'],
  notebooklm_upload_mode: ['smart', 'individual', 'combined'],
  tool_update_cadence: ['daily', 'weekly', 'manual'],
  video_resolution: ['best', '1080', '720', '480'],
}

export default function Settings() {
  const [settings, setSettings] = useState<SettingsState>({})
  const [original, setOriginal] = useState<SettingsState>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [cleanupRunning, setCleanupRunning] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<Record<string, number> | null>(null)
  const [cleanupError, setCleanupError] = useState<string | null>(null)

  useEffect(() => {
    api.getSettings()
      .then((data) => {
        const flat = data as unknown as SettingsState
        setSettings(flat)
        setOriginal(flat)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const setField = (key: string, value: string | boolean | number | null) => {
    setSettings((s) => ({ ...s, [key]: value }))
    setSuccess(false)
  }

  const save = async () => {
    const changes: Record<string, unknown> = {}
    for (const key of Object.keys(settings)) {
      if (settings[key] !== original[key]) {
        changes[key] = settings[key]
      }
    }
    if (Object.keys(changes).length === 0) return

    setSaving(true)
    try {
      await api.updateSettings(changes)
      setOriginal({ ...settings })
      setSuccess(true)
      setError(null)
      setTimeout(() => setSuccess(false), 3000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = JSON.stringify(settings) !== JSON.stringify(original)

  const runCleanup = async (dryRun: boolean) => {
    setCleanupRunning(true)
    setCleanupError(null)
    setCleanupResult(null)
    try {
      const res = await api.runCleanup(dryRun)
      setCleanupResult(res.counts)
    } catch (e) {
      setCleanupError((e as Error).message)
    } finally {
      setCleanupRunning(false)
    }
  }

  if (loading) return <div className="py-20 text-center text-xs text-muted-foreground animate-pulse">Loading settings...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">Configure StreamDoc (writes to .env file)</p>
        </div>
        <div className="flex items-center gap-2">
          {success && (
            <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" /> Saved!
            </span>
          )}
          <Button onClick={save} disabled={saving || !hasChanges} size="sm" className="gap-1.5">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Save Changes
          </Button>
        </div>
      </div>

      {error && <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">{error}</div>}

      <PluginUpdates />

      <div className="grid gap-3 md:grid-cols-2">
        {sections.map((section) => (
          <Card key={section.id}>
            <CardHeader className="py-3">
              <CardTitle className="text-sm">{section.label}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5 pt-0">
              {section.fields.map((field) => {
                const value = settings[field]
                const isBool = boolFields.has(field)
                const selectOpts = selectFields[field]

                // Reason: yt_dlp_bypass_chain gets a dedicated ordered-list
                // editor with per-mode tooltips, not a plain text input.
                if (field === 'yt_dlp_bypass_chain') {
                  return (
                    <div key={field} className="grid gap-1.5">
                      <Label className="text-xs">
                        Bypass Chain
                      </Label>
                      <BypassChainEditor
                        value={String(value || '')}
                        onChange={(v) => setField(field, v)}
                      />
                    </div>
                  )
                }

                return (
                  <div key={field} className="grid gap-1">
                    <Label htmlFor={field} className="text-xs">
                      {field.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                    </Label>
                    {isBool ? (
                      <div className="flex items-center gap-2">
                        <Switch
                          checked={value === true}
                          onCheckedChange={(v) => setField(field, v)}
                        />
                        <span className="text-xs text-muted-foreground">{value ? 'Enabled' : 'Disabled'}</span>
                      </div>
                    ) : selectOpts ? (
                      <Select value={String(value || '')} onValueChange={(v) => setField(field, v)}>
                        <SelectTrigger id={field} className="h-8"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {selectOpts.map((opt) => <SelectItem key={opt} value={opt}>{opt}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        id={field}
                        value={value === null ? '' : String(value)}
                        onChange={(e) => setField(field, e.target.value)}
                        type={typeof value === 'number' ? 'number' : 'text'}
                        className="h-8"
                      />
                    )}
                  </div>
                )
              })}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Social Settings shortcut */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Users className="h-4 w-4" />
            Social Platform Auth
          </CardTitle>
          <CardDescription className="text-xs">
            Configure Reddit, X (Twitter), and Stocktwits credentials, run auth flows, and test connectivity.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" size="sm" asChild>
            <Link to="/settings/social">Open Social Settings</Link>
          </Button>
        </CardContent>
      </Card>

      {/* Manual Cleanup Controls */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm">Manual Cleanup</CardTitle>
          <CardDescription className="text-xs">
            Run retention cleanup to delete old media files, reports, and artifacts based on retention policy settings.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => runCleanup(true)}
              disabled={cleanupRunning}
            >
              {cleanupRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Eye className="h-3.5 w-3.5 mr-1.5" />}
              Dry Run
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => runCleanup(false)}
              disabled={cleanupRunning}
            >
              {cleanupRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Trash2 className="h-3.5 w-3.5 mr-1.5" />}
              Run Cleanup
            </Button>
          </div>
          {cleanupError && (
            <p className="text-xs text-destructive">{cleanupError}</p>
          )}
          {cleanupResult && (
            <div className="rounded-md border border-border bg-muted/50 p-3">
              <p className="text-xs font-medium mb-1.5">Cleanup Results:</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {Object.entries(cleanupResult).map(([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-muted-foreground">{key.replace(/_/g, ' ')}:</span>
                    <span className="font-medium">{val}</span>
                  </div>
                ))}
                {Object.keys(cleanupResult).length === 0 && (
                  <span className="text-muted-foreground">Nothing to clean up.</span>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
