import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, Zap, Play, Clock, Filter, Loader2, X } from 'lucide-react'
import { api, type Preset, type SSEEvent } from '@/lib/api'
import { useSSE } from '@/hooks/useSSE'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { PresetForm } from '@/components/shared/PresetForm'
import { SingleVideoRun } from '@/components/shared/SingleVideoRun'
import { describeSchedule } from '@/lib/schedule'

const emptyPreset: Partial<Preset> = {
  name: '',
  preset_type: 'youtube',
  channel_list_id: '',
  channel_names: '',
  prompt_md: '',
  social_sources: null,
  outputs: 'pdf,markdown,notebooklm',
  notebooklm_kind: 'slide_deck',
  notebooklm_prompt_template: null,
  schedule: '',
  lookback_hours: 24,
  max_videos: 10,
  text_filter: '',
  date_range_days: null,
  playlist_mode: false,
  skip_processed: true,
  active: true,
  retention_enabled: true,
  file_retention_hours: 24,
  notebook_retention_hours: 24,
}

export default function Presets() {
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Preset | null>(null)
  const [form, setForm] = useState<Partial<Preset>>(emptyPreset)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const { latestEvent, events, isDone } = useSSE(activeJobId)

  const load = () => {
    api.listPresets()
      .then(setPresets)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(emptyPreset)
    setDialogOpen(true)
  }

  const openEdit = (p: Preset) => {
    setEditing(p)
    setForm(p)
    setDialogOpen(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      if (editing) {
        await api.updatePreset(editing.id, form)
      } else {
        await api.createPreset(form)
      }
      setDialogOpen(false)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleteId) return
    try {
      await api.deletePreset(deleteId)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const toggleActive = async (p: Preset) => {
    try {
      await api.updatePreset(p.id, { active: !p.active })
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const runPreset = async (p: Preset) => {
    setRunningId(p.id)
    try {
      const res = await api.startFetch(p.id)
      setActiveJobId(res.job_id)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunningId(null)
    }
  }

  // Auto-refresh when SSE completes
  useEffect(() => {
    if (activeJobId && isDone) {
      load()
      setTimeout(() => setActiveJobId(null), 3000)
    }
  }, [activeJobId, isDone])

  // Reason: when navigating back to the page, auto-subscribe to any
  // running job so the progress bar and live updates are visible.
  useEffect(() => {
    if (activeJobId) return
    api.listJobs(5, 'running').then((runningJobs) => {
      if (runningJobs.length > 0) {
        setActiveJobId(runningJobs[0].id)
      }
    }).catch(() => {})
  }, [])

  if (loading) {
    return <div className="animate-pulse py-20 text-center text-muted-foreground text-sm">Loading presets...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Presets</h1>
          <p className="text-sm text-muted-foreground">Manage your channel processing presets</p>
        </div>
        <Button onClick={openCreate} size="sm" className="gap-1.5">
          <Plus className="h-3.5 w-3.5" /> New Preset
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
          {error}
        </div>
      )}

      {/* SSE Progress Card */}
      {activeJobId && latestEvent && (
        <Card className="border-primary/30">
          <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              {latestEvent.status === 'running' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {latestEvent.status === 'completed' && <span className="text-emerald-500">&#10003;</span>}
              {latestEvent.status === 'failed' && <span className="text-destructive">&#10007;</span>}
              {latestEvent.message}
            </CardTitle>
            <div className="flex items-center gap-2">
              {latestEvent.progress !== null && (
                <span className="text-xs font-mono text-muted-foreground">{Math.round(latestEvent.progress)}%</span>
              )}
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setActiveJobId(null)}>
                <X className="h-3 w-3" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {latestEvent.progress !== null && latestEvent.progress < 100 && (
              <Progress value={latestEvent.progress} />
            )}
            {latestEvent.video_title && (
              <p className="text-xs text-muted-foreground">Processing: {latestEvent.video_title}</p>
            )}
            {events.length > 1 && (
              <div className="mt-2 max-h-32 overflow-y-auto space-y-1 rounded-md bg-muted/50 p-2">
                {events.slice(-8).map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="font-mono shrink-0">{e.step}</span>
                    <span className="truncate">{e.message}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Presets list - takes 2 columns */}
        <div className="lg:col-span-2 space-y-3">
          {presets.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center">
                <Zap className="mx-auto mb-2 h-6 w-6 text-muted-foreground/40" />
                <p className="text-xs text-muted-foreground">No presets yet. Create one to get started.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2.5">
              {presets.map((p) => (
                <Card key={p.id} className="hover:shadow-md transition-shadow">
                  <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <StatusBadge status={p.active ? 'active' : 'unknown'} />
                      <CardTitle className="text-sm truncate">{p.name}</CardTitle>
                    </div>
                    <div className="flex shrink-0 gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => runPreset(p)}
                        disabled={runningId === p.id}
                        title="Run now"
                      >
                        {runningId === p.id ? (
                          <span className="animate-pulse text-xs">...</span>
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(p)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleteId(p.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-1.5 pt-0 text-xs">
                    {p.preset_type === 'social' ? (
                      <>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="font-medium w-16 shrink-0">Type</span>
                          <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary text-[10px]">Social</span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="font-medium w-16 shrink-0">Sources</span>
                          <span className="truncate">
                            {(() => {
                              if (!p.social_sources) return '—'
                              try {
                                return JSON.parse(p.social_sources).map((s: {platform:string, identifier:string}) => `${s.platform}:${s.identifier}`).join(', ')
                              } catch {
                                return p.social_sources
                              }
                            })()}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="font-medium w-16 shrink-0">Outputs</span>
                          <span>{p.outputs}</span>
                        </div>
                        <div className="flex items-center gap-4 text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {describeSchedule(p.schedule)}
                          </span>
                          {p.max_videos && <span>Max: {p.max_videos} posts</span>}
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="font-medium w-16 shrink-0">Channels</span>
                          <span className="truncate">{p.channel_names || p.channel_list_id || '—'}</span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <span className="font-medium w-16 shrink-0">Outputs</span>
                          <span>{p.outputs}</span>
                        </div>
                        <div className="flex items-center gap-4 text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {describeSchedule(p.schedule)}
                          </span>
                          <span>Lookback: {p.lookback_hours ?? 24}h</span>
                          {p.max_videos && <span>Max: {p.max_videos}</span>}
                          {p.playlist_mode && <span className="text-primary">Playlist</span>}
                        </div>
                        <div className="flex items-center gap-4 text-muted-foreground">
                          {p.retention_enabled === false ? (
                            <span>Retention: disabled</span>
                          ) : (
                            <>
                              <span>Files: {p.file_retention_hours ?? 24}h</span>
                              <span>Notebooks: {p.notebook_retention_hours ?? 24}h</span>
                            </>
                          )}
                        </div>
                      </>
                    )}
                    {p.text_filter && (
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <Filter className="h-3 w-3" />
                        <span>Filter: "{p.text_filter}"</span>
                      </div>
                    )}
                    <div className="flex items-center justify-between pt-1.5">
                      <span className="text-muted-foreground">
                        {p.active ? 'Active' : 'Inactive'}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        onClick={() => toggleActive(p)}
                      >
                        {p.active ? 'Deactivate' : 'Activate'}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Single Video Run - takes 1 column */}
        <div className="lg:col-span-1">
          <SingleVideoRun />
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-base">{editing ? 'Edit Preset' : 'Create Preset'}</DialogTitle>
          </DialogHeader>
          <PresetForm preset={form} onChange={setForm} existingPresets={presets} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving || !form.name} size="sm">
              {saving ? 'Saving...' : editing ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(v) => !v && setDeleteId(null)}
        title="Delete Preset"
        description="Are you sure you want to delete this preset? This action cannot be undone."
        confirmText="Delete"
        destructive
        onConfirm={confirmDelete}
      />
    </div>
  )
}
