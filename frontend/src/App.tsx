import { Routes, Route } from 'react-router-dom'
import { TopNav } from '@/components/layout/TopNav'
import Dashboard from '@/pages/Dashboard'
import Presets from '@/pages/Presets'
import Prompts from '@/pages/Prompts'
import Jobs from '@/pages/Jobs'
import Reports from '@/pages/Reports'
import Scheduler from '@/pages/Scheduler'
import NotebookLM from '@/pages/NotebookLM'
import Antigravity from '@/pages/Antigravity'
import Settings from '@/pages/Settings'
import SocialSettings from '@/pages/SocialSettings'

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <TopNav />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/presets" element={<Presets />} />
          <Route path="/prompts" element={<Prompts />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/scheduler" element={<Scheduler />} />
          <Route path="/notebooklm" element={<NotebookLM />} />
          <Route path="/antigravity" element={<Antigravity />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/social" element={<SocialSettings />} />
        </Routes>
      </main>
    </div>
  )
}
