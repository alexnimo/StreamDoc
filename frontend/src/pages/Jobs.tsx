import { useEffect, useState, useCallback } from 'react'
import { Play, RotateCw, Send, Loader2, X, Ban, ChevronDown, ChevronRight, FileText, FileImage, Clock, Film, Hash, ExternalLink, AlertCircle, Download, Mic, Image as ImageIcon, FileOutput, RefreshCw, CheckCircle2, Clock3, XCircle, Rocket } from 'lucide-react'
import { api, type Job, type Preset, type SSEEvent, type GenerationRecord } from '@/lib/api'
import { useSSE } from '@/hooks/useSSE'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatDate, timeAgo } from '@/lib/utils'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

/** Step icon mapping for SSE events */
const STEP_ICONS: Record<string, typeof Download> = {
  download: Download,
  transcribe: Mic,
  frames: ImageIcon,
  output: FileOutput,
  process: Film,
  init: Clock,
  channels: Film,
  list_videos: Film,
  report: FileText,
  upload: Send,
  complete: FileText,
}

/** Live progress panel for a single running job. Subscribes to SSE events. */
function RunningJobProgress({ jobId }: { jobId: string }) {
  const { latestEvent, events } = useSSE(jobId)
  if (!latestEvent && events.length === 0) {
    return <p className="text-xs text-muted-foreground animate-pulse">Connecting to live progress...</p>
  }
  return (
    <div className="space-y-2">
      {latestEvent && (
        <div className="flex items-center gap-2 text-xs">
          {latestEvent.status === 'running' && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
          {latestEvent.status === 'completed' && <span className="text-emerald-500">&#10003;</span>}
          {latestEvent.status === 'failed' && <span className="text-destructive">&#10007;</span>}
          <span className="font-medium">{latestEvent.message}</span>
          {latestEvent.progress !== null && (
            <span className="text-muted-foreground ml-auto">{Math.round(latestEvent.progress)}%</span>
          )}
        </div>
      )}
      {latestEvent && latestEvent.progress !== null && latestEvent.progress < 100 && (
        <Progress value={latestEvent.progress} className="h-1.5" />
      )}
      {events.length > 1 && (
        <div className="mt-2 max-h-40 overflow-y-auto space-y-1 rounded-md bg-muted/50 p-2">
          {events.slice(-12).map((e, i) => {
            const Icon = STEP_ICONS[e.step] || Film
            return (
              <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Icon className="h-3 w-3 shrink-0" />
                <span className="font-mono">{e.step}</span>
                <span className="truncate">{e.message}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** Status icon for a generation record */
function GenStatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
  if (status === 'failed') return <XCircle className="h-3.5 w-3.5 text-destructive" />
  if (status === 'pending' || status === 'in_progress') return <Clock3 className="h-3.5 w-3.5 text-amber-500 animate-pulse" />
  return <AlertCircle className="h-3.5 w-3.5 text-muted-foreground" />
}

/** Shows NotebookLM generation statuses for a specific job. */
function GenerationStatusPanel({ jobId }: { jobId: string }) {
  const [generations, setGenerations] = useState<GenerationRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [polling, setPolling] = useState(false)

  const load = useCallback(() => {
    api.listGenerations().then((all) => {
      setGenerations(all.filter((g) => g.job_id === jobId))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [jobId])

  useEffect(() => {
    load()
    // Reason: poll every 30s to match backend poller interval
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [load])

  const pollNow = async () => {
    setPolling(true)
    try {
      await api.pollGenerations()
      await load()
    } catch {
      // ignore
    } finally {
      setPolling(false)
    }
  }

  if (loading) return null
  if (generations.length === 0) return null

  const hasPending = generations.some((g) => g.status === 'pending' || g.status === 'in_progress')

  return (
    <div>
      <h4 className="text-xs font-semibold mb-1.5 flex items-center gap-1.5">
        <RefreshCw className="h-3 w-3 text-primary" />
        NotebookLM Generations
        {hasPending && (
          <Button variant="ghost" size="sm" className="h-5 px-2 text-xs gap-1" onClick={pollNow} disabled={polling}>
            {polling ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            Check now
          </Button>
        )}
      </h4>
      <div className="space-y-1">
        {generations.map((g) => (
          <div key={g.id} className="flex items-center gap-2 text-xs rounded-md bg-background/60 px-2 py-1.5">
            <GenStatusIcon status={g.status} />
            <span className="font-medium capitalize">{g.content_type.replace('_', ' ')}</span>
            <span className={
              g.status === 'completed' ? 'text-emerald-600 dark:text-emerald-400' :
              g.status === 'failed' ? 'text-destructive' :
              'text-amber-500'
            }>
              {g.status}
            </span>
            {g.local_path && (
              <a
                href={api.downloadGeneration(g.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline inline-flex items-center gap-1"
                onClick={(e) => e.stopPropagation()}
              >
                <Download className="h-3 w-3" /> Download
              </a>
            )}
            {g.error && (
              <span className="text-destructive truncate ml-auto" title={g.error}>{g.error}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [fetchPreset, setFetchPreset] = useState<string>('')
  const [resendJob, setResendJob] = useState<Job | null>(null)
  const [resendDest, setResendDest] = useState('notebooklm')
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set())
  const { latestEvent, events, isDone } = useSSE(activeJobId)

  const toggleExpand = (jobId: string) => {
    setExpandedJobs((prev) => {
      const next = new Set(prev)
      if (next.has(jobId)) {
        next.delete(jobId)
      } else {
        next.add(jobId)
      }
      return next
    })
  }

  const fmtDuration = (seconds: number | null | undefined) => {
    if (!seconds) return '—'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }

  const load = useCallback(() => {
    api.listJobs(50, statusFilter === 'all' ? undefined : statusFilter)
      .then(setJobs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [statusFilter])

  useEffect(() => {
    api.listPresets().then(setPresets).catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  // Auto-refresh when there are running jobs
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === 'running')
    if (!hasRunning) return
    const interval = setInterval(() => load(), 3000)
    return () => clearInterval(interval)
  }, [jobs, load])

  // Auto-expand running jobs so live progress is visible
  useEffect(() => {
    const runningIds = jobs.filter((j) => j.status === 'running').map((j) => j.id)
    if (runningIds.length > 0) {
      setExpandedJobs((prev) => {
        const next = new Set(prev)
        let changed = false
        for (const id of runningIds) {
          if (!next.has(id)) {
            next.add(id)
            changed = true
          }
        }
        return changed ? next : prev
      })
    }
  }, [jobs])

  // Auto-refresh when SSE is active
  useEffect(() => {
    if (activeJobId && isDone) {
      load()
      setTimeout(() => setActiveJobId(null), 2000)
    }
  }, [activeJobId, isDone, load])

  // Reason: when navigating back to the page, auto-subscribe to any
  // running job so the progress bar and live updates are visible.
  // Without this, the SSE connection is lost and the user only sees
  // "connected to stream" with no progress details.
  useEffect(() => {
    if (activeJobId) return // already tracking a job
    const running = jobs.find((j) => j.status === 'running')
    if (running) {
      setActiveJobId(running.id)
    }
  }, [jobs, activeJobId])

  // Reason: auto-refresh jobs list every 30s when there are jobs with
  // pending NotebookLM generations. The background poller updates job
  // destinations asynchronously, so the frontend needs to re-fetch
  // to show the updated status (pending → completed).
  useEffect(() => {
    const hasPending = jobs.some((j) => {
      const dests = j.destinations || {}
      return Object.values(dests).some((v) => v === 'pending' || v === 'in_progress')
    })
    if (!hasPending) return
    const interval = setInterval(() => load(), 30000)
    return () => clearInterval(interval)
  }, [jobs, load])

  const startFetch = async () => {
    if (!fetchPreset) return
    try {
      const res = await api.startFetch(fetchPreset)
      setActiveJobId(res.job_id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const retryJob = async (id: string) => {
    try {
      await api.retryJob(id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const cancelJob = async (id: string) => {
    try {
      await api.cancelJob(id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const doResend = async () => {
    if (!resendJob) return
    try {
      await api.resendJob(resendJob.id, resendDest)
      setResendJob(null)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-sm text-muted-foreground">Monitor and manage fetch runs</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={fetchPreset} onValueChange={setFetchPreset}>
            <SelectTrigger className="w-40"><SelectValue placeholder="Select preset" /></SelectTrigger>
            <SelectContent>
              {presets.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button onClick={startFetch} disabled={!fetchPreset} size="sm" className="gap-1.5">
            <Play className="h-3.5 w-3.5" /> Run Fetch
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center justify-between rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
          {error}
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setError(null)}><X className="h-3 w-3" /></Button>
        </div>
      )}

      {/* SSE Progress Card */}
      {activeJobId && latestEvent && (
        <Card className="border-primary/30">
          <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              {latestEvent.status === 'running' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {latestEvent.status === 'completed' && <span className="text-emerald-500">✓</span>}
              {latestEvent.status === 'failed' && <span className="text-destructive">✗</span>}
              {latestEvent.message}
            </CardTitle>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setActiveJobId(null)}>
              <X className="h-3 w-3" />
            </Button>
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
                  <div key={i} className="text-xs text-muted-foreground">
                    <span className="font-mono">{e.step}</span>: {e.message}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Filter */}
      <div className="flex gap-2">
        {['all', 'running', 'completed', 'failed', 'partial'].map((s) => (
          <Button
            key={s}
            variant={statusFilter === s ? 'default' : 'outline'}
            size="sm"
            onClick={() => { setStatusFilter(s); setLoading(true) }}
            className="capitalize"
          >
            {s}
          </Button>
        ))}
      </div>

      {/* Jobs Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="py-12 text-center text-xs text-muted-foreground animate-pulse">Loading jobs...</div>
          ) : jobs.length === 0 ? (
            <div className="py-12 text-center text-xs text-muted-foreground">No jobs found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Job ID</th>
                    <th className="px-4 py-2.5 font-medium">Preset</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Created</th>
                    <th className="px-4 py-2.5 font-medium">Artifacts</th>
                    <th className="px-4 py-2.5 font-medium">Destinations</th>
                    <th className="px-4 py-2.5 font-medium">Errors</th>
                    <th className="px-4 py-2.5 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => {
                    const isExpanded = expandedJobs.has(job.id)
                    const details = job.details || {}
                    const videos = details.videos || []
                    const stats = details.stats
                    const artifacts = details.artifacts || []
                    const integrations = details.integrations || {}
                    const isRunning = job.status === 'running'
                    const hasDetails = isRunning || videos.length > 0 || artifacts.length > 0 || Object.keys(integrations).length > 0
                    return (
                      <>
                        <tr key={job.id} className="border-b border-border last:border-0 hover:bg-accent/30 cursor-pointer" onClick={() => hasDetails && toggleExpand(job.id)}>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-1.5">
                              {hasDetails && (
                                isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                              )}
                              <span className="font-mono text-xs">{job.id}</span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5 font-medium">{job.preset_name}</td>
                          <td className="px-4 py-2.5"><StatusBadge status={job.status} /></td>
                          <td className="px-4 py-2.5 text-muted-foreground" title={formatDate(job.created_at)}>{timeAgo(job.created_at)}</td>
                          <td className="px-4 py-2.5">{job.artifact_count}</td>
                          <td className="px-4 py-2.5 text-xs">
                            {Object.keys(job.destinations).length > 0 ? (
                              <div className="space-y-0.5">
                                {Object.entries(job.destinations).filter(([k]) => k === 'notebooklm').map(([dest, result]) => (
                                  <span key={dest} className={result.startsWith('success') ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'}>
                                    {dest}: {result.startsWith('success') ? '✓' : '✗'}
                                  </span>
                                ))}
                                {job.destinations['notebooklm_url'] && (
                                  <a
                                    href={job.destinations['notebooklm_url']}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block text-primary hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    Open notebook ↗
                                  </a>
                                )}
                                {job.destinations['notebooklm_errors'] && (
                                  <span className="block text-destructive" title={Array.isArray(job.destinations['notebooklm_errors']) ? job.destinations['notebooklm_errors'].join('; ') : String(job.destinations['notebooklm_errors'])}>
                                    errors: {Array.isArray(job.destinations['notebooklm_errors']) ? job.destinations['notebooklm_errors'].length : 1}
                                  </span>
                                )}
                                {Object.entries(job.destinations)
                                  .filter(([k]) => k.startsWith('notebooklm_') && k !== 'notebooklm_url' && k !== 'notebooklm_errors')
                                  .map(([key, val]) => {
                                    if (val === 'pending') return <span key={key} className="block text-amber-500">{key.replace('notebooklm_', '')}: pending…</span>
                                    if (val.startsWith('error')) {
                                      // Reason: show the actual error message (e.g.
                                      // "Daily limit reached") as a tooltip so the
                                      // user knows why the generation failed.
                                      const errMsg = val.replace(/^error:\s*/, '')
                                      const isDailyLimit = errMsg.toLowerCase().includes('daily limit')
                                      return (
                                        <span
                                          key={key}
                                          className={`block ${isDailyLimit ? 'text-amber-600 dark:text-amber-400' : 'text-destructive'}`}
                                          title={errMsg}
                                        >
                                          {key.replace('notebooklm_', '')}: {isDailyLimit ? '⚠ daily limit' : '✗'}
                                        </span>
                                      )
                                    }
                                    // Reason: val is a file path — show ✓ with
                                    // a download link so the user can get the
                                    // slide deck PDF directly from the compact
                                    // view without expanding the job.
                                    const ct = key.replace('notebooklm_', '')
                                    return (
                                      <a
                                        key={key}
                                        href={api.downloadJobArtifact(job.id, ct)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="block text-emerald-600 dark:text-emerald-400 hover:underline"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        {ct}: ✓ Download
                                      </a>
                                    )
                                  })}
                                {job.destinations['agy_herenow_url'] && (
                                  <a
                                    href={job.destinations['agy_herenow_url']}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block text-primary hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    Open on here.now ↗
                                  </a>
                                )}
                                {job.destinations['agy_artifact_path'] && (
                                  <a
                                    href={job.destinations['agy_artifact_path']}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block text-emerald-600 dark:text-emerald-400 hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    Antigravity: ✓ Download
                                  </a>
                                )}
                                {job.destinations['agy_errors'] && (
                                  <span className="block text-destructive" title={Array.isArray(job.destinations['agy_errors']) ? job.destinations['agy_errors'].join('; ') : String(job.destinations['agy_errors'])}>
                                    agy errors: {Array.isArray(job.destinations['agy_errors']) ? job.destinations['agy_errors'].length : 1}
                                  </span>
                                )}
                              </div>
                            ) : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-xs text-destructive max-w-[200px] truncate" title={job.errors.join('; ')}>
                            {job.errors.length > 0 ? job.errors.join('; ') : '—'}
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                              {job.status === 'running' && (
                                <Button variant="ghost" size="icon" className="h-6 w-6" title="Cancel" onClick={() => cancelJob(job.id)}>
                                  <Ban className="h-3 w-3" />
                                </Button>
                              )}
                              {(job.status === 'failed' || job.status === 'partial') && (
                                <Button variant="ghost" size="icon" className="h-6 w-6" title="Retry" onClick={() => retryJob(job.id)}>
                                  <RotateCw className="h-3 w-3" />
                                </Button>
                              )}
                              <Button variant="ghost" size="icon" className="h-6 w-6" title="Resend" onClick={() => setResendJob(job)}>
                                <Send className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && hasDetails && (
                          <tr className="border-b border-border bg-muted/30">
                            <td colSpan={8} className="px-4 py-3">
                              <div className="space-y-4">
                                {/* Live progress for running jobs */}
                                {isRunning && (
                                  <div>
                                    <h4 className="text-xs font-semibold mb-1.5 flex items-center gap-1.5">
                                      <Loader2 className="h-3 w-3 animate-spin text-primary" />
                                      Live Progress
                                    </h4>
                                    <RunningJobProgress jobId={job.id} />
                                  </div>
                                )}

                                {/* Stats */}
                                {stats && (
                                  <div className="flex flex-wrap gap-4">
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                      <Film className="h-3.5 w-3.5" />
                                      <span>{stats.total_videos} video{stats.total_videos !== 1 ? 's' : ''}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                      <Clock className="h-3.5 w-3.5" />
                                      <span>Total: {fmtDuration(stats.total_duration_seconds)}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                      <FileImage className="h-3.5 w-3.5" />
                                      <span>{stats.total_frames} frames</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                      <Hash className="h-3.5 w-3.5" />
                                      <span>{stats.total_transcript_words?.toLocaleString()} words</span>
                                    </div>
                                  </div>
                                )}

                                {/* Videos */}
                                {videos.length > 0 && (
                                  <div>
                                    <h4 className="text-xs font-semibold mb-1.5">Processed Videos</h4>
                                    <div className="space-y-1">
                                      {videos.map((v) => (
                                        <div key={v.video_id} className="flex items-center justify-between text-xs rounded-md bg-background/60 px-2 py-1.5">
                                          <div className="flex items-center gap-2 min-w-0">
                                            <span className="truncate font-medium" title={v.title}>{v.title}</span>
                                            {v.channel_title && <span className="text-muted-foreground truncate">from {v.channel_title}</span>}
                                          </div>
                                          <div className="flex items-center gap-3 text-muted-foreground shrink-0">
                                            <span>{fmtDuration(v.duration_seconds)}</span>
                                            <span>{v.frame_count} frames</span>
                                            <span>{v.transcript_word_count} words</span>
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* Artifacts */}
                                {artifacts.length > 0 && (
                                  <div>
                                    <h4 className="text-xs font-semibold mb-1.5">Artifacts</h4>
                                    <div className="flex flex-wrap gap-2">
                                      {artifacts.map((a) => (
                                        <div key={a.video_id} className="flex items-center gap-2">
                                          {a.md_path && (
                                            <TooltipProvider>
                                              <Tooltip>
                                                <TooltipTrigger asChild>
                                                  <a
                                                    href={`/api/reports/download/${a.video_id}?format=md`}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className={`inline-flex items-center gap-1 text-xs rounded-md px-2 py-1 ${a.status === 'ready' ? 'bg-primary/10 text-primary hover:bg-primary/20' : 'bg-muted text-muted-foreground'}`}
                                                    onClick={(e) => e.stopPropagation()}
                                                  >
                                                    <FileText className="h-3 w-3" />
                                                    {a.title || a.video_id}.md
                                                  </a>
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                  <p className="text-xs">{a.status === 'ready' ? 'Open Markdown' : `Status: ${a.status}`}</p>
                                                </TooltipContent>
                                              </Tooltip>
                                            </TooltipProvider>
                                          )}
                                          {a.pdf_path && (
                                            <TooltipProvider>
                                              <Tooltip>
                                                <TooltipTrigger asChild>
                                                  <a
                                                    href={`/api/reports/download/${a.video_id}?format=pdf`}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className={`inline-flex items-center gap-1 text-xs rounded-md px-2 py-1 ${a.status === 'ready' ? 'bg-primary/10 text-primary hover:bg-primary/20' : 'bg-muted text-muted-foreground'}`}
                                                    onClick={(e) => e.stopPropagation()}
                                                  >
                                                    <FileImage className="h-3 w-3" />
                                                    {a.title || a.video_id}.pdf
                                                  </a>
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                  <p className="text-xs">{a.status === 'ready' ? 'Open PDF' : `Status: ${a.status}`}</p>
                                                </TooltipContent>
                                              </Tooltip>
                                            </TooltipProvider>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* Integrations */}
                                {(Object.keys(integrations).length > 0 || Object.keys(job.destinations).length > 0) && (
                                  <div>
                                    <h4 className="text-xs font-semibold mb-1.5">Integrations</h4>
                                    <div className="space-y-1">
                                      {/* Reason: merge integrations from details with
                                          destinations from the job record so the
                                          expanded view shows the notebook URL and
                                          slide deck download even for jobs where
                                          details.integrations wasn't populated. */}
                                      {(() => {
                                        const allDests = { ...job.destinations, ...integrations }
                                        return Object.entries(allDests).map(([key, value]) => {
                                        if (key === 'notebooklm' && typeof value === 'string' && value.startsWith('success')) {
                                          const url = allDests['notebooklm_url'] as string | undefined
                                          return (
                                            <div key={key} className="flex items-center gap-2 text-xs">
                                              <span className="text-emerald-600 dark:text-emerald-400">NotebookLM:</span>
                                              {url ? (
                                                <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                                                  Open notebook <ExternalLink className="h-3 w-3" />
                                                </a>
                                              ) : (
                                                <span className="text-muted-foreground">Uploaded successfully</span>
                                              )}
                                            </div>
                                          )
                                        }
                                        if (key === 'notebooklm_errors') {
                                          // Reason: notebooklm_errors is a list of strings
                                          // (accumulated from batch_generate), not a single
                                          // string like the other notebooklm_* keys — render
                                          // it as a stacked list of error messages.
                                          const errs = Array.isArray(value) ? value : [value]
                                          return (
                                            <div key={key} className="space-y-1">
                                              {errs.map((e, i) => (
                                                <div key={i} className="flex items-center gap-2 text-xs text-destructive">
                                                  <AlertCircle className="h-3 w-3" />
                                                  <span>{String(e)}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )
                                        }
                                        if (key.startsWith('notebooklm_') && key !== 'notebooklm_url') {
                                          const contentType = key.replace('notebooklm_', '')
                                          if (value === 'pending') {
                                            return (
                                              <div key={key} className="flex items-center gap-2 text-xs">
                                                <span className="text-amber-500">{contentType}:</span>
                                                <span className="text-muted-foreground">generating on NotebookLM...</span>
                                              </div>
                                            )
                                          }
                                          if (value.startsWith('error')) {
                                            const errMsg = value.replace(/^error:\s*/, '')
                                            const isDailyLimit = errMsg.toLowerCase().includes('daily limit')
                                            return (
                                              <div key={key} className={`flex items-center gap-2 text-xs ${isDailyLimit ? 'text-amber-600 dark:text-amber-400' : 'text-destructive'}`}>
                                                <AlertCircle className="h-3 w-3" />
                                                <span>{contentType}: {errMsg}</span>
                                              </div>
                                            )
                                          }
                                          // Reason: value is a file path to the generated PDF
                                          return (
                                            <div key={key} className="flex items-center gap-2 text-xs">
                                              <span className="text-emerald-600 dark:text-emerald-400">{contentType}:</span>
                                              <a
                                                href={api.downloadJobArtifact(job.id, contentType)}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-primary hover:underline"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                <Download className="h-3 w-3" />
                                                Download
                                              </a>
                                            </div>
                                          )
                                        }
                                        if (key === 'notebooklm' && typeof value === 'string' && !value.startsWith('success')) {
                                          return (
                                            <div key={key} className="flex items-center gap-2 text-xs text-destructive">
                                              <AlertCircle className="h-3 w-3" />
                                              <span>NotebookLM: {value}</span>
                                            </div>
                                          )
                                        }
                                        // Antigravity destinations
                                        if (key === 'agy_herenow_url') {
                                          return (
                                            <div key={key} className="flex items-center gap-2 text-xs">
                                              <span className="text-emerald-600 dark:text-emerald-400">Antigravity:</span>
                                              <a
                                                href={value}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-primary hover:underline"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                Open on here.now <ExternalLink className="h-3 w-3" />
                                              </a>
                                            </div>
                                          )
                                        }
                                        if (key === 'agy_artifact_path') {
                                          return (
                                            <div key={key} className="flex items-center gap-2 text-xs">
                                              <span className="text-emerald-600 dark:text-emerald-400">Antigravity artifact:</span>
                                              <a
                                                href={value}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-primary hover:underline"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                <Download className="h-3 w-3" />
                                                Download
                                              </a>
                                            </div>
                                          )
                                        }
                                        if (key === 'agy_errors') {
                                          const errs = Array.isArray(value) ? value : [value]
                                          return (
                                            <div key={key} className="space-y-1">
                                              {errs.map((e, i) => (
                                                <div key={i} className="flex items-center gap-2 text-xs text-destructive">
                                                  <AlertCircle className="h-3 w-3" />
                                                  <span>Antigravity: {String(e)}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )
                                        }
                                        return null
                                      })
                                      })()}
                                    </div>
                                  </div>
                                )}

                                {/* NotebookLM Generation Status (async tracking) */}
                                <GenerationStatusPanel jobId={job.id} />
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Resend Dialog */}
      <Dialog open={resendJob !== null} onOpenChange={(v) => !v && setResendJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-base">Resend Job Reports</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-1.5">
              <Label htmlFor="dest" className="text-xs">Destination</Label>
              <Input id="dest" value={resendDest} onChange={(e) => setResendDest(e.target.value)} placeholder="notebooklm" />
            </div>
            <p className="text-xs text-muted-foreground">
              This will resend the job's report files to the specified destination.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResendJob(null)} size="sm">Cancel</Button>
            <Button onClick={doResend} size="sm">Resend</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
