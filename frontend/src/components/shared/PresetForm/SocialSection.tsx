import { MessageSquare } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { SocialSourcesInput, type SocialSourceEntry } from '@/components/shared/SocialSourcesInput'
import type { Preset } from '@/lib/api'

interface SocialSectionProps {
  preset: Partial<Preset>
  sources: SocialSourceEntry[]
  onSourcesChange: (sources: SocialSourceEntry[]) => void
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

export function SocialSection({
  preset,
  sources,
  onSourcesChange,
  update,
  disabled,
}: SocialSectionProps) {
  return (
    <div className="space-y-4">
      <SocialSourcesInput sources={sources} onChange={onSourcesChange} />

      <div className="rounded-md border border-border p-3 space-y-3">
        <div className="flex items-center gap-1.5">
          <MessageSquare className="h-3.5 w-3.5 text-primary" />
          <Label className="text-xs font-medium">Social Collection</Label>
        </div>
        <p className="text-xs text-muted-foreground">Settings that apply to all social sources.</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="social_lookback_hours" className="text-xs">
              Lookback Window (hours)
            </Label>
            <Input
              id="social_lookback_hours"
              type="number"
              min={1}
              value={formValue(preset.social_lookback_hours)}
              onChange={(e) =>
                update({ social_lookback_hours: parseIntOrNull(e.target.value) })
              }
              placeholder="24"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">Only collect posts published in the last N hours.</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="social_max_posts" className="text-xs">
              Default Max Posts
            </Label>
            <Input
              id="social_max_posts"
              type="number"
              min={1}
              value={formValue(preset.social_max_posts)}
              onChange={(e) =>
                update({ social_max_posts: parseIntOrNull(e.target.value) })
              }
              placeholder="500"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Leave blank to collect every post in the lookback window (recommended for high-volume lists).
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function formValue(value: number | null | undefined): string | number {
  return value == null ? '' : value
}

function parseIntOrNull(value: string): number | null {
  return value === '' ? null : parseInt(value, 10)
}
