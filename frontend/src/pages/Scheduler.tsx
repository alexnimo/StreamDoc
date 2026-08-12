import { useEffect, useState, useCallback } from 'react'
import { Calendar, Plus, Trash2, Play, Loader2 } from 'lucide-react'
import { api, type ScheduledJob, type Preset } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ScheduleInput } from '@/components/shared/ScheduleInput'
import { describeSchedule } from '@/lib/schedule'

export default function Scheduler() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [newPreset, setNewPreset] = useState('')
  const [newSchedule, setNewSchedule] = useState('')
  const [adding, setAdding] = useState(false)
  const [runningId, setRunningId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([api.listScheduledJobs(), api.listPresets()])
      .then(([sj, ps]) => { setJobs(sj); setPresets(ps); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // Reason: presets that already have a schedule appear in the jobs list, so
  // the "Add Schedule" dialog only offers presets that are not yet scheduled.
  // This keeps the two surfaces in sync and prevents duplicate entries.
  const scheduledPresetIds = new Set(jobs.map((j) => j.preset))
  const unscheduledPresets = presets.filter((p) => !scheduledPresetIds.has(p.id))

  const addJob = async () => {
    if (!newPreset || !newSchedule) return
    setAdding(true)
    try {
      await api.addScheduledJob(newPreset, newSchedule)
      setAddOpen(false)
      setNewPreset('')
      setNewSchedule('')
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setAdding(false)
    }
  }

  const removeJob = async (preset: string) => {
    try {
      await api.removeScheduledJob(preset)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const runOnce = async (preset: string) => {
    setRunningId(preset)
    try {
      await api.runOnce(preset)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunningId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Scheduler</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Automated preset schedules — synced with each preset's schedule field
          </p>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)} disabled={unscheduledPresets.length === 0}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          Add Schedule
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2.5 text-xs text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Calendar className="h-4 w-4" />
            Scheduled Jobs ({jobs.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No scheduled presets. Set a schedule on a preset (here or in the
              Presets page) to automate runs.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Preset</th>
                    <th className="px-3 py-2 font-medium">Schedule</th>
                    <th className="px-3 py-2 font-medium">Trigger</th>
                    <th className="px-3 py-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id} className="border-b border-border last:border-0 hover:bg-accent/30">
                      <td className="px-3 py-2.5 font-medium">{job.preset}</td>
                      <td className="px-3 py-2.5">{describeSchedule(job.schedule)}</td>
                      <td className="px-3 py-2.5"><StatusBadge status={job.trigger} /></td>
                      <td className="px-3 py-2.5">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Run once"
                            disabled={runningId === job.preset}
                            onClick={() => runOnce(job.preset)}
                          >
                            {runningId === job.preset ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Play className="h-3 w-3" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Remove"
                            onClick={() => removeJob(job.preset)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Scheduled Job</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label className="text-xs">Preset</Label>
              <Select value={newPreset} onValueChange={setNewPreset}>
                <SelectTrigger><SelectValue placeholder="Select a preset" /></SelectTrigger>
                <SelectContent>
                  {unscheduledPresets.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">Schedule</Label>
              <ScheduleInput
                value={newSchedule || null}
                onChange={(v) => setNewSchedule(v || '')}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={addJob} disabled={adding || !newPreset || !newSchedule}>
              {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
