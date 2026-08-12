import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw, Download, CheckCircle2, AlertCircle, Clock, History, Package, Shield,
} from 'lucide-react'
import { api, type PluginStatus, type PluginUpdateLog, type PotProviderStatus } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

/** Format an ISO timestamp as a short relative time string. */
function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 0) return 'just now'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function PluginUpdates() {
  const [plugins, setPlugins] = useState<PluginStatus[]>([])
  const [logs, setLogs] = useState<PluginUpdateLog[]>([])
  const [potStatus, setPotStatus] = useState<PotProviderStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [updating, setUpdating] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([api.listPlugins(), api.getPluginLogs(20), api.getPotStatus()])
      .then(([p, l, pot]) => {
        setPlugins(p)
        setLogs(l)
        setPotStatus(pot)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const checkAll = async () => {
    setChecking(true)
    try {
      const result = await api.checkAllPlugins()
      setPlugins(result)
      setLogs(await api.getPluginLogs(20))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  const updateOne = async (name: string) => {
    setUpdating(name)
    try {
      await api.updatePlugin(name)
      setPlugins(await api.listPlugins())
      setLogs(await api.getPluginLogs(20))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUpdating(null)
    }
  }

  const anyUpdateAvailable = plugins.some((p) => p.update_available)

  if (loading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Package className="h-4 w-4" />
            Plugin Updates
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            Checking plugin versions...
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm flex items-center gap-2">
              <Package className="h-4 w-4" />
              Plugin Updates
              {anyUpdateAvailable && (
                <Badge variant="destructive" className="text-[10px] gap-1">
                  <AlertCircle className="h-3 w-3" />
                  {plugins.filter((p) => p.update_available).length} update{plugins.filter((p) => p.update_available).length > 1 ? 's' : ''}
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              yt-dlp, ffmpeg, and whisper version status
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={checkAll} disabled={checking} className="gap-1.5">
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? 'animate-spin' : ''}`} />
            Check All
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <p className="text-xs text-destructive">{error}</p>}

        {/* PO Token provider status */}
        {potStatus && (
          <div className="flex items-center justify-between rounded-md border border-border bg-muted/30 px-3 py-2">
            <div className="flex items-center gap-2">
              <Shield className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium">PO Token</span>
              {potStatus.status === 'active' ? (
                <Badge variant="secondary" className="text-[10px] gap-1 text-emerald-600">
                  <CheckCircle2 className="h-2.5 w-2.5" />
                  Active
                </Badge>
              ) : potStatus.status === 'starting' ? (
                <Badge variant="secondary" className="text-[10px] gap-1 text-amber-600">
                  <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                  Starting
                </Badge>
              ) : potStatus.status === 'stopped' ? (
                <Badge variant="secondary" className="text-[10px] gap-1 text-amber-600">
                  <AlertCircle className="h-2.5 w-2.5" />
                  Stopped
                </Badge>
              ) : (
                <Badge variant="secondary" className="text-[10px] gap-1 text-muted-foreground">
                  <AlertCircle className="h-2.5 w-2.5" />
                  Unavailable
                </Badge>
              )}
            </div>
            <span className="text-[10px] text-muted-foreground truncate ml-2">{potStatus.message}</span>
          </div>
        )}

        {plugins.map((plugin) => (
          <div
            key={plugin.name}
            className="flex items-center justify-between rounded-md border border-border bg-muted/30 px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{plugin.display_name}</span>
                {plugin.update_available ? (
                  <Badge variant="destructive" className="text-[10px] gap-1">
                    <AlertCircle className="h-2.5 w-2.5" />
                    Update available
                  </Badge>
                ) : plugin.installed_version ? (
                  <Badge variant="secondary" className="text-[10px] gap-1">
                    <CheckCircle2 className="h-2.5 w-2.5" />
                    Up to date
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="text-[10px]">Not installed</Badge>
                )}
                {plugin.auto_update_enabled && (
                  <Badge variant="outline" className="text-[10px]">auto</Badge>
                )}
              </div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                <span>
                  {plugin.installed_version ? (
                    <code className="rounded bg-muted px-1 py-0.5">{plugin.installed_version}</code>
                  ) : '—'}
                </span>
                {plugin.latest_version && plugin.update_available && (
                  <span className="text-muted-foreground">
                    → <code className="rounded bg-muted px-1 py-0.5">{plugin.latest_version}</code>
                  </span>
                )}
                <span className="flex items-center gap-0.5">
                  <Clock className="h-2.5 w-2.5" />
                  checked {timeAgo(plugin.last_checked)}
                </span>
              </div>
              {plugin.update_message && (
                <p className="mt-0.5 text-[10px] text-muted-foreground truncate">{plugin.update_message}</p>
              )}
            </div>
            <div className="ml-2 flex-shrink-0">
              {plugin.update_available && (
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => updateOne(plugin.name)}
                  disabled={updating === plugin.name}
                  className="gap-1.5"
                >
                  {updating === plugin.name ? (
                    <RefreshCw className="h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="h-3 w-3" />
                  )}
                  Update
                </Button>
              )}
            </div>
          </div>
        ))}

        {/* Update logs */}
        <div className="pt-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowLogs((v) => !v)}
            className="gap-1.5 text-xs text-muted-foreground"
          >
            <History className="h-3 w-3" />
            {showLogs ? 'Hide' : 'Show'} update log
          </Button>
          {showLogs && (
            <div className="mt-2 max-h-48 overflow-y-auto rounded-md border border-border bg-muted/20 p-2">
              {logs.length === 0 ? (
                <p className="text-[11px] text-muted-foreground py-2 text-center">No update events yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {logs.map((log, i) => (
                    <div key={i} className="flex items-start gap-2 text-[11px]">
                      {log.success ? (
                        <CheckCircle2 className="h-3 w-3 text-emerald-500 mt-0.5 flex-shrink-0" />
                      ) : (
                        <AlertCircle className="h-3 w-3 text-destructive mt-0.5 flex-shrink-0" />
                      )}
                      <span className="text-muted-foreground">{timeAgo(log.timestamp)}</span>
                      <span className="font-medium">{log.plugin}</span>
                      <span className="text-muted-foreground">{log.action}</span>
                      {log.from_version && log.to_version && (
                        <span className="text-muted-foreground">
                          {log.from_version} → {log.to_version}
                        </span>
                      )}
                      {log.message && (
                        <span className="text-muted-foreground truncate">{log.message}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
