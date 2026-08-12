import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Package, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * A nav icon that shows a red dot badge when any plugin has an update
 * available. Clicking navigates to the Settings page where the full
 * PluginUpdates card lives.
 *
 * Reason: the user needs visibility into plugin updates across ALL screens,
 * not just Settings. This badge appears in the top nav so it's always
 * visible. It polls the cached plugin status endpoint (no PyPI hit) every
 * 12 hours — the backend cadence (daily/weekly/manual) already controls
 * how often PyPI is actually hit, so a longer poll interval here is
 * sufficient and avoids unnecessary requests.
 */
export function PluginUpdateBadge() {
  const [updateCount, setUpdateCount] = useState(0)

  useEffect(() => {
    let cancelled = false

    const check = () => {
      api.listPlugins()
        .then((plugins) => {
          if (cancelled) return
          setUpdateCount(plugins.filter((p) => p.update_available).length)
        })
        .catch(() => { /* silent — badge is non-critical */ })
    }

    check()
    const interval = setInterval(check, 12 * 60 * 60 * 1000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <NavLink
      to="/settings"
      className={({ isActive }) =>
        cn(
          'relative flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
          isActive
            ? 'bg-primary/10 text-primary'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
        )
      }
      title={updateCount > 0 ? `${updateCount} plugin update(s) available` : 'Plugin status'}
    >
      <Package className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">Plugins</span>
      {updateCount > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold text-destructive-foreground">
          {updateCount}
        </span>
      )}
    </NavLink>
  )
}
