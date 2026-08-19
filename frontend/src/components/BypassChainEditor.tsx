import { ChevronUp, ChevronDown, X, Plus, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip'

// Reason: kept in sync with SUPPORTED_BYPASS_MODES in downloader.py.
// Each entry has a short label and a tooltip explaining what it does,
// what it bypasses, and its limitations — so operators can make an
// informed decision when building the chain.
const BYPASS_MODE_INFO: Record<string, { label: string; tooltip: string }> = {
  web_embedded: {
    label: 'Web Embedded',
    tooltip: 'Uses the WEB_EMBEDDED_PLAYER client. Bypasses IP-level 403 blocks on DASH/HTTPS downloads and gets full-quality URLs (up to 4K). No PO token or cookies needed. Requires a JS runtime (node/deno). Does not work for videos with embedding disabled.',
  },
  po_token: {
    label: 'PO Token',
    tooltip: 'Uses a PO Token provider container (bgutil-ytdlp-pot-provider) to generate Proof-of-Origin tokens. Needs Docker to run the container. The web client may be SABR-only (formats skipped), so this may fall back to android_vr which can 403 mid-download.',
  },
  cookie: {
    label: 'Cookie Jar',
    tooltip: 'Uses a pre-exported Netscape-format cookie jar at yt_dlp_cookiejar_path. Requires manual cookie export from a signed-in browser session. Good for members-only or age-restricted content.',
  },
  cookies_from_browser: {
    label: 'Browser Cookies',
    tooltip: 'Reads cookies directly from the operator\'s signed-in browser session. No manual export needed. Fails if Chrome/Edge is running on Windows (cookie DB locked). Configure the browser via yt_dlp_cookies_browser.',
  },
  hls: {
    label: 'HLS Fallback',
    tooltip: 'Uses the web_safari client with HLS (m3u8) formats. Bypasses IP-level 403 blocks but is capped at 480p — quality-degraded last resort. Requires a JS runtime (node/deno). Use only when all other modes fail.',
  },
  default: {
    label: 'Default',
    tooltip: 'yt-dlp built-in client selection (android_vr, web_safari). No bypass applied. Subject to IP-level 403 blocks on DASH downloads.',
  },
}

const ALL_MODES = Object.keys(BYPASS_MODE_INFO)

interface BypassChainEditorProps {
  value: string
  onChange: (value: string) => void
}

export function BypassChainEditor({ value, onChange }: BypassChainEditorProps) {
  // Reason: parse the comma-separated string into an ordered list,
  // filtering out empty entries and unknown modes.
  const modes = value
    .split(',')
    .map((m) => m.trim())
    .filter((m) => m && BYPASS_MODE_INFO[m])

  const update = (newModes: string[]) => {
    onChange(newModes.join(','))
  }

  const moveUp = (index: number) => {
    if (index === 0) return
    const next = [...modes]
    ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
    update(next)
  }

  const moveDown = (index: number) => {
    if (index === modes.length - 1) return
    const next = [...modes]
    ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
    update(next)
  }

  const remove = (index: number) => {
    update(modes.filter((_, i) => i !== index))
  }

  // Reason: only show modes in the dropdown that aren't already in the
  // chain — prevents duplicates.
  const available = ALL_MODES.filter((m) => !modes.includes(m))

  const add = (mode: string) => {
    if (!mode || modes.includes(mode)) return
    update([...modes, mode])
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-2">
        {/* Ordered list of modes */}
        {modes.length === 0 && (
          <p className="text-xs text-muted-foreground italic">
            Chain is empty — legacy bypass mode + fallback will be used.
          </p>
        )}
        {modes.map((mode, index) => {
          const info = BYPASS_MODE_INFO[mode]
          if (!info) return null
          return (
            <div
              key={`${mode}-${index}`}
              className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-2 py-1.5"
            >
              {/* Step number */}
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-medium text-primary">
                {index + 1}
              </span>

              {/* Mode badge with tooltip */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help">
                    <Badge variant="secondary" className="gap-1 text-xs">
                      {info.label}
                      <Info className="h-3 w-3 text-muted-foreground" />
                    </Badge>
                  </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs text-xs">
                  {info.tooltip}
                </TooltipContent>
              </Tooltip>

              {/* Spacer */}
              <div className="flex-1" />

              {/* Up / Down / Remove buttons */}
              <div className="flex items-center gap-0.5">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => moveUp(index)}
                  disabled={index === 0}
                >
                  <ChevronUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => moveDown(index)}
                  disabled={index === modes.length - 1}
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-destructive hover:text-destructive"
                  onClick={() => remove(index)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )
        })}

        {/* Add mode dropdown */}
        {available.length > 0 && (
          <div className="flex items-center gap-2 pt-1">
            <Plus className="h-3.5 w-3.5 text-muted-foreground" />
            <Select value="" onValueChange={add}>
              <SelectTrigger className="h-7 w-full text-xs">
                <SelectValue placeholder="Add bypass mode…" />
              </SelectTrigger>
              <SelectContent>
                {available.map((mode) => (
                  <SelectItem key={mode} value={mode} className="text-xs">
                    {BYPASS_MODE_INFO[mode].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Help text */}
        <p className="text-[11px] text-muted-foreground">
          Modes are tried top-to-bottom. On retriable failure (403, bot
          detection, rate limit) the next mode is tried. On success or
          permanent error (private/deleted) the chain stops.
        </p>
      </div>
    </TooltipProvider>
  )
}
