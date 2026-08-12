import { useEffect, useState } from 'react'
import { ArrowLeft, CheckCircle2, AlertTriangle, XCircle, Loader2, RefreshCw, LogIn, Activity, Save } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { SocialStatus, TwitterStatus, RedditStatus, StocktwitsStatus } from '@/lib/api'

interface PlatformSpec {
  key: 'twitter' | 'reddit' | 'stocktwits'
  label: string
  description: string
  binaryPathKey?: string
  apiBaseKey?: string
}

const platforms: PlatformSpec[] = [
  {
    key: 'twitter',
    label: 'X (Twitter)',
    description: 'Requires the twitter CLI. Authorize verifies the current X session from browser cookies.',
    binaryPathKey: 'twitter_cli_binary_path',
  },
  {
    key: 'reddit',
    label: 'Reddit',
    description: 'Requires the rdt CLI. Authorize extracts browser cookies.',
    binaryPathKey: 'rdt_cli_binary_path',
  },
  {
    key: 'stocktwits',
    label: 'Stocktwits',
    description: 'No authentication required. Configure the API base URL if needed.',
    apiBaseKey: 'stocktwits_api_base',
  },
]

function statusColor(status: TwitterStatus | RedditStatus | StocktwitsStatus) {
  if ('authenticated' in status) {
    if (!status.binary_found) return 'text-destructive'
    if (status.authenticated) return 'text-emerald-500'
    return 'text-amber-500'
  }
  if ('api_reachable' in status) {
    return status.api_reachable ? 'text-emerald-500' : 'text-destructive'
  }
  return 'text-muted-foreground'
}

function StatusIcon({ status }: { status: TwitterStatus | RedditStatus | StocktwitsStatus }) {
  const color = statusColor(status)
  if ('authenticated' in status) {
    if (!status.binary_found) return <XCircle className={`h-5 w-5 ${color}`} />
    if (status.authenticated) return <CheckCircle2 className={`h-5 w-5 ${color}`} />
    return <AlertTriangle className={`h-5 w-5 ${color}`} />
  }
  if ('api_reachable' in status) {
    return status.api_reachable
      ? <CheckCircle2 className={`h-5 w-5 ${color}`} />
      : <XCircle className={`h-5 w-5 ${color}`} />
  }
  return <Activity className="h-5 w-5 text-muted-foreground" />
}

function StatusText({ status }: { status: TwitterStatus | RedditStatus | StocktwitsStatus }) {
  if ('authenticated' in status) {
    if (!status.binary_found) return <span>Not configured</span>
    if (status.authenticated) return <span>Authenticated</span>
    return <span>Binary found, not authenticated</span>
  }
  if ('api_reachable' in status) {
    return status.api_reachable
      ? <span>API reachable</span>
      : <span>API unreachable</span>
  }
  return <span>Unknown</span>
}

