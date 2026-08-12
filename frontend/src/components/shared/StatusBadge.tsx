import { cn } from '@/lib/utils'

const statusConfig: Record<string, { label: string; className: string }> = {
  completed: { label: 'Completed', className: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  running: { label: 'Running', className: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  failed: { label: 'Failed', className: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  partial: { label: 'Partial', className: 'bg-orange-500/15 text-orange-600 dark:text-orange-400' },
  ready: { label: 'Ready', className: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  active: { label: 'Active', className: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  missing: { label: 'Missing', className: 'bg-zinc-500/15 text-zinc-500' },
  unknown: { label: 'Unknown', className: 'bg-zinc-500/15 text-zinc-500' },
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const config = statusConfig[status] || { label: status, className: 'bg-zinc-500/15 text-zinc-500' }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        config.className,
        className,
      )}
    >
      {config.label}
    </span>
  )
}
