import { useState } from 'react'
import { Play, Loader2, Youtube, X } from 'lucide-react'
import { api, type SingleVideoFetchResponse } from '@/lib/api'
import { useSSE } from '@/hooks/useSSE'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'

export function SingleVideoRun() {
  const [url, setUrl] = useState('')
  const [promptMd, setPromptMd] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SingleVideoFetchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const { latestEvent, events, isDone } = useSSE(activeJobId)

  const run = async () => {
    if (!url.trim()) return
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.fetchSingleVideo({
        url: url.trim(),
        prompt_md: promptMd,
        outputs: 'pdf,markdown',
      })
      setResult(res)
      setActiveJobId(res.job_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">Single Video Run</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <p className="text-xs text-muted-foreground">
          Process an individual YouTube video or playlist URL without creating a preset.
        </p>
        <div className="grid gap-1.5">
          <Label htmlFor="single-url" className="text-xs">YouTube URL</Label>
          <div className="relative">
            <Youtube className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="single-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              className="pl-8"
            />
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="single-prompt" className="text-xs">Prompt (optional)</Label>
          <Textarea
            id="single-prompt"
            value={promptMd}
            onChange={(e) => setPromptMd(e.target.value)}
            rows={2}
            placeholder="Custom instructions for this run..."
          />
        </div>
        <Button
          onClick={run}
          disabled={running || !url.trim()}
          size="sm"
          className="w-full"
        >
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          <span className="ml-1.5">{running ? 'Processing...' : 'Run Single Video'}</span>
        </Button>
        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}
        {result && (
          <div className="rounded-md bg-primary/10 p-2.5 text-xs">
            <p className="font-medium text-primary">Started successfully</p>
            <p className="text-muted-foreground mt-0.5">
              Job ID: {result.job_id}
              {result.video_title && ` · ${result.video_title}`}
            </p>
          </div>
        )}

        {/* SSE Progress */}
        {activeJobId && latestEvent && (
          <div className="rounded-md border border-border p-2.5 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                {latestEvent.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
                {latestEvent.status === 'completed' && <span className="text-emerald-500">&#10003;</span>}
                {latestEvent.status === 'failed' && <span className="text-destructive">&#10007;</span>}
                <span>{latestEvent.message}</span>
              </div>
              <button
                type="button"
                onClick={() => setActiveJobId(null)}
                className="text-muted-foreground hover:text-destructive"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
            {latestEvent.progress !== null && latestEvent.progress < 100 && (
              <Progress value={latestEvent.progress} />
            )}
            {latestEvent.video_title && (
              <p className="text-xs text-muted-foreground">Processing: {latestEvent.video_title}</p>
            )}
            {events.length > 1 && (
              <div className="max-h-24 overflow-y-auto space-y-0.5 rounded bg-muted/50 p-1.5">
                {events.slice(-6).map((e, i) => (
                  <div key={i} className="text-xs text-muted-foreground">
                    <span className="font-mono">{e.step}</span>: {e.message}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
