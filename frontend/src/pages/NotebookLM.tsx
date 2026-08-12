import { useEffect, useState } from 'react'
import {
  BookOpen, Plus, Trash2, Share2, Loader2, Upload,
  Clock, ShieldCheck, AlertCircle, Download, Sparkles,
} from 'lucide-react'
import { api, type NotebookLMAuthStatus, type Notebook, type RetentionContent, type RetentionCleanupResult, type PromptTemplate } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { formatDate } from '@/lib/utils'

export default function NotebookLM() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">NotebookLM</h1>
        <p className="text-sm text-muted-foreground">Manage notebooks, content generation, and retention</p>
      </div>
      <Tabs defaultValue="auth">
        <TabsList>
          <TabsTrigger value="auth">Auth</TabsTrigger>
          <TabsTrigger value="notebooks">Notebooks</TabsTrigger>
          <TabsTrigger value="upload">Upload</TabsTrigger>
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="retention">Retention</TabsTrigger>
        </TabsList>
        <TabsContent value="auth"><AuthTab /></TabsContent>
        <TabsContent value="notebooks"><NotebooksTab /></TabsContent>
        <TabsContent value="upload"><UploadTab /></TabsContent>
        <TabsContent value="content"><ContentTab /></TabsContent>
        <TabsContent value="retention"><RetentionTab /></TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Auth Tab
