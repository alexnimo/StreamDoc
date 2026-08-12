import { useEffect, useState, useCallback, useMemo } from 'react'
import { FileText, Loader2, Search, Layers } from 'lucide-react'
import { api, type ReportSummary, type Preset } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ReportCard } from '@/components/shared/ReportCard'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export default function Reports() {
  const [reports, setReports] = useState<ReportSummary[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [presetFilter, setPresetFilter] = useState<string>('all')
  const [search, setSearch] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    const presetParam = presetFilter !== 'all' ? presetFilter : undefined
    Promise.all([
      api.listReports(presetParam, 100),
      api.listPresets(),
    ])
      .then(([r, p]) => { setReports(r); setPresets(p); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [presetFilter])

  useEffect(() => { load() }, [load])

  const filtered = reports.filter((r) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      r.title?.toLowerCase().includes(q) ||
      r.video_id?.toLowerCase().includes(q) ||
      r.channel_title?.toLowerCase().includes(q)
    )
  })

  // Reason: group reports by job_id so reports from the same preset run
  // are stacked together. Reports without a job_id get their own group.
  const grouped = useMemo(() => {
    const groups: Record<string, ReportSummary[]> = {}
    for (const r of filtered) {
      const key = r.job_id || `solo-${r.video_id}`
      if (!groups[key]) groups[key] = []
      groups[key].push(r)
    }
    // Reason: sort groups by the most recent report in each group
    return Object.entries(groups)
      .sort(([, a], [, b]) => {
        const aTime = a[0]?.created_at || ''
        const bTime = b[0]?.created_at || ''
        return bTime.localeCompare(aTime)
      })
      .map(([key, items]) => ({ key, items }))
  }, [filtered])

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Reports</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Browse all processed video reports</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <Select value={presetFilter} onValueChange={setPresetFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All presets" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All presets</SelectItem>
            {presets.map((p) => (
              <SelectItem key={p.id} value={p.name}>{p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title or video ID..."
            className="pl-8"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2.5 text-xs text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileText className="h-4 w-4" />
            Reports ({filtered.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-12">
              No reports found. Run a preset to generate reports.
            </p>
          ) : (
            <div className="space-y-4">
              {grouped.map(({ key, items }) => (
                <div key={key}>
                  {items.length > 1 && (
                    <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                      <Layers className="h-3.5 w-3.5" />
                      {items[0].preset_name || 'Unknown preset'} — {items.length} reports
                    </div>
                  )}
                  <div className={items.length > 1 ? "grid gap-2.5 sm:grid-cols-2" : "grid gap-2.5 sm:grid-cols-2"}>
                    {items.map((report) => (
                      <ReportCard key={report.video_id} report={report} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
