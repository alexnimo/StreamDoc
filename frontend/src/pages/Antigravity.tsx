import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Rocket, RefreshCw, Loader2, AlertCircle, CheckCircle2,
  PackageOpen, Download, Boxes, Terminal,
} from 'lucide-react'
import { api, type AgySkillInfo, type Settings } from '@/lib/api'
import CLITools from '@/pages/CLITools'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'

// Reason: T7's api.agy.status() is typed as Record<string, unknown> because
// the response shape wasn't pinned at the client layer. We narrow it here
// rather than touching api.ts (out of scope for T8 — T7 owns that file).
interface AgyStatus {
  installed: boolean
  binary: string | null
  agy_version: string | null
  install_url: string | null
}

export default function Antigravity() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Antigravity</h1>
        <p className="text-sm text-muted-foreground">
          Manage the agy CLI, installed skills, and configuration
        </p>
      </div>
      <Tabs defaultValue="status">
        <TabsList>
          <TabsTrigger value="status">Status</TabsTrigger>
          <TabsTrigger value="skills">Skills</TabsTrigger>
          <TabsTrigger value="cli">CLI Tools</TabsTrigger>
          <TabsTrigger value="config">Configuration</TabsTrigger>
        </TabsList>
        <TabsContent value="status"><StatusTab /></TabsContent>
        <TabsContent value="skills"><SkillsTab /></TabsContent>
        <TabsContent value="cli"><CLITools embedded /></TabsContent>
        <TabsContent value="config"><ConfigurationTab /></TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status Tab
