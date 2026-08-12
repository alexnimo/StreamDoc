import { Presentation, Loader2, Info, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api, type Preset, type AgySkillInfo, type AgyReportFile } from '@/lib/api'

type ActiveBackend = '__none__' | 'notebooklm' | 'agy'

interface BackendSectionProps {
  preset: Partial<Preset>
  activeBackend: ActiveBackend
  agySkills: AgySkillInfo[]
  agyModels: string[]
  loadingAgySkills: boolean
  agySkillsError: string | null
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

function parseOutputs(outputs?: string | null): string[] {
  return (outputs || '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
}

export function BackendSection({
  preset,
  activeBackend,
  agySkills,
  agyModels,
  loadingAgySkills,
  agySkillsError,
  update,
  disabled,
}: BackendSectionProps) {
  const [availableReports, setAvailableReports] = useState<AgyReportFile[]>([])
  const [loadingReports, setLoadingReports] = useState(false)
  const [reportsError, setReportsError] = useState<string | null>(null)
  const [reportsLoaded, setReportsLoaded] = useState(false)

  // Reason: load the available report files for this preset once when the
  // agy backend is active and the preset has a name, so the operator can
  // pick an existing report instead of regenerating one each run.
  const loadReports = () => {
    if (reportsLoaded || !preset.name) return
    setReportsLoaded(true)
    setLoadingReports(true)
    setReportsError(null)
    api.agy
      .listPresetReports(preset.name)
      .then(setAvailableReports)
      .catch((e) => {
        setReportsError((e as Error).message)
        setAvailableReports([])
      })
      .finally(() => setLoadingReports(false))
  }

  const setBackend = (backend: ActiveBackend) => {
    const current = parseOutputs(preset.outputs)
    const base = current.filter((f) => f !== 'notebooklm' && f !== 'agy')
    const next = [...base]
    if (backend !== '__none__') next.push(backend)

    const patch: Partial<Preset> = {
      outputs: next.join(','),
      agy_enabled: backend === 'agy',
    }

    const sourceTemplate = activeBackend === 'agy' ? preset.agy_prompt_template : preset.notebooklm_prompt_template
    if (backend === 'notebooklm' && sourceTemplate && !preset.notebooklm_prompt_template) {
      patch.notebooklm_prompt_template = sourceTemplate
    }
    if (backend === 'agy' && sourceTemplate && !preset.agy_prompt_template) {
      patch.agy_prompt_template = sourceTemplate
    }

    update(patch)
  }

  const handleModelChange = (value: string) => {
    update({ agy_model: value === '__default__' ? null : value })
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-3">
      <div className="flex items-center gap-1.5">
        <Presentation className="h-3.5 w-3.5 text-primary" />
        <Label className="text-xs font-medium">Generation Backend</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Choose which service generates enhanced content from your reports.
      </p>

      <div className="grid gap-1.5">
        <Label className="text-xs">Backend</Label>
        <Select value={activeBackend} onValueChange={(v) => setBackend(v as ActiveBackend)} disabled={disabled}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">None (PDF + Markdown only)</SelectItem>
            <SelectItem value="notebooklm">NotebookLM</SelectItem>
            <SelectItem value="agy">Antigravity</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {activeBackend === 'notebooklm' && (
        <>
          <div className="grid gap-1.5">
            <Label className="text-xs">NotebookLM Content Type</Label>
            <Select
              value={preset.notebooklm_kind || 'slide_deck'}
              onValueChange={(v) => update({ notebooklm_kind: v })}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="slide_deck">Slide Deck</SelectItem>
                <SelectItem value="podcast">Podcast</SelectItem>
                <SelectItem value="infographic">Infographic</SelectItem>
                <SelectItem value="report">Report</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              The type of content NotebookLM should generate from the uploaded report.
            </p>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label className="text-xs">Retry on failure</Label>
              <p className="text-xs text-muted-foreground mt-0.5">
                Automatically resubmit a failed NotebookLM generation.
              </p>
            </div>
            <Switch
              checked={preset.notebooklm_retry_failed ?? true}
              onCheckedChange={(v) => update({ notebooklm_retry_failed: v })}
              disabled={disabled}
            />
          </div>

          {preset.notebooklm_retry_failed !== false && (
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="notebooklm_retry_attempts" className="text-xs">
                  Retry attempts
                </Label>
                <Input
                  id="notebooklm_retry_attempts"
                  type="number"
                  min={1}
                  max={5}
                  value={preset.notebooklm_retry_attempts ?? 1}
                  onChange={(e) =>
                    update({ notebooklm_retry_attempts: parseInt(e.target.value, 10) || 1 })
                  }
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">How many times to retry</p>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="notebooklm_retry_delay_minutes" className="text-xs">
                  Retry delay (minutes)
                </Label>
                <Input
                  id="notebooklm_retry_delay_minutes"
                  type="number"
                  min={1}
                  max={60}
                  step={0.5}
                  value={preset.notebooklm_retry_delay_minutes ?? 5}
                  onChange={(e) =>
                    update({ notebooklm_retry_delay_minutes: parseFloat(e.target.value) || 5 })
                  }
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">Wait time between retries</p>
              </div>
            </div>
          )}
        </>
      )}

      {activeBackend === 'agy' && (
        <>
          <div className="grid gap-1.5">
            <Label className="text-xs">Skill</Label>
            {loadingAgySkills ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading skills...
              </div>
            ) : agySkillsError ? (
              <>
                <Select disabled>
                  <SelectTrigger>
                    <SelectValue placeholder="Could not load skills" />
                  </SelectTrigger>
                </Select>
                <p className="text-xs text-destructive">{agySkillsError}</p>
              </>
            ) : agySkills.length === 0 ? (
              <div className="flex items-start gap-2 rounded-md bg-secondary/50 p-2.5 text-xs text-muted-foreground">
                <Info className="h-3.5 w-3.5 shrink-0 text-primary mt-0.5" />
                <span>
                  No Antigravity skills are installed. Install skills on the{' '}
                  <Link to="/antigravity" className="text-primary underline hover:text-primary/80">
                    Antigravity page
                  </Link>
                  .
                </span>
              </div>
            ) : (
              <>
                <Select
                  value={preset.agy_skill || ''}
                  onValueChange={(v) => update({ agy_skill: v || null })}
                  disabled={disabled}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a skill" />
                  </SelectTrigger>
                  <SelectContent>
                    {agySkills.map((skill) => (
                      <SelectItem key={skill.name} value={skill.name}>
                        {skill.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  The Antigravity skill to use for content generation.
                </p>
              </>
            )}
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs">Model</Label>
            <Select
              value={preset.agy_model || '__default__'}
              onValueChange={handleModelChange}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">Default</SelectItem>
                {agyModels.map((model) => (
                  <SelectItem key={model} value={model}>
                    {model}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">The LLM model to use for generation.</p>
          </div>

          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Use an existing report</Label>
              <button
                type="button"
                onClick={loadReports}
                disabled={disabled || loadingReports || !preset.name}
                className="text-xs text-primary underline hover:text-primary/80 disabled:opacity-50"
              >
                {loadingReports ? 'Loading…' : 'Refresh list'}
              </button>
            </div>
            <Select
              value={preset.agy_existing_report || '__none__'}
              onValueChange={(v) =>
                update({ agy_existing_report: v === '__none__' ? null : v })
              }
              disabled={disabled || !preset.name}
              onOpenChange={(open) => {
                if (open) loadReports()
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Generate a new report each run" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">Generate a new report each run</SelectItem>
                {availableReports.map((r) => (
                  <SelectItem key={r.path} value={r.path}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {preset.name
                ? 'Send a pre-existing report file to agy instead of generating a new one. Good for testing the pipeline without re-running fetch.'
                : 'Save the preset first to enable picking an existing report.'}
            </p>
            {reportsError && (
              <p className="text-xs text-destructive">{reportsError}</p>
            )}
            {preset.agy_existing_report && (
              <div className="flex items-start gap-2 rounded-md bg-secondary/50 p-2 text-xs text-muted-foreground">
                <FileText className="h-3.5 w-3.5 shrink-0 text-primary mt-0.5" />
                <span className="break-all">{preset.agy_existing_report}</span>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label className="text-xs">Publish to here.now</Label>
              <p className="text-xs text-muted-foreground mt-0.5">
                Publishes generated HTML to here.now and returns a public link in the job report.
              </p>
            </div>
            <Switch
              checked={preset.agy_publish_herenow ?? false}
              onCheckedChange={(v) => update({ agy_publish_herenow: v })}
              disabled={disabled}
            />
          </div>
        </>
      )}
    </div>
  )
}
