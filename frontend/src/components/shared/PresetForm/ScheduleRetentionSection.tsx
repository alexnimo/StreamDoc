import { CalendarClock, Clock } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { ScheduleInput } from '@/components/shared/ScheduleInput'
import type { Preset } from '@/lib/api'

interface ScheduleRetentionSectionProps {
  preset: Partial<Preset>
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

export function ScheduleRetentionSection({
  preset,
  update,
  disabled,
}: ScheduleRetentionSectionProps) {
  return (
    <>
      <div className="rounded-md border border-border p-3 space-y-2">
        <div className="flex items-center gap-1.5">
          <CalendarClock className="h-3.5 w-3.5 text-primary" />
          <Label className="text-xs font-medium">Schedule</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          When this preset should run automatically. This is the same schedule shown on the Scheduler page.
        </p>
        <ScheduleInput
          value={preset.schedule}
          onChange={(v) => update({ schedule: v })}
        />
      </div>

      <div className="rounded-md border border-border p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-primary" />
            <Label className="text-xs font-medium">Retention Policy</Label>
          </div>
          <Switch
            checked={preset.retention_enabled ?? true}
            onCheckedChange={(v) => update({ retention_enabled: v })}
            disabled={disabled}
          />
        </div>
        {preset.retention_enabled !== false ? (
          <>
            <p className="text-xs text-muted-foreground">
              How long generated files and NotebookLM notebooks are kept before permanent deletion. Default is 24 hours.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="file_retention_hours" className="text-xs">
                  File Retention (hours)
                </Label>
                <Input
                  id="file_retention_hours"
                  type="number"
                  min={0}
                  step={1}
                  value={formValue(preset.file_retention_hours)}
                  onChange={(e) =>
                    update({ file_retention_hours: parseNumber(e.target.value) })
                  }
                  placeholder="24"
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">
                  Report files (.md, .pdf) are deleted after this many hours.
                </p>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="notebook_retention_hours" className="text-xs">
                  Notebook Retention (hours)
                </Label>
                <Input
                  id="notebook_retention_hours"
                  type="number"
                  min={0}
                  step={1}
                  value={formValue(preset.notebook_retention_hours)}
                  onChange={(e) =>
                    update({ notebook_retention_hours: parseNumber(e.target.value) })
                  }
                  placeholder="24"
                  disabled={disabled}
                />
                <p className="text-xs text-muted-foreground">
                  NotebookLM notebooks are deleted after this many hours.
                </p>
              </div>
            </div>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Retention is disabled. Files and notebooks are kept indefinitely.
          </p>
        )}
      </div>
    </>
  )
}

function formValue(value: number | null | undefined): string | number {
  return value == null ? '' : value
}

function parseNumber(value: string): number | null {
  return value === '' ? null : parseFloat(value)
}
