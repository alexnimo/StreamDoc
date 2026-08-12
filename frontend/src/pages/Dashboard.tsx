import { useEffect, useState } from 'react'
import { Zap, Briefcase, Video, BookOpen, ArrowRight, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type DashboardStats } from '@/lib/api'
import { StatCard } from '@/components/shared/StatCard'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ReportCard } from '@/components/shared/ReportCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { timeAgo } from '@/lib/utils'

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getStats()
      .then((data) => { setStats(data); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-pulse text-muted-foreground">Loading dashboard...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <p className="text-destructive text-sm">{error}</p>
        <Button onClick={() => window.location.reload()}>Retry</Button>
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="space-y-6">
      <div className="hero-gradient rounded-lg p-4">
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Overview of your StreamDoc pipeline</p>
      </div>

      {/* Stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Presets"
          value={stats.total_presets}
          description={`${stats.active_presets} active`}
          icon={Zap}
        />
        <StatCard
          label="Jobs (24h)"
          value={stats.jobs_24h}
          description={`${stats.jobs_completed} completed, ${stats.jobs_failed} failed`}
          icon={Briefcase}
        />
        <StatCard
          label="Videos Processed"
          value={stats.videos_processed}
          icon={Video}
        />
        <StatCard
          label="NotebookLM"
          value={stats.notebooklm_notebooks}
          description={stats.notebooklm_enabled ? 'Enabled' : 'Disabled'}
          icon={BookOpen}
        />
      </div>

      {/* Recent Reports */}
      {stats.recent_reports.length > 0 && (
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Recent Reports</CardTitle>
            <Link to="/jobs">
              <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs">
                View all <ArrowRight className="h-3 w-3" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid gap-2.5 md:grid-cols-2">
              {stats.recent_reports.slice(0, 6).map((report) => (
                <ReportCard key={report.video_id} report={report} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Activity */}
      <Card>
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="text-sm">Recent Activity</CardTitle>
          <Link to="/jobs">
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs">
              View all <ArrowRight className="h-3 w-3" />
            </Button>
          </Link>
        </CardHeader>
        <CardContent className="pt-0">
          {stats.recent_jobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <FileText className="h-6 w-6 text-muted-foreground/40" />
              <p className="text-xs text-muted-foreground">
                No recent jobs. Run a preset to get started.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {stats.recent_jobs.map((job) => (
                <div
                  key={job.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 transition-colors hover:bg-accent/30"
                >
                  <div className="flex items-center gap-2.5">
                    <StatusBadge status={job.status} />
                    <div>
                      <p className="text-xs font-medium">{job.preset_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {job.artifact_count} artifacts · {timeAgo(job.created_at)}
                      </p>
                    </div>
                  </div>
                  {job.errors.length > 0 && (
                    <span className="text-xs text-destructive">
                      {job.errors.length} error(s)
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
