/** Schedule string formatting helpers shared across pages. */

/** Convert a raw schedule string to a human-readable label. */
export function describeSchedule(raw: string | null | undefined): string {
  const s = (raw || '').trim()
  if (!s) return 'Manual'
  if (s.startsWith('interval:')) {
    const secs = parseInt(s.split('interval:', 2)[1]) || 0
    if (secs >= 3600) return `Every ${Math.round(secs / 3600)} hour(s)`
    if (secs >= 60) return `Every ${Math.round(secs / 60)} minute(s)`
    return `Every ${secs} seconds`
  }
  if (s.startsWith('cron:')) {
    const expr = s.split('cron:', 2)[1].trim()
    const parts = expr.split(/\s+/)
    if (
      parts.length === 5 &&
      parts[1] !== '*' &&
      parts[0] !== '*' &&
      parts[2] === '*' &&
      parts[3] === '*' &&
      parts[4] === '*'
    ) {
      const h = parseInt(parts[1]) || 0
      const m = parseInt(parts[0]) || 0
      return `Daily at ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')} UTC`
    }
    return `Cron: ${expr}`
  }
  return s
}
