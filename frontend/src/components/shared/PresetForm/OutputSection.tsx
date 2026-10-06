import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import type { Preset } from '@/lib/api'

interface OutputSectionProps {
  preset: Partial<Preset>
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

const FORMATS = ['pdf', 'markdown'] as const

function parseOutputs(outputs?: string | null): string[] {
  return (outputs || '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
}

export function OutputSection({ preset, update, disabled }: OutputSectionProps) {
  const current = parseOutputs(preset.outputs)

  const toggleFormat = (format: (typeof FORMATS)[number]) => {
    const selected = current.includes(format)
    const next = selected
      ? current.filter((f) => f !== format)
      : [...current, format]
    update({ outputs: next.join(',') })
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <Label className="text-xs font-medium">Output Formats</Label>
      <p className="text-xs text-muted-foreground">
        Which file formats to generate. Markdown is the input format for CLI/agent
        backends (Antigravity reads it directly, including image file paths); PDF is
        mainly for web tools like NotebookLM and human reading.
      </p>
      <div className="flex flex-wrap gap-4 pt-0.5">
        {FORMATS.map((format) => (
          <label
            key={format}
            className="flex items-center gap-1.5 text-xs cursor-pointer"
          >
            <Checkbox
              checked={current.includes(format)}
              onCheckedChange={() => toggleFormat(format)}
              disabled={disabled}
            />
            <span className="capitalize">{format}</span>
          </label>
        ))}
      </div>
      {current.includes('agy') && !current.includes('markdown') && (
        <p className="text-xs text-amber-600">
          Antigravity is enabled but Markdown is off — the backend will fall back
          to PDF, which requires slower text extraction and burns extra tokens.
        </p>
      )}
    </div>
  )
}
