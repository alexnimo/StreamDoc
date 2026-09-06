import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Settings, Briefcase, BookOpen, Zap, FileText, CalendarClock, Files, Rocket } from 'lucide-react'
import { ThemeToggle } from './ThemeToggle'
import { NotificationBell } from './NotificationBell'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/presets', label: 'Presets', icon: Zap },
  { to: '/prompts', label: 'Prompts', icon: FileText },
  { to: '/jobs', label: 'Jobs', icon: Briefcase },
  { to: '/reports', label: 'Reports', icon: Files },
  { to: '/scheduler', label: 'Scheduler', icon: CalendarClock },
  { to: '/notebooklm', label: 'NotebookLM', icon: BookOpen },
  { to: '/antigravity', label: 'Antigravity', icon: Rocket },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function TopNav() {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/60">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <img src="/icon.svg" alt="StreamDoc" className="h-7 w-7 rounded-md" />
          <span className="text-base font-semibold tracking-tight">StreamDoc</span>
        </div>

        <nav className="flex items-center gap-0.5">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{item.label}</span>
              </NavLink>
            )
          })}
        </nav>

        <div className="flex items-center gap-2">
          <NotificationBell />
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
