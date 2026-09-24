import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, Copy, FileText, Check } from 'lucide-react'
import { api, type PromptTemplate } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'

const emptyPrompt: Partial<PromptTemplate> = {
  name: '',
  description: '',
  target_types: ['slide_deck', 'infographic'],
  prompt: '',
  variables: {},
  template_kind: 'content',
}

const contentTypeOptions = [
  { value: 'slide_deck', label: 'Slide Deck' },
  { value: 'podcast', label: 'Podcast' },
  { value: 'infographic', label: 'Infographic' },
  { value: 'report', label: 'Report' },
  { value: 'interactive_dashboard', label: 'Interactive Dashboard' },
]

const templateKindOptions: { value: 'content' | 'design'; label: string }[] = [
  { value: 'content', label: 'Content' },
  { value: 'design', label: 'Design' },
]

export default function Prompts() {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<PromptTemplate | null>(null)
  const [form, setForm] = useState<Partial<PromptTemplate>>(emptyPrompt)
  const [deleteName, setDeleteName] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [copiedName, setCopiedName] = useState<string | null>(null)

  const load = () => {
    api.listPrompts()
      .then(setPrompts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(emptyPrompt)
    setDialogOpen(true)
  }

  const openEdit = (p: PromptTemplate) => {
    setEditing(p)
    // Reason: older templates may lack template_kind; normalize so the update payload always sends the existing kind.
    setForm({ ...p, template_kind: p.template_kind || 'content' })
    setDialogOpen(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      if (editing) {
        await api.updatePrompt(editing.name, form)
      } else {
        await api.createPrompt(form as PromptTemplate)
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
    if (!deleteName) return
    try {
      await api.deletePrompt(deleteName)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const copyPrompt = async (p: PromptTemplate) => {
    try {
      await navigator.clipboard.writeText(p.prompt)
      setCopiedName(p.name)
      setTimeout(() => setCopiedName(null), 2000)
    } catch {
      // ignore
    }
  }

  const toggleTargetType = (type: string) => {
    const current = form.target_types || []
    if (current.includes(type)) {
      setForm((f) => ({ ...f, target_types: current.filter((t) => t !== type) }))
    } else {
      setForm((f) => ({ ...f, target_types: [...current, type] }))
    }
  }

  // Reason: templates without a kind are legacy "content" templates (server defaults missing kind to "content").
  const contentTemplates = prompts.filter((p) => p.template_kind !== 'design')
  const designTemplates = prompts.filter((p) => p.template_kind === 'design')

  const renderTemplateCard = (p: PromptTemplate) => (
    <Card key={p.name} className="hover:shadow-md transition-shadow">
      <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-sm">{p.name}</CardTitle>
        <div className="flex shrink-0 gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => copyPrompt(p)}
            title="Copy prompt text"
          >
            {copiedName === p.name ? (
              <Check className="h-3.5 w-3.5 text-primary" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(p)}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleteName(p.name)}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        <p className="text-xs text-muted-foreground">{p.description}</p>
        <div className="flex flex-wrap gap-1">
          {p.target_types.map((t) => (
            <span
              key={t}
              className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary"
            >
              {t.replace('_', ' ')}
            </span>
          ))}
        </div>
        <div className="rounded-md bg-muted/50 p-2.5">
          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
            {p.prompt.slice(0, 500)}
            {p.prompt.length > 500 && '...'}
          </pre>
        </div>
        {Object.keys(p.variables).length > 0 && (
          <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
            <span>Variables:</span>
            {Object.keys(p.variables).map((v) => (
              <span key={v} className="font-mono text-primary">
                {`{${v}}`}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )

  const renderSection = (
    title: string,
    description: string,
    templates: PromptTemplate[],
    emptyMessage: string,
  ) => (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {templates.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <FileText className="mx-auto mb-2 h-6 w-6 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">{emptyMessage}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {templates.map(renderTemplateCard)}
        </div>
      )}
    </section>
  )

  if (loading) {
    return <div className="animate-pulse py-20 text-center text-muted-foreground text-sm">Loading prompts...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Prompt Templates</h1>
          <p className="text-sm text-muted-foreground">Create and manage prompts for NotebookLM content generation</p>
        </div>
        <Button onClick={openCreate} size="sm" className="gap-1.5">
          <Plus className="h-3.5 w-3.5" /> New Template
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
          {error}
        </div>
      )}

      {renderSection(
        'Content Templates',
        'Prompts that define what content to generate and how to structure it.',
        contentTemplates,
        'No content templates yet.',
      )}
      {renderSection(
        'Design Templates',
        'Design templates describe how the output looks — visual style and layout instructions — not what to extract.',
        designTemplates,
        'No design templates yet.',
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-base">{editing ? 'Edit Template' : 'Create Template'}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label htmlFor="prompt-name" className="text-xs">Name</Label>
              <Input
                id="prompt-name"
                value={form.name || ''}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                disabled={!!editing}
                placeholder="e.g. financial_analysis"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="prompt-desc" className="text-xs">Description</Label>
              <Input
                id="prompt-desc"
                value={form.description || ''}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="What this prompt does..."
              />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">Template Kind</Label>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Template kind">
                {templateKindOptions.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={!!editing}
                    onClick={() => setForm((f) => ({ ...f, template_kind: opt.value }))}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                      (form.template_kind || 'content') === opt.value
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {editing
                  ? 'Template kind cannot be changed after creation.'
                  : 'Content prompts define what to generate; design prompts define how the output looks.'}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">Target Content Types</Label>
              <div className="flex flex-wrap gap-2">
                {contentTypeOptions.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleTargetType(opt.value)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                      (form.target_types || []).includes(opt.value)
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {(form.template_kind || 'content') === 'design'
                  ? 'Design templates render against every content type — these are informational tags only.'
                  : 'Content templates must list every content type they support — rendering is gated to these.'}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="prompt-text" className="text-xs">Prompt Text</Label>
              <Textarea
                id="prompt-text"
                value={form.prompt || ''}
                onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                rows={6}
                placeholder="Analyze this content and create a {content_type} that..."
              />
              <p className="text-xs text-muted-foreground">
                Use {`{content_type}`} and other variables with {`{variable_name}`} syntax.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving || !form.name} size="sm">
              {saving ? 'Saving...' : editing ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteName !== null}
        onOpenChange={(v) => !v && setDeleteName(null)}
        title="Delete Prompt"
        description="Are you sure you want to delete this prompt template?"
        confirmText="Delete"
        destructive
        onConfirm={confirmDelete}
      />
    </div>
  )
}
