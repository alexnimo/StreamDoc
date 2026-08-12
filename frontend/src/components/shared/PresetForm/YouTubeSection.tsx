import { Search, X, Youtube, Info, Filter, Loader2 } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import type { Preset } from '@/lib/api'

interface ResolvedChannel {
  input: string
  channelId: string
  channelTitle: string
}

interface YouTubeSectionProps {
  preset: Partial<Preset>
  channelInput: string
  setChannelInput: (value: string) => void
  resolving: boolean
  resolveError: string | null
  resolvedChannels: ResolvedChannel[]
  onResolve: () => void
  onRemoveChannel: (idx: number) => void
  update: (patch: Partial<Preset>) => void
  disabled?: boolean
}

export function YouTubeSection({
  preset,
  channelInput,
  setChannelInput,
  resolving,
  resolveError,
  resolvedChannels,
  onResolve,
  onRemoveChannel,
  update,
  disabled,
}: YouTubeSectionProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-1.5">
        <Label className="text-xs">YouTube Channels</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Youtube className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={channelInput}
              onChange={(e) => setChannelInput(e.target.value)}
              onKeyDown={(e) =>
                e.key === 'Enter' && (e.preventDefault(), onResolve())
              }
              placeholder="@handle, channel name, or full URL"
              className="pl-8"
              disabled={disabled}
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onResolve}
            disabled={resolving || !channelInput.trim() || disabled}
          >
            {resolving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Search className="h-3.5 w-3.5" />
            )}
            <span className="ml-1.5">Resolve</span>
          </Button>
        </div>
        {resolveError && (
          <p className="text-xs text-destructive">{resolveError}</p>
        )}
        <p className="text-xs text-muted-foreground">
          Enter a channel name, @handle, full YouTube URL, or channel ID. Separate multiple entries with commas.
        </p>

        {resolvedChannels.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {resolvedChannels.map((ch, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-2 py-1 text-xs"
              >
                <span className="font-medium text-primary">{ch.channelTitle}</span>
                <span className="text-muted-foreground">{ch.channelId}</span>
                <button
                  type="button"
                  onClick={() => onRemoveChannel(i)}
                  className="text-muted-foreground hover:text-destructive"
                  disabled={disabled}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-md border border-border p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-xs">Playlist Mode</Label>
            <p className="text-xs text-muted-foreground mt-0.5">
              Treat the channel input as a playlist URL instead of a channel.
            </p>
          </div>
          <Switch
            checked={preset.playlist_mode || false}
            onCheckedChange={(v) => update({ playlist_mode: v })}
            disabled={disabled}
          />
        </div>
        {preset.playlist_mode && (
          <div className="flex items-start gap-2 rounded-md bg-secondary/50 p-2.5">
            <Info className="h-3.5 w-3.5 shrink-0 text-primary mt-0.5" />
            <p className="text-xs text-muted-foreground">
              Enter playlist URLs (e.g. https://www.youtube.com/playlist?list=PLxxxx) in the channel field above.
              All videos in the playlist will be processed.
            </p>
          </div>
        )}
      </div>

      <div className="rounded-md border border-border p-3 space-y-3">
        <div className="flex items-center gap-1.5">
          <Filter className="h-3.5 w-3.5 text-primary" />
          <Label className="text-xs font-medium">Video Filtering</Label>
        </div>
        <p className="text-xs text-muted-foreground">Control which videos get processed when the preset runs.</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="lookback" className="text-xs">
              Lookback Window (hours)
            </Label>
            <Input
              id="lookback"
              type="number"
              value={formValue(preset.lookback_hours)}
              onChange={(e) => update({ lookback_hours: parseIntOrNull(e.target.value) })}
              placeholder="24"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">Only process videos published in the last N hours.</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="date_range_days" className="text-xs">
              Lookback Window (days)
            </Label>
            <Input
              id="date_range_days"
              type="number"
              value={formValue(preset.date_range_days)}
              onChange={(e) => update({ date_range_days: parseIntOrNull(e.target.value) })}
              placeholder="7"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">If set, overrides the hours field.</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="max_videos" className="text-xs">
              Max Videos per Channel
            </Label>
            <Input
              id="max_videos"
              type="number"
              value={formValue(preset.max_videos)}
              onChange={(e) => update({ max_videos: parseIntOrNull(e.target.value) })}
              placeholder="5"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Maximum videos to process from each channel within the lookback window.
            </p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="text_filter" className="text-xs">
              Title Filter
            </Label>
            <Input
              id="text_filter"
              value={preset.text_filter || ''}
              onChange={(e) => update({ text_filter: e.target.value })}
              placeholder="e.g. BTC, ETH, Bitcoin"
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              Only process videos whose title contains this text.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function formValue(value: number | null | undefined): string | number {
  return value == null ? '' : value
}

function parseIntOrNull(value: string): number | null {
  return value === '' ? null : parseInt(value, 10)
}
