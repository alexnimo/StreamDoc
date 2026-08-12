import { useState } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type ScheduleMode = 'interval' | 'daily' | 'cron' | 'off'

interface ScheduleInputProps {
  value: string | null | undefined
  onChange: (value: string | null) => void
}

/** Parse a schedule string into mode + params. */
function parseSchedule(raw: string | null | undefined): { mode: ScheduleMode; hours: number; minute: number; cronExpr: string } {
  const s = (raw || '').trim()
  if (!s) return { mode: 'off', hours: 12, minute: 0, cronExpr: '' }
  if (s.startsWith('interval:')) {
    const secs = parseInt(s.split('interval:', 2)[1]) || 0
    return { mode: 'interval', hours: Math.round(secs / 3600), minute: 0, cronExpr: '' }
  }
  if (s.startsWith('cron:')) {
    const expr = s.split('cron:', 2)[1].trim()
    const parts = expr.split(/\s+/)
    if (parts.length === 5 && parts[1] !== '*' && parts[0] !== '*' && parts[2] === '*' && parts[3] === '*' && parts[4] === '*') {
      return { mode: 'daily', hours: parseInt(parts[1]) || 0, minute: parseInt(parts[0]) || 0, cronExpr: '' }
    }
    return { mode: 'cron', hours: 12, minute: 0, cronExpr: expr }
  }
  return { mode: 'cron', hours: 12, minute: 0, cronExpr: s }
}

/** Build a schedule string from mode + params. */
function buildSchedule(mode: ScheduleMode, hours: number, minute: number, cronExpr: string): string | null {
  switch (mode) {
    case 'off':
      return null
    case 'interval':
      return `interval:${hours * 3600}`
    case 'daily':
      return `cron:${minute} ${hours} * * *`
    case 'cron':
      return cronExpr.trim() ? `cron:${cronExpr.trim()}` : null
  }
}

export function ScheduleInput({ value, onChange }: ScheduleInputProps) {
  const parsed = parseSchedule(value)
  const [mode, setMode] = useState<ScheduleMode>(parsed.mode)
  const [hours, setHours] = useState(parsed.hours)
  const [minute, setMinute] = useState(parsed.minute)
  const [cronExpr, setCronExpr] = useState(parsed.cronExpr)

  const update = (newMode: ScheduleMode, newHours: number, newMinute: number, newCron: string) => {
    onChange(buildSchedule(newMode, newHours, newMinute, newCron))
  }

  const handleModeChange = (m: ScheduleMode) => {
    setMode(m)
    update(m, hours, minute, cronExpr)
  }

  return (
    <div className="space-y-2">
      <Select value={mode} onValueChange={(v) => handleModeChange(v as ScheduleMode)}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="off">No schedule (manual only)</SelectItem>
          <SelectItem value="interval">Every N hours</SelectItem>
          <SelectItem value="daily">Daily at a specific time</SelectItem>
          <SelectItem value="cron">Custom cron (advanced)</SelectItem>
        </SelectContent>
      </Select>

      {mode === 'interval' && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Run every</span>
          <Input
            type="number"
            min={1}
            max={168}
            value={hours}
            onChange={(e) => {
              const h = e.target.value === '' ? 1 : parseInt(e.target.value) || 1
              setHours(h)
              update('interval', h, minute, cronExpr)
            }}
            className="w-20 h-8"
          />
          <span className="text-xs text-muted-foreground">hour(s)</span>
        </div>
      )}

      {mode === 'daily' && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Run at</span>
          <Input
            type="number"
            min={0}
            max={23}
            value={hours}
            onChange={(e) => {
              const h = e.target.value === '' ? 0 : parseInt(e.target.value) || 0
              setHours(h)
              update('daily', h, minute, cronExpr)
            }}
            className="w-16 h-8"
          />
          <span className="text-xs text-muted-foreground">:</span>
          <Input
            type="number"
            min={0}
            max={59}
            value={minute}
            onChange={(e) => {
              const m = e.target.value === '' ? 0 : parseInt(e.target.value) || 0
              setMinute(m)
              update('daily', hours, m, cronExpr)
            }}
            className="w-16 h-8"
          />
          <span className="text-xs text-muted-foreground">(24h, UTC)</span>
        </div>
      )}

      {mode === 'cron' && (
        <div className="space-y-1">
          <Input
            value={cronExpr}
            onChange={(e) => {
              setCronExpr(e.target.value)
              update('cron', hours, minute, e.target.value)
            }}
            placeholder="0 */6 * * *"
            className="font-mono text-xs h-8"
          />
          <p className="text-xs text-muted-foreground">
            Standard 5-field cron: minute hour day month day-of-week
          </p>
        </div>
      )}

      {mode !== 'off' && (
        <p className="text-xs text-muted-foreground">
          Result: <code className="rounded bg-muted px-1 font-mono">{buildSchedule(mode, hours, minute, cronExpr)}</code>
        </p>
      )}
    </div>
  )
}
