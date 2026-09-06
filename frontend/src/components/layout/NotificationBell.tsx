import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCircle2, AlertCircle, AlertTriangle, X, Package } from 'lucide-react'
import { api, type NotificationItem } from '@/lib/api'
import { cn } from '@/lib/utils'

const DISMISS_KEY = 'streamdoc:dismissed-notifications'
const POLL_INTERVAL = 60_000 // 60 seconds

/** Load dismissed notification IDs from localStorage. */
function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISS_KEY)
    if (!raw) return new Set()
    return new Set(JSON.parse(raw) as string[])
  } catch {
    return new Set()
  }
}

/** Save dismissed notification IDs to localStorage. */
function saveDismissed(ids: Set<string>): void {
  try {
    // Reason: keep the set bounded so localStorage doesn't grow forever.
    // Retain only the last 100 dismissed IDs.
    const arr = Array.from(ids).slice(-100)
    localStorage.setItem(DISMISS_KEY, JSON.stringify(arr))
  } catch { /* localStorage may be unavailable */ }
}

/** Format an ISO timestamp as a short relative time string. */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 0) return 'just now'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/** Icon for a notification type/severity. */
function NotificationIcon({ type, severity }: { type: string; severity: string }) {
  if (type === 'plugin_update') return <Package className="h-4 w-4 text-amber-500 flex-shrink-0" />
  if (severity === 'error') return <AlertCircle className="h-4 w-4 text-destructive flex-shrink-0" />
  if (severity === 'warning') return <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
  return <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" />
}

export function NotificationBell() {
  const [allNotifications, setAllNotifications] = useState<NotificationItem[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.getNotifications()
      setAllNotifications(result.notifications)
    } catch {
      // silent — bell is non-critical
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [load])

  // Reason: close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Reason: filter out dismissed notifications to get the visible set
  const visible = allNotifications.filter((n) => !dismissed.has(n.id))
  const count = visible.length

  const dismiss = (id: string) => {
    const next = new Set(dismissed)
    next.add(id)
    setDismissed(next)
    saveDismissed(next)
  }

  const dismissAll = () => {
    const next = new Set(dismissed)
    for (const n of visible) next.add(n.id)
    setDismissed(next)
    saveDismissed(next)
  }

  const handleClick = (n: NotificationItem) => {
    dismiss(n.id)
    setOpen(false)
    if (n.action_url) navigate(n.action_url)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'relative flex items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground',
          open && 'bg-accent/50 text-foreground',
        )}
        title={count > 0 ? `${count} notification(s)` : 'Notifications'}
        aria-label="Notifications"
      >
        <Bell className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold text-destructive-foreground">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-card shadow-lg">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold">Notifications</span>
            <div className="flex items-center gap-2">
              {visible.length > 0 && (
                <button
                  onClick={dismissAll}
                  className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  Dismiss all
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="max-h-96 overflow-y-auto">
            {loading && visible.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground animate-pulse">
                <Bell className="h-3.5 w-3.5" />
                Loading notifications...
              </div>
            ) : visible.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                All caught up
              </div>
            ) : (
              <div className="divide-y divide-border">
                {visible.map((n) => (
                  <div
                    key={n.id}
                    className="group flex items-start gap-2.5 px-3 py-2.5 transition-colors hover:bg-accent/30 cursor-pointer"
                    onClick={() => handleClick(n)}
                  >
                    <NotificationIcon type={n.type} severity={n.severity} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-1">
                        <p className="text-xs font-medium leading-tight">{n.title}</p>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            dismiss(n.id)
                          }}
                          className="flex-shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted-foreground leading-tight line-clamp-2">
                        {n.message}
                      </p>
                      <div className="mt-1 flex items-center justify-between">
                        <span className="text-[10px] text-muted-foreground">{timeAgo(n.timestamp)}</span>
                        {n.action_label && (
                          <span className="text-[10px] font-medium text-primary">
                            {n.action_label} →
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