// ---------------------------------------------------------------------------
function AuthTab() {
  const [status, setStatus] = useState<NotebookLMAuthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)
  const [loginResult, setLoginResult] = useState<string | null>(null)
  const [cookieHeader, setCookieHeader] = useState('')
  const [cookieLogin, setCookieLogin] = useState(false)
  const [showCookieInput, setShowCookieInput] = useState(false)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)

  const load = () => {
    api.getNotebookLMAuthStatus()
      .then((s) => { setStatus(s); setLastChecked(new Date()) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  // Reason: Poll auth status every 30 minutes when the tab is visible.
  // The backend also runs a 12h keepalive task, but this lets the UI
  // detect session expiry sooner and prompt the user to re-login.
  useEffect(() => {
    load()
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 30 * 60 * 1000) // 30 minutes
    return () => clearInterval(interval)
  }, [])

  const login = async () => {
    setLoggingIn(true)
    setError(null)
    setLoginResult(null)
    try {
      const res = await api.loginNotebookLM(false)
      if (res.success) {
        setLoginResult(res.message)
        load()
      } else {
        setLoginResult(res.message)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoggingIn(false)
    }
  }

  const loginWithCookies = async () => {
    if (!cookieHeader.trim()) return
    setCookieLogin(true)
    setError(null)
    setLoginResult(null)
    try {
      const res = await api.loginNotebookLMWithCookies(cookieHeader.trim())
      if (res.success) {
        setLoginResult(res.message)
        setCookieHeader('')
        setShowCookieInput(false)
        load()
      } else {
        setLoginResult(res.message)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setCookieLogin(false)
    }
  }

  const logout = async () => {
    try { await api.logoutNotebookLM(); load() }
    catch (e) { setError((e as Error).message) }
  }

  if (loading) return <div className="py-8 text-center text-xs text-muted-foreground">Loading auth status...</div>
  if (error) return <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">{error}</div>
  if (!status) return null

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4" /> Authentication Status
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-muted-foreground">Profile</span>
              <p className="font-medium">{status.profile || '—'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Configured</span>
              <p className="font-medium">{status.configured ? 'Yes' : 'No'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Valid Session</span>
              <p><StatusBadge status={status.is_valid ? 'active' : 'unknown'} /></p>
            </div>
            <div>
              <span className="text-muted-foreground">Fresh Session</span>
              <p><StatusBadge status={status.is_fresh ? 'active' : 'unknown'} /></p>
            </div>
            <div className="col-span-2">
              <span className="text-muted-foreground">Storage Path</span>
              <p className="font-mono text-xs">{status.storage_path || '—'}</p>
            </div>
            <div className="col-span-2">
              <span className="text-muted-foreground">Message</span>
              <p className="text-xs">{status.message || '—'}</p>
            </div>
            {lastChecked && (
              <div className="col-span-2">
                <span className="text-muted-foreground">Last Checked</span>
                <p className="text-xs text-muted-foreground">{lastChecked.toLocaleTimeString()}</p>
              </div>
            )}
          </div>
          <div className="flex gap-2 pt-2">
            <Button
              onClick={login}
              disabled={loggingIn}
              size="sm"
              className="gap-1.5"
            >
              {loggingIn ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              {loggingIn ? 'Opening browser...' : 'Login via browser'}
            </Button>
            <Button
              variant="outline"
              onClick={() => setShowCookieInput(!showCookieInput)}
              size="sm"
            >
              Login via cookies
            </Button>
            <Button variant="outline" onClick={load} size="sm">
              Refresh status
            </Button>
            <Button variant="destructive" onClick={logout} disabled={!status.configured} size="sm">
              Logout
            </Button>
          </div>

          {showCookieInput && (
            <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
              <p className="text-xs font-medium">Login with Cookie header</p>
              <p className="text-xs text-muted-foreground">
                Open{' '}
                <a href="https://notebooklm.google.com" target="_blank" rel="noopener noreferrer" className="text-primary underline">
                  notebooklm.google.com
                </a>{' '}
                in your browser, open DevTools (F12) → Network tab, click any request,
                find the <code className="rounded bg-muted px-1">Cookie</code> request header,
                copy its value and paste it below.
              </p>
              <textarea
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="SID=xxx; __Secure-1PSIDTS=yyy; HSID=zzz; ..."
                value={cookieHeader}
                onChange={(e) => setCookieHeader(e.target.value)}
              />
              <Button
                onClick={loginWithCookies}
                disabled={cookieLogin || !cookieHeader.trim()}
                size="sm"
                className="gap-1.5"
              >
                {cookieLogin ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                {cookieLogin ? 'Saving...' : 'Save cookies'}
              </Button>
            </div>
          )}
          {loginResult && (
            <div className={`rounded-md p-2.5 text-xs ${loginResult.includes('success') ? 'bg-primary/10 text-primary' : 'bg-destructive/10 text-destructive'}`}>
              {loginResult}
            </div>
          )}
        </CardContent>
      </Card>

      {!status.configured && (
        <Card className="border-amber-500/30">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <div className="text-xs">
              <p className="font-medium">Not authenticated</p>
              <p className="text-muted-foreground">
                Click "Login via cookies" and paste your Cookie header from
                notebooklm.google.com (easiest), or "Login via browser" to
                open a browser window for Google sign-in.
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Notebooks Tab
// ---------------------------------------------------------------------------
function NotebooksTab() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  const load = () => {
    api.listNotebooks()
      .then(setNotebooks)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const create = async () => {
    if (!newTitle) return
    setCreating(true)
    try { await api.createNotebook(newTitle); setNewTitle(''); load() }
    catch (e) { setError((e as Error).message) }
    finally { setCreating(false) }
  }

  const confirmDelete = async () => {
    if (!deleteId) return
    try { await api.deleteNotebook(deleteId); load() }
    catch (e) { setError((e as Error).message) }
  }

  const share = async (id: string) => {
    try {
      const res = await api.shareNotebook(id)
      setShareUrl(res.url)
    } catch (e) { setError((e as Error).message) }
  }

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">Loading notebooks...</div>

  return (
    <div className="space-y-4">
      {error && <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      <Card>
        <CardHeader><CardTitle className="text-base">Create Notebook</CardTitle></CardHeader>
        <CardContent className="flex gap-2">
          <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="Notebook title" />
          <Button onClick={create} disabled={creating || !newTitle} className="gap-2">
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create
          </Button>
        </CardContent>
      </Card>

      {notebooks.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          <BookOpen className="mx-auto mb-2 h-6 w-6" />No notebooks found.
        </CardContent></Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {notebooks.map((nb) => (
            <Card key={nb.id} className="hover:shadow-md transition-shadow">
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <p className="font-medium">{nb.title}</p>
                  <p className="text-xs text-muted-foreground">{nb.sources_count} sources · {nb.id}</p>
                </div>
                <div className="flex gap-1">
                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Share" onClick={() => share(nb.id)}>
                    <Share2 className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Delete" onClick={() => setDeleteId(nb.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {shareUrl && (
        <Card className="border-primary/30">
          <CardContent className="flex items-center justify-between p-4">
            <div>
              <p className="text-sm font-medium">Share URL</p>
              <a href={shareUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">
                {shareUrl}
              </a>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setShareUrl(null)}>Close</Button>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(v) => !v && setDeleteId(null)}
        title="Delete Notebook"
        description="Are you sure you want to delete this notebook? This action cannot be undone."
        confirmText="Delete"
        destructive
        onConfirm={confirmDelete}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Content Tab
// ---------------------------------------------------------------------------
function ContentTab() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([])
  const [selectedNb, setSelectedNb] = useState('')
  const [contentType, setContentType] = useState('slide_deck')
  const [promptTemplate, setPromptTemplate] = useState('')
  const [title, setTitle] = useState('')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [batchTypes, setBatchTypes] = useState('slide_deck,infographic')
  const [batching, setBatching] = useState(false)
  const [batchResult, setBatchResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    api.listNotebooks().then(setNotebooks).catch(() => {})
    // Reason: pull available prompt templates from the API instead of hard-coding them
    api.listPrompts().then(setPromptTemplates).catch(() => {})
  }, [])

  const generate = async () => {
    if (!selectedNb) return
    setGenerating(true)
    setResult(null)
    try {
      const res = await api.generateContent({
        notebook_id: selectedNb,
        content_type: contentType,
        prompt_template: promptTemplate,
        title: title || undefined,
        wait: true,
        download: true,
      })
      setResult(res)
    } catch (e) { setError((e as Error).message) }
    finally { setGenerating(false) }
  }

  const batchGenerate = async () => {
    if (!selectedNb) return
    setBatching(true)
    setBatchResult(null)
    try {
      const res = await api.batchGenerate({
        notebook_id: selectedNb,
        types: batchTypes,
        prompt_template: promptTemplate,
      })
      setBatchResult(res)
    } catch (e) { setError((e as Error).message) }
    finally { setBatching(false) }
  }

  return (
    <div className="space-y-4">
      {error && <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-5 w-5" /> Generate Content
          </CardTitle>
          <CardDescription>Generate a single content artifact in a notebook</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>Notebook</Label>
            <Select value={selectedNb} onValueChange={setSelectedNb}>
              <SelectTrigger><SelectValue placeholder="Select notebook" /></SelectTrigger>
              <SelectContent>
                {notebooks.map((nb) => <SelectItem key={nb.id} value={nb.id}>{nb.title}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label>Content Type</Label>
              <Select value={contentType} onValueChange={setContentType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="slide_deck">Slide Deck</SelectItem>
                  <SelectItem value="podcast">Podcast</SelectItem>
                  <SelectItem value="infographic">Infographic</SelectItem>
                  <SelectItem value="report">Report</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Prompt Template</Label>
              <Select value={promptTemplate} onValueChange={setPromptTemplate}>
                <SelectTrigger><SelectValue placeholder="None (default)" /></SelectTrigger>
                <SelectContent>
                  {promptTemplates.map((t) => (
                    <SelectItem key={t.name} value={t.name}>
                      {t.name}{t.description ? ` — ${t.description}` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Title (optional)</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Custom title" />
          </div>
          <Button onClick={generate} disabled={generating || !selectedNb} className="gap-2">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {generating ? 'Generating...' : 'Generate & Download'}
          </Button>
          {result && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <p className="font-medium">Result</p>
              <pre className="mt-1 text-xs overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Batch Generate</CardTitle>
          <CardDescription>Generate multiple content types in parallel</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>Content Types (comma-separated)</Label>
            <Input value={batchTypes} onChange={(e) => setBatchTypes(e.target.value)} />
          </div>
          <Button onClick={batchGenerate} disabled={batching || !selectedNb} className="gap-2">
            {batching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {batching ? 'Generating...' : 'Batch Generate'}
          </Button>
          {batchResult && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <p className="font-medium">Batch Result</p>
              <pre className="mt-1 text-xs overflow-x-auto">{JSON.stringify(batchResult, null, 2)}</pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Upload Tab
// ---------------------------------------------------------------------------
function UploadTab() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [selectedNb, setSelectedNb] = useState('')
  const [filePath, setFilePath] = useState('')
  const [title, setTitle] = useState('')
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listNotebooks().then(setNotebooks).catch(() => {})
  }, [])

  const upload = async () => {
    if (!selectedNb || !filePath) return
    setUploading(true)
    setResult(null)
    try {
      const res = await api.uploadContent({
        notebook_id: selectedNb,
        file_path: filePath,
        title: title || undefined,
      })
      setResult(res)
    } catch (e) { setError((e as Error).message) }
    finally { setUploading(false) }
  }

  return (
    <div className="space-y-4">
      {error && <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Upload className="h-5 w-5" /> Upload Source File
          </CardTitle>
          <CardDescription>Upload a file (e.g. markdown report) as a source to an existing notebook</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>Notebook</Label>
            <Select value={selectedNb} onValueChange={setSelectedNb}>
              <SelectTrigger><SelectValue placeholder="Select notebook" /></SelectTrigger>
              <SelectContent>
                {notebooks.map((nb) => <SelectItem key={nb.id} value={nb.id}>{nb.title}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>File Path (server-side)</Label>
            <Input
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              placeholder="e.g. data/Outputs/myreport/video.md"
            />
            <p className="text-xs text-muted-foreground">
              Path to the file on the server to upload as a notebook source.
            </p>
          </div>
          <div className="grid gap-2">
            <Label>Source Title (optional)</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Custom source title" />
          </div>
          <Button onClick={upload} disabled={uploading || !selectedNb || !filePath} className="gap-2">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploading ? 'Uploading...' : 'Upload Source'}
          </Button>
          {result && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <p className="font-medium">Upload Result</p>
              <pre className="mt-1 text-xs overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Retention Tab
// ---------------------------------------------------------------------------
function RetentionTab() {
  const [items, setItems] = useState<RetentionContent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dryRun, setDryRun] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<RetentionCleanupResult | null>(null)
  const [extendId, setExtendId] = useState<string | null>(null)
  const [extendHours, setExtendHours] = useState(48)

  const load = () => {
    api.listRetention()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const cleanup = async () => {
    setCleaning(true)
    try {
      const res = await api.cleanupRetention(dryRun, false)
      setCleanupResult(res)
      load()
    } catch (e) { setError((e as Error).message) }
    finally { setCleaning(false) }
  }

  const doExtend = async () => {
    if (!extendId) return
    try { await api.extendRetention(extendId, extendHours); setExtendId(null); load() }
    catch (e) { setError((e as Error).message) }
  }

  const makePermanent = async (id: string) => {
    try { await api.makePermanent(id); load() }
    catch (e) { setError((e as Error).message) }
  }

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">Loading retention data...</div>

  return (
    <div className="space-y-4">
      {error && <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-5 w-5" /> Cleanup Expired Content
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} className="rounded" />
            Dry run (preview only)
          </label>
          <Button onClick={cleanup} disabled={cleaning} className="gap-2">
            {cleaning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            {cleaning ? 'Cleaning...' : 'Run Cleanup'}
          </Button>
          {cleanupResult && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <pre className="text-xs overflow-x-auto">{JSON.stringify(cleanupResult, null, 2)}</pre>
            </div>
          )}
        </CardContent>
      </Card>

      {items.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">No tracked content.</CardContent></Card>
      ) : (
        <Card>
          <CardHeader><CardTitle className="text-base">Tracked Content ({items.length})</CardTitle></CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Notebook</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Permanent</th>
                    <th className="px-4 py-3 font-medium">Expires</th>
                    <th className="px-4 py-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-border last:border-0 hover:bg-accent/30">
                      <td className="px-4 py-3">
                        <p className="font-medium">{item.notebook_title || item.notebook_id}</p>
                        <p className="text-xs text-muted-foreground">{item.preset_name}</p>
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                      <td className="px-4 py-3">{item.is_permanent ? '✓' : '—'}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDate(item.expires_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          {!item.is_permanent && (
                            <>
                              <Button variant="ghost" size="sm" className="h-7" onClick={() => { setExtendId(item.id); setExtendHours(48) }}>
                                Extend
                              </Button>
                              <Button variant="ghost" size="sm" className="h-7" onClick={() => makePermanent(item.id)}>
                                Permanent
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Extend Dialog */}
      {extendId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={() => setExtendId(null)}>
          <div className="rounded-xl border border-border bg-card p-6 shadow-lg max-w-sm w-full" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold">Extend Retention</h3>
            <p className="text-sm text-muted-foreground mt-1">Set a new retention period in hours.</p>
            <div className="mt-4 grid gap-2">
              <Label>Hours</Label>
              <Input type="number" value={extendHours} onChange={(e) => setExtendHours(parseInt(e.target.value) || 48)} />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setExtendId(null)}>Cancel</Button>
              <Button onClick={doExtend}>Extend</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
