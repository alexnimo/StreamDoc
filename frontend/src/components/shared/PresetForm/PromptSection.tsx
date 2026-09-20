import { useEffect, useState } from 'react'
import { MessageSquare, FileText, Palette } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Preset, PromptTemplate } from '@/lib/api'

type ActiveBackend = '__none__' | 'notebooklm' | 'agy'

interface PromptSectionProps {
  preset: Partial<Preset>
  activeBackend: ActiveBackend
  promptTemplates: PromptTemplate[]
  selectedTemplateName: string | null | undefined
  isTemplateLocked: boolean
  templatePreview: string | null
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

export function PromptSection({
  preset,
  activeBackend,
  promptTemplates,
  selectedTemplateName,
  isTemplateLocked,
  templatePreview,
  update,
  disabled,
}: PromptSectionProps) {
  const handleTemplateChange = (value: string) => {
    if (value === '__manual__') {
      if (activeBackend === 'agy') {
        update({ agy_prompt_template: null })
      } else {
        update({ notebooklm_prompt_template: null })
      }
    } else if (activeBackend === 'agy') {
      update({ agy_prompt_template: value })
    } else {
      update({ notebooklm_prompt_template: value })
    }
  }

  const placeholder =
    activeBackend === 'agy'
      ? 'Custom instructions sent to Antigravity and embedded in the report header...'
      : activeBackend === 'notebooklm'
        ? 'Custom instructions sent to NotebookLM and embedded in the report header...'
        : 'Custom instructions embedded in the report header...'

  const designTemplates = promptTemplates.filter((t) => t.template_kind === 'design')
  // Reason: OFF means the field is null/absent; local state lets the switch stay ON
  // even before a template is selected (e.g. to show the empty-list hint).
  const [designEnabled, setDesignEnabled] = useState(preset.design_prompt_template != null)
  useEffect(() => {
    setDesignEnabled(preset.design_prompt_template != null)
  }, [preset.design_prompt_template])
  const selectedDesignTemplate = designTemplates.find(
    (t) => t.name === preset.design_prompt_template,
  )

  const handleDesignToggle = (enabled: boolean) => {
    setDesignEnabled(enabled)
    if (!enabled) {
      // Reason: write an explicit null so a stale template name is never left on the preset.
      update({ design_prompt_template: null })
    }
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-3">
      <div className="flex items-center gap-1.5">
        <MessageSquare className="h-3.5 w-3.5 text-primary" />
        <Label className="text-xs font-medium">Generation Prompt</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Choose the prompt that will be used for the report header and for the selected generation backend.
      </p>

      <div className="grid gap-1.5">
        <Label className="text-xs">Prompt Source</Label>
        <Select
          value={selectedTemplateName || '__manual__'}
          onValueChange={handleTemplateChange}
          disabled={disabled}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select a prompt" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__manual__">Use custom prompt</SelectItem>
            {promptTemplates.map((template) => (
              <SelectItem key={template.name} value={template.name}>
                {template.name}
                {template.description ? ` — ${template.description}` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {isTemplateLocked
            ? 'Using a saved prompt template. The prompt is loaded from the template at runtime.'
            : 'Using a custom prompt. Type your instructions below.'}
        </p>
      </div>

      {isTemplateLocked && (
        <div className="grid gap-1.5">
          <Label className="text-xs">Template Preview</Label>
          <Textarea
            value={templatePreview || ''}
            rows={4}
            readOnly
            placeholder="Template prompt will appear here..."
            className="bg-muted/50 cursor-not-allowed"
          />
          <p className="text-xs text-muted-foreground">
            This is a read-only preview of the selected template. Edit it on the Prompts page.
          </p>
        </div>
      )}

      {!isTemplateLocked && (
        <div className="grid gap-1.5">
          <Label htmlFor="prompt_md" className="text-xs flex items-center gap-1.5">
            <FileText className="h-3 w-3" />
            Custom Prompt / Instructions (Markdown)
          </Label>
          <Textarea
            id="prompt_md"
            value={preset.prompt_md || ''}
            onChange={(e) => update({ prompt_md: e.target.value })}
            rows={4}
            placeholder={placeholder}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            {activeBackend === 'agy'
              ? 'This text is sent to Antigravity and included in the report header.'
              : activeBackend === 'notebooklm'
                ? 'This text is sent to NotebookLM as the generation prompt and included in the report header.'
                : 'This text is included in the report header.'}
          </p>
        </div>
      )}

      <div className="grid gap-1.5 border-t border-border pt-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Palette className="h-3.5 w-3.5 text-primary" />
            <Label className="text-xs font-medium">Design Prompt (optional)</Label>
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="design-template-enabled" className="text-xs text-muted-foreground">
              Enable design template
            </Label>
            <Switch
              id="design-template-enabled"
              checked={designEnabled}
              onCheckedChange={handleDesignToggle}
              disabled={disabled}
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Apply a design template that controls how the generated output looks — layout, styling, and visual structure.
        </p>

        {designEnabled && designTemplates.length === 0 && (
          <p className="text-xs text-muted-foreground">Create design templates on the Prompts page</p>
        )}

        {designEnabled && designTemplates.length > 0 && (
          <div className="grid gap-1.5">
            <Label className="text-xs">Design Template</Label>
            <Select
              value={preset.design_prompt_template || undefined}
              onValueChange={(v) => update({ design_prompt_template: v })}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a design template" />
              </SelectTrigger>
              <SelectContent>
                {designTemplates.map((template) => (
                  <SelectItem key={template.name} value={template.name}>
                    {template.name}
                    {template.description ? ` — ${template.description}` : ''}
                  </SelectItem>
                ))}
                {preset.design_prompt_template && !selectedDesignTemplate && (
                  <SelectItem value={preset.design_prompt_template}>
                    {preset.design_prompt_template} — template not found
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
        )}

        {designEnabled && selectedDesignTemplate && (
          <div className="grid gap-1.5">
            <Label className="text-xs">Design Template Preview</Label>
            <Textarea
              value={selectedDesignTemplate.prompt}
              rows={4}
              readOnly
              className="bg-muted/50 cursor-not-allowed"
            />
            <p className="text-xs text-muted-foreground">
              This is a read-only preview of the selected design template. Edit it on the Prompts page.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