export default function SocialSettings() {
  const [status, setStatus] = useState<SocialStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [savingField, setSavingField] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [authPending, setAuthPending] = useState<string | null>(null)
  const [testPending, setTestPending] = useState<string | null>(null)
  const [configValues, setConfigValues] = useState<Record<string, string>>({})

  const fetchStatus = async () => {
    setRefreshing(true)
    setError(null)
    try {
      const data = await api.getSocialStatus()
      setStatus(data)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const fetchConfig = async () => {
    try {
      const settings = await api.getSettings()
      setConfigValues({
        twitter_cli_binary_path: String(settings.twitter_cli_binary_path || ''),
        rdt_cli_binary_path: String(settings.rdt_cli_binary_path || ''),
        stocktwits_api_base: String(settings.stocktwits_api_base || ''),
      })
    } catch (e) {
      // Non-fatal: inputs will be empty but editable.
    }
  }

  useEffect(() => {
    fetchStatus()
    fetchConfig()
  }, [])

  const handleAuth = async (platform: string) => {
    setAuthPending(platform)
    setError(null)
    try {
      const res = await api.authSocialPlatform(platform)
      alert(res.message)
      await fetchStatus()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setAuthPending(null)
    }
  }

  const handleTest = async (platform: string) => {
    setTestPending(platform)
    setError(null)
    try {
      const res = await api.testSocialPlatform(platform)
      alert(`${platform}: ${res.success ? 'OK' : 'Failed'} - ${res.message}`)
      await fetchStatus()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setTestPending(null)
    }
  }

  const updateConfigValue = (key: string, value: string) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }))
  }

  const saveConfigField = async (key: string) => {
    setSavingField(key)
    setError(null)
    try {
      const value = configValues[key]
      await api.updateSettings({ [key]: value || null })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSavingField(null)
    }
  }

  if (loading) {
    return (
      <div className="py-20 text-center text-xs text-muted-foreground animate-pulse">
        Loading social settings...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/settings" className="gap-1.5">
            <ArrowLeft className="h-4 w-4" />
            Back
          </Link>
        </Button>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Social Settings</h1>
          <p className="text-sm text-muted-foreground">Configure Reddit, X, and Stocktwits access</p>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {platforms.map((platform) => {
          const platformStatus = status?.[platform.key]
          if (!platformStatus) return null

          return (
            <Card key={platform.key}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">{platform.label}</CardTitle>
                  <StatusIcon status={platformStatus} />
                </div>
                <CardDescription className="text-xs">{platform.description}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2 text-xs">
                  <span className={statusColor(platformStatus)}>
                    <StatusText status={platformStatus} />
                  </span>
                </div>

                {'binary_found' in platformStatus && platformStatus.binary_found && (
                  <>
                    <div className="text-xs text-muted-foreground">
                      Version: {platformStatus.version || 'unknown'}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Last check: {platformStatus.last_check ? new Date(platformStatus.last_check).toLocaleString() : 'never'}
                    </div>
                  </>
                )}
                {'binary_found' in platformStatus && !platformStatus.binary_found && (
                  <div className="text-xs text-muted-foreground">
                    {platformStatus.message}
                  </div>
                )}

                {'api_reachable' in platformStatus && (
                  <>
                    <div className="text-xs text-muted-foreground">
                      Last check: {platformStatus.last_check ? new Date(platformStatus.last_check).toLocaleString() : 'never'}
                    </div>
                    {platformStatus.rate_limit_remaining && (
                      <div className="text-xs text-muted-foreground">
                        Rate limit remaining: {platformStatus.rate_limit_remaining}
                      </div>
                    )}
                  </>
                )}

                {platform.binaryPathKey && (
                  <div className="space-y-1.5">
                    <Label htmlFor={platform.binaryPathKey} className="text-xs">Binary path</Label>
                    <div className="flex gap-2">
                      <Input
                        id={platform.binaryPathKey}
                        value={configValues[platform.binaryPathKey] || ''}
                        onChange={(e) => updateConfigValue(platform.binaryPathKey!, e.target.value)}
                        placeholder="Auto-detected if left blank"
                        className="h-8 text-xs"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 px-2"
                        onClick={() => saveConfigField(platform.binaryPathKey!)}
                        disabled={savingField === platform.binaryPathKey}
                      >
                        {savingField === platform.binaryPathKey ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Save className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  </div>
                )}

                {platform.apiBaseKey && (
                  <div className="space-y-1.5">
                    <Label htmlFor={platform.apiBaseKey} className="text-xs">API base URL</Label>
                    <div className="flex gap-2">
                      <Input
                        id={platform.apiBaseKey}
                        value={configValues[platform.apiBaseKey] || ''}
                        onChange={(e) => updateConfigValue(platform.apiBaseKey!, e.target.value)}
                        placeholder="https://api.stocktwits.com/api/2/"
                        className="h-8 text-xs"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 px-2"
                        onClick={() => saveConfigField(platform.apiBaseKey!)}
                        disabled={savingField === platform.apiBaseKey}
                      >
                        {savingField === platform.apiBaseKey ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Save className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  </div>
                )}

                <div className="flex gap-2 pt-1">
                  {platform.key !== 'stocktwits' && (
                    <Button
                      size="sm"
                      className="h-8 gap-1.5"
                      onClick={() => handleAuth(platform.key)}
                      disabled={authPending === platform.key}
                    >
                      {authPending === platform.key ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <LogIn className="h-3.5 w-3.5" />
                      )}
                      Authorize
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5"
                    onClick={() => handleTest(platform.key)}
                    disabled={testPending === platform.key}
                  >
                    {testPending === platform.key ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Activity className="h-3.5 w-3.5" />
                    )}
                    Test
                  </Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className="flex justify-end">
        <Button variant="outline" size="sm" className="gap-1.5" onClick={fetchStatus} disabled={refreshing}>
          {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh Status
        </Button>
      </div>
    </div>
  )
}
