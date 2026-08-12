import { useEffect, useState } from 'react'
import { Plus, X, Search, Loader2, AlertTriangle, Lock, CheckCircle2 } from 'lucide-react'
import { api, type SocialStatus } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface SocialSourceEntry {
  platform: string
  identifier: string
  resolved_name?: string
  resolved_id?: string
  max_posts: number | null
}

interface PlatformMeta {
  value: 'reddit' | 'stocktwits' | 'x'
  label: string
  hint: string
}

const PLATFORMS: PlatformMeta[] = [
  { value: 'reddit', label: 'Reddit', hint: 'Subreddit (e.g. wallstreetbets)' },
  { value: 'stocktwits', label: 'Stocktwits', hint: 'Symbol or @user (e.g. AAPL, @trader1)' },
  { value: 'x', label: 'X/Twitter', hint: 'user, list/<id>, search/<query>, tweet/<id>' },
]

interface Props {
  sources: SocialSourceEntry[]
  onChange: (sources: SocialSourceEntry[]) => void
}

interface ResolutionRecord {
  display_name: string
  exists: boolean
}

export function SocialSourcesInput({ sources, onChange }: Props) {
  const [newPlatform, setNewPlatform] = useState<'reddit' | 'stocktwits' | 'x'>('reddit')
  const [newIdentifier, setNewIdentifier] = useState('')
  const [newMaxPosts, setNewMaxPosts] = useState('')
  const [resolving, setResolving] = useState<string | null>(null)
  const [status, setStatus] = useState<SocialStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [resolvedMap, setResolvedMap] = useState<Record<string, ResolutionRecord>>({})
  const [addError, setAddError] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    api.getSocialStatus()
      .then((s) => { if (!cancelled) setStatus(s) })
      .catch(() => { /* best-effort: leave platforms enabled if status is unavailable */ })
      .finally(() => { if (!cancelled) setStatusLoading(false) })
    return () => { cancelled = true }
  }, [])

  const isPlatformReady = (platform: string): boolean => {
    if (statusLoading || !status) return true
    if (platform === 'reddit') {
      return status.reddit.binary_found && status.reddit.authenticated
    }
    if (platform === 'x') {
      return status.twitter.binary_found && status.twitter.authenticated
    }
    if (platform === 'stocktwits') {
      return status.stocktwits.api_reachable
    }
    return false
  }

  const platformReason = (platform: string): string => {
    if (statusLoading || !status) return ''
    if (platform === 'reddit') {
      if (!status.reddit.binary_found) return 'CLI binary not found. Install and authenticate on the Social settings page.'
      if (!status.reddit.authenticated) return 'Not authenticated. Run the authorization flow on the Social settings page.'
      return ''
    }
    if (platform === 'x') {
      if (!status.twitter.binary_found) return 'CLI binary not found. Install and authenticate on the Social settings page.'
      if (!status.twitter.authenticated) return 'Not authenticated. Run the authorization flow on the Social settings page.'
      return ''
    }
    if (platform === 'stocktwits') {
      if (!status.stocktwits.api_reachable) return 'Stocktwits API is not reachable from this host.'
      return ''
    }
    return ''
  }

  const normalize = (platform: string, identifier: string): string => {
    const ident = identifier.trim()
    if (platform === 'reddit') {
      return ident.replace(/^\/?r\//i, '').trim()
    }
    if (platform === 'stocktwits') {
      return ident.replace(/^\$/, '').trim()
    }
    return ident
  }

  const resolveKey = (source: { platform: string; identifier: string }) => `${source.platform}:${source.identifier}`

  const add = async () => {
    const raw = newIdentifier.trim()
    if (!raw || !isPlatformReady(newPlatform)) return

    // Reason: YouTube-style comma-separated batch input. Each item is
    // normalized, resolved, and only added if the platform confirms it exists.
    const parts = raw
      .split(',')
      .map((part) => normalize(newPlatform, part))
      .filter(Boolean)
    if (!parts.length) return

    setResolving('add')
    setAddError('')
    const resolved: SocialSourceEntry[] = []

    try {
      for (const ident of parts) {
        try {
          const result = await api.resolveSocialSource(newPlatform, ident)
          setResolvedMap((prev) => ({
            ...prev,
            [resolveKey({ platform: newPlatform, identifier: ident })]: {
              display_name: result.display_name,
              exists: result.exists,
            },
          }))
          if (result.exists) {
            resolved.push({
              platform: newPlatform,
              identifier: result.resolved_identifier || ident,
              resolved_name: result.display_name || undefined,
              resolved_id: result.resolved_identifier || undefined,
              max_posts: newMaxPosts ? parseInt(newMaxPosts) : null,
            })
          }
        } catch (e) {
          // eslint-disable-next-line no-console
          console.warn('Social source resolution failed:', e)
        }
      }

      if (resolved.length !== parts.length) {
        setAddError(`Added ${resolved.length} of ${parts.length} source(s); unresolved items were skipped.`)
      }

      if (resolved.length) {
        onChange([...sources, ...resolved])
      }
    } finally {
      setResolving(null)
      if (resolved.length === parts.length) {
        setNewIdentifier('')
        setNewMaxPosts('')
      }
    }
  }

  const remove = (idx: number) => {
    onChange(sources.filter((_, i) => i !== idx))
  }

  const resolveOne = async (idx: number) => {
    const source = sources[idx]
    if (!source?.identifier) return
    setResolving(`${idx}`)
    try {
      const result = await api.resolveSocialSource(source.platform, source.identifier)
      const next = [...sources]
      next[idx] = {
        ...next[idx],
        identifier: result.resolved_identifier || next[idx].identifier,
        resolved_name: result.display_name || undefined,
        resolved_id: result.resolved_identifier || undefined,
      }
      setResolvedMap((prev) => ({
        ...prev,
        [resolveKey(next[idx])]: {
          display_name: result.display_name,
          exists: result.exists,
        },
      }))
      onChange(next)
    } catch (e) {
      // Resolution is best-effort; keep the user-supplied value.
      // eslint-disable-next-line no-console
      console.warn('Social source resolution failed:', e)
    } finally {
      setResolving(null)
    }
  }

  const addDisabled = resolving === 'add' || !newIdentifier.trim() || !isPlatformReady(newPlatform)

  return (
    <div className="rounded-md border border-border p-3 space-y-3">
      <div className="flex items-center gap-1.5">
        <Label className="text-xs font-medium">Social Sources</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Add social platforms and source identifiers to collect posts from.
      </p>

      <div className="flex flex-wrap gap-2">
        <Select value={newPlatform} onValueChange={(v) => setNewPlatform(v as typeof newPlatform)}>
          <SelectTrigger className="h-9 w-[140px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PLATFORMS.map((p) => {
              const ready = isPlatformReady(p.value)
              return (
                <SelectItem key={p.value} value={p.value} disabled={!ready}>
                  <span className="flex items-center gap-1.5">
                    {p.label}
                    {!ready && <Lock className="h-3 w-3" />}
                  </span>
                </SelectItem>
              )
            })}
          </SelectContent>
        </Select>
        <Input
          className="flex-1 min-w-[180px] h-9 text-xs"
          placeholder={PLATFORMS.find((p) => p.value === newPlatform)?.hint || 'Identifier'}
          value={newIdentifier}
          onChange={(e) => setNewIdentifier(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
          disabled={!isPlatformReady(newPlatform)}
        />
        <Input
          className="w-28 h-9 text-xs"
          placeholder="Max"
          title="Max posts per source. Leave blank to collect every post in the lookback window."
          aria-label="Max posts per source. Leave blank to collect every post in the lookback window."
          type="number"
          min={1}
          value={newMaxPosts}
          onChange={(e) => setNewMaxPosts(e.target.value)}
          disabled={!isPlatformReady(newPlatform)}
        />
        <Button type="button" size="sm" onClick={add} disabled={addDisabled}>
          <Plus className="mr-1 h-3 w-3" />
          Add
        </Button>
      </div>

      {!isPlatformReady(newPlatform) && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          {platformReason(newPlatform)}
        </p>
      )}

      {addError && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          {addError}
        </p>
      )}

      {sources.length === 0 && (
        <p className="text-xs text-muted-foreground italic">No sources added yet.</p>
      )}
      {sources.map((s, i) => {
        const resolution = resolvedMap[resolveKey(s)]
        const resolvedBadge = resolution ? (
          resolution.exists ? (
            <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <AlertTriangle className="h-3 w-3 text-amber-600 dark:text-amber-400" />
          )
        ) : null

        return (
          <div key={i} className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
              {s.platform}
            </span>
            <div className="flex-1 min-w-0">
              <code className="block truncate text-muted-foreground">{s.identifier}</code>
              {s.resolved_name && s.resolved_name !== s.identifier && (
                <span className="block truncate text-emerald-600 dark:text-emerald-400">
                  {s.resolved_name}
                </span>
              )}
            </div>
            {s.max_posts != null && (
              <span
                className="text-muted-foreground"
                title="Max posts per source. Leave blank to collect every post in the lookback window."
              >
                max {s.max_posts}
              </span>
            )}
            {resolvedBadge && (
              <span
                className="flex items-center"
                title={resolution?.exists ? `Resolved: ${resolution.display_name}` : 'Could not resolve this source'}
              >
                {resolvedBadge}
              </span>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-destructive"
              onClick={() => resolveOne(i)}
              disabled={resolving === `${i}` || !isPlatformReady(s.platform)}
              title="Resolve source"
            >
              {resolving === `${i}` ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Search className="h-3 w-3" />
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-destructive"
              onClick={() => remove(i)}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        )
      })}
    </div>
  )
}