// ---------------------------------------------------------------------------
function StatusTab() {
  const [status, setStatus] = useState<AgyStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const load = () => {
    setChecking(true)
    api.agy.status()
      .then((s) => { setStatus(s as unknown as AgyStatus); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => { setLoading(false); setChecking(false) })
  }

  useEffect(() => { load() }, [])

  if (loading) {
    return (
      <div className="py-8 text-center text-xs text-muted-foreground">
        <Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin" />
        Checking agy CLI status...
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
        {error}
      </div>
    )
  }
  if (!status) return null

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Rocket className="h-4 w-4" /> Antigravity CLI
          </CardTitle>
          <CardDescription className="text-xs">
            Local binary discovery and version probe
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-muted-foreground">Installed</span>
              <p className="flex items-center gap-1.5 font-medium">
                {status.installed ? (
                  <>
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                    Yes
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                    Not installed
                  </>
                )}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">Version</span>
              <p className="font-mono text-xs">{status.agy_version || '—'}</p>
            </div>
            <div className="col-span-2">
              <span className="text-muted-foreground">Binary path</span>
              <p className="font-mono text-xs break-all">{status.binary || '—'}</p>
            </div>
          </div>
          <div className="flex gap-2 pt-2">
            <Button onClick={load} disabled={checking} size="sm" variant="outline" className="gap-1.5">
              {checking ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Re-check
            </Button>
          </div>
        </CardContent>
      </Card>

      {!status.installed && (
        <Card className="border-amber-500/30">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <div className="text-xs">
              <p className="font-medium">Antigravity CLI not found on PATH</p>
              <p className="text-muted-foreground">
                Install the <code className="rounded bg-muted px-1">agy</code> CLI
                to run skills locally.{" "}
                {status.install_url && (
                  <a
                    href={status.install_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline"
                  >
                    Install instructions
                  </a>
                )}
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skills Tab
// ---------------------------------------------------------------------------
function SkillsTab() {
  const [skills, setSkills] = useState<AgySkillInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [installing, setInstalling] = useState<string | null>(null)
  const [installError, setInstallError] = useState<string | null>(null)
  const [installingAll, setInstallingAll] = useState(false)
  const [confirmAllOpen, setConfirmAllOpen] = useState(false)
  const [updatingUpstream, setUpdatingUpstream] = useState(false)
  const [upstreamMessage, setUpstreamMessage] = useState<string | null>(null)

  const load = () => {
    api.agy.listAvailableSkills()
      .then((s) => { setSkills(s); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const installOne = async (name: string) => {
    setInstalling(name)
    setInstallError(null)
    try {
      await api.agy.installSkill(name)
      load()
    } catch (e) {
      setInstallError((e as Error).message)
    } finally {
      setInstalling(null)
    }
  }

  const installAll = async () => {
    setInstallingAll(true)
    setInstallError(null)
    try {
      await api.agy.installAll()
      load()
    } catch (e) {
      setInstallError((e as Error).message)
    } finally {
      setInstallingAll(false)
    }
  }

  const updateFromUpstream = async () => {
    setUpdatingUpstream(true)
    setUpstreamMessage(null)
    setInstallError(null)
    try {
      const res = await api.agy.updateFromUpstream() as { installed?: string[] }
      const names = res.installed || []
      setUpstreamMessage(
        names.length > 0
          ? `Updated ${names.length} skill(s) from upstream: ${names.join(', ')}`
          : 'No skills were updated (check server logs for details).',
      )
      load()
    } catch (e) {
      setInstallError((e as Error).message)
    } finally {
      setUpdatingUpstream(false)
    }
  }

  if (loading) {
    return (
      <div className="py-8 text-center text-xs text-muted-foreground">
        Loading skills...
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
        {error}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {skills.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-8 text-center">
            <PackageOpen className="mb-2 h-6 w-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No skills available.</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="space-y-3">
            {skills.map((skill) => (
              <Card key={skill.name} className="hover:shadow-md transition-shadow">
                <CardContent className="flex items-center justify-between p-4">
                  <div className="flex items-center gap-3">
                    <Boxes className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="font-medium text-sm">{skill.name}</p>
                      <p className="text-xs">
                        {skill.installed ? (
                          <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> Installed
                          </span>
                        ) : (
                          <span className="text-muted-foreground">Available</span>
                        )}
                      </p>
                    </div>
                  </div>
                  {!skill.installed && (
                    <Button
                      onClick={() => installOne(skill.name)}
                      disabled={installing === skill.name}
                      size="sm"
                      variant="outline"
                      className="gap-1.5"
                    >
                      {installing === skill.name ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                      Install
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={() => setConfirmAllOpen(true)}
              disabled={installingAll}
              size="sm"
              className="gap-1.5"
            >
              {installingAll ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Boxes className="h-3.5 w-3.5" />
              )}
              Install All
            </Button>
            <Button
              onClick={updateFromUpstream}
              disabled={updatingUpstream}
              size="sm"
              variant="outline"
              className="gap-1.5"
            >
              {updatingUpstream ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Update from upstream
            </Button>
            {installError && (
              <p className="text-xs text-destructive">{installError}</p>
            )}
          </div>
          {upstreamMessage && (
            <p className="text-xs text-emerald-600 dark:text-emerald-400">
              {upstreamMessage}
            </p>
          )}
        </>
      )}

      <ConfirmDialog
        open={confirmAllOpen}
        onOpenChange={setConfirmAllOpen}
        title="Install all skills?"
        description="This copies every available skill to the install directory. Existing files will be overwritten."
        confirmText="Install All"
        onConfirm={installAll}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Configuration Tab
// ---------------------------------------------------------------------------
function ConfigurationTab() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [models, setModels] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      api.getSettings(),
      api.agy.supportedModels().catch(() => []),
    ])
      .then(([s, discoveredModels]) => {
        setSettings(s)
        setModels(discoveredModels)
        setError(null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="py-8 text-center text-xs text-muted-foreground">
        <Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin" />
        Loading configuration...
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
        {error}
      </div>
    )
  }
  if (!settings) return null

  const modelList = models?.length
    ? models
    : (settings.agy_supported_models || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Rocket className="h-4 w-4" /> Antigravity Configuration
        </CardTitle>
        <CardDescription className="text-xs">
          Read-only view of the agy-related settings
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 text-xs">
          <ConfigRow label="Enabled" value={settings.agy_enabled ? 'Yes' : 'No'} />
          <ConfigRow
            label="Default Skill"
            value={settings.agy_default_skill || '—'}
            mono
          />
          <ConfigRow
            label="Default Model"
            value={settings.agy_default_model || '—'}
            mono
          />
          <ConfigRow
            label="Wait Timeout"
            value={`${settings.agy_default_wait_timeout}s`}
            mono
          />
          <ConfigRow
            label="Install Dir"
            value={settings.agy_install_dir}
            mono
          />
          <ConfigRow
            label="Global Dir"
            value={settings.agy_global_dir}
            mono
          />
          <ConfigRow
            label="Templates Dir"
            value={settings.agy_templates_dir}
            mono
          />
          <ConfigRow
            label="Sample Prompts Dir"
            value={settings.agy_sample_prompts_dir}
            mono
          />
          <ConfigRow
            label="Output Dir"
            value={settings.agy_output_dir}
            mono
          />
          <div className="col-span-2">
            <span className="text-muted-foreground">Supported Models</span>
            {modelList.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {modelList.map((m) => (
                  <span
                    key={m}
                    className="rounded-md border border-border bg-secondary/50 px-2 py-0.5 font-mono text-xs"
                  >
                    {m}
                  </span>
                ))}
              </div>
            ) : (
              <p className="font-mono text-xs">—</p>
            )}
          </div>
        </div>
        <p className="pt-2 text-xs text-muted-foreground">
          Edit these values in the{' '}
          <Link to="/settings" className="text-primary underline">Settings</Link>
          {' '}page.
        </p>
      </CardContent>
    </Card>
  )
}

function ConfigRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div>
      <span className="text-muted-foreground">{label}</span>
      <p className={`text-xs ${mono ? 'font-mono' : 'font-medium'}`}>{value}</p>
    </div>
  )
}
