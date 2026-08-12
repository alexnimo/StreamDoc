import { useState } from 'react'
import { ChevronDown, FileText, Image, Clock, Type, Download, ExternalLink, Presentation, Loader2, AlertCircle, Rocket, File } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn, timeAgo } from '@/lib/utils'
import type { ReportSummary, ReportDetail } from '@/lib/api'
import { api } from '@/lib/api'

interface ReportCardProps {
  report: ReportSummary
}

export function ReportCard({ report }: ReportCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [loading, setLoading] = useState(false)

  const toggleExpand = async () => {
    if (!expanded && !detail) {
      setLoading(true)
      try {
        const d = await api.getReport(report.video_id)
        setDetail(d)
      } catch {
        // ignore
      } finally {
        setLoading(false)
      }
    }
    setExpanded(!expanded)
  }

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-md">
      <div className="flex gap-0">
        {/* Thumbnail */}
        <div
          className="group relative h-24 w-32 shrink-0 cursor-pointer overflow-hidden bg-muted"
          onClick={toggleExpand}
        >
          {report.thumbnail_path ? (
            <img
              src={report.thumbnail_path}
              alt={report.title}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <Image className="h-6 w-6 text-muted-foreground/40" />
            </div>
          )}
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20">
            <ChevronDown
              className={cn(
                'h-5 w-5 text-white opacity-0 transition-all',
                expanded && 'rotate-180 opacity-100',
                'group-hover:opacity-100',
              )}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex min-w-0 flex-1 flex-col p-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 text-sm font-medium leading-snug" onClick={toggleExpand}>
              {report.title || report.video_id}
            </h3>
            <div className="flex shrink-0 gap-1">
              {report.has_pdf && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  asChild
                >
                  <a href={api.downloadReport(report.video_id, 'pdf')} download>
                    <Download className="h-3 w-3" />
                  </a>
                </Button>
              )}
            </div>
          </div>

          {/* Meta row */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            {report.duration_seconds && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {Math.floor(report.duration_seconds / 60)}m
              </span>
            )}
            {report.frame_count > 0 && (
              <span className="flex items-center gap-1">
                <Image className="h-3 w-3" />
                {report.frame_count} frames
              </span>
            )}
            {report.transcript_word_count > 0 && (
              <span className="flex items-center gap-1">
                <Type className="h-3 w-3" />
                {report.transcript_word_count.toLocaleString()} words
              </span>
            )}
            <span>{timeAgo(report.created_at)}</span>
          </div>

          {/* Format badges */}
          <div className="mt-1.5 flex gap-1.5">
            {report.has_pdf && (
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                PDF
              </span>
            )}
            {report.has_markdown && (
              <span className="rounded bg-secondary px-1.5 py-0.5 text-xs font-medium text-secondary-foreground">
                MD
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Expandable detail */}
      {expanded && (
        <div className="expand-transition border-t border-border">
          {loading ? (
            <div className="p-4 text-center text-xs text-muted-foreground animate-pulse">
              Loading details...
            </div>
          ) : detail ? (
            <div className="space-y-3 p-3">
              {/* Markdown preview */}
              {detail.markdown_content && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <FileText className="h-3 w-3" />
                    Report Content
                  </div>
                  <div className="max-h-48 overflow-y-auto rounded-md bg-muted/50 p-2.5">
                    <pre className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                      {detail.markdown_content.slice(0, 2000)}
                      {detail.markdown_content.length > 2000 && '...'}
                    </pre>
                  </div>
                </div>
              )}

              {/* Frame gallery */}
              {detail.frame_paths.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Image className="h-3 w-3" />
                    Extracted Frames ({detail.frame_paths.length})
                  </div>
                  <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6">
                    {detail.frame_paths.slice(0, 12).map((fp, i) => (
                      <div
                        key={i}
                        className="aspect-video overflow-hidden rounded bg-muted"
                      >
                        <img
                          src={fp}
                          alt={`Frame ${i + 1}`}
                          className="h-full w-full object-cover"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Download buttons */}
              <div className="flex gap-2">
                {detail.has_pdf && (
                  <Button variant="outline" size="sm" asChild>
                    <a href={api.downloadReport(report.video_id, 'pdf')} download>
                      <Download className="mr-1.5 h-3 w-3" />
                      Download PDF
                    </a>
                  </Button>
                )}
                {detail.has_markdown && (
                  <Button variant="outline" size="sm" asChild>
                    <a href={api.downloadReport(report.video_id, 'markdown')} download>
                      <Download className="mr-1.5 h-3 w-3" />
                      Download Markdown
                    </a>
                  </Button>
                )}
              </div>

              {/* NotebookLM generated content */}
              {(detail.notebooklm_url || (detail.notebooklm_generations && detail.notebooklm_generations.length > 0)) && (
                <div className="rounded-md bg-primary/5 p-2.5">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-primary">
                    <Presentation className="h-3 w-3" />
                    NotebookLM Generated Content
                  </div>
                  <div className="space-y-1.5">
                    {detail.notebooklm_url && (
                      <a
                        href={detail.notebooklm_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-xs text-primary hover:underline"
                      >
                        <ExternalLink className="h-3 w-3" />
                        Open NotebookLM notebook
                      </a>
                    )}
                    {detail.notebooklm_generations.map((gen, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        {gen.status === 'completed' && (
                          <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                            <Presentation className="h-3 w-3" />
                            {gen.content_type.replace('_', ' ')}
                          </span>
                        )}
                        {gen.status === 'completed' && gen.local_path && (
                          <a
                            href={`/api/reports/generation/${gen.id}/download`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-primary hover:underline"
                          >
                            <Download className="h-3 w-3" />
                            Download
                          </a>
                        )}
                        {(gen.status === 'pending' || gen.status === 'in_progress') && (
                          <span className="flex items-center gap-1.5 text-amber-500">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            {gen.content_type.replace('_', ' ')} — {gen.status}
                          </span>
                        )}
                        {gen.status === 'failed' && (
                          <span className="flex items-center gap-1.5 text-destructive">
                            <AlertCircle className="h-3 w-3" />
                            {gen.content_type.replace('_', ' ')} — failed
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Antigravity generated content */}
              {(detail.agy_herenow_url || detail.agy_artifact_path) && (
                <div className="rounded-md bg-primary/5 p-2.5">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-primary">
                    <Rocket className="h-3 w-3" />
                    Antigravity Generated Content
                  </div>
                  <div className="space-y-1.5">
                    {detail.agy_herenow_url && (
                      <a
                        href={detail.agy_herenow_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-xs text-primary hover:underline"
                      >
                        <ExternalLink className="h-3 w-3" />
                        Open on here.now
                      </a>
                    )}
                    {detail.agy_artifact_path && (
                      <span
                        title={detail.agy_artifact_path}
                        className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
                      >
                        <File className="h-3 w-3" />
                        Local artifact: {detail.agy_artifact_path}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-4 text-center text-xs text-muted-foreground">
              No detailed data available.
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
