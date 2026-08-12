import { useState, useEffect } from 'react'
import { api, type Preset, type ChannelResolveResponse, type PromptTemplate, type AgySkillInfo } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { type SocialSourceEntry } from '@/components/shared/SocialSourcesInput'
import { PromptSection } from './PresetForm/PromptSection'
import { OutputSection } from './PresetForm/OutputSection'
import { BackendSection } from './PresetForm/BackendSection'
import { ScheduleRetentionSection } from './PresetForm/ScheduleRetentionSection'
import { YouTubeSection } from './PresetForm/YouTubeSection'
import { SocialSection } from './PresetForm/SocialSection'

interface ResolvedChannel {
  input: string
  channelId: string
  channelTitle: string
}

export interface PresetFormProps {
  preset: Partial<Preset>
  onChange: (p: Partial<Preset>) => void
  mode?: 'create' | 'edit' | 'view'
  embedded?: boolean
  existingPresets?: Preset[]
}

type ActiveBackend = '__none__' | 'notebooklm' | 'agy'

export function PresetForm({
  preset,
  onChange,
  mode,
  embedded,
  existingPresets,
}: PresetFormProps) {
  const disabled = mode === 'view'

  const [channelInput, setChannelInput] = useState('')
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [resolvedChannels, setResolvedChannels] = useState<ResolvedChannel[]>([])

  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([])
  const [templatePreview, setTemplatePreview] = useState<string | null>(null)

  const [agySkills, setAgySkills] = useState<AgySkillInfo[]>([])
  const [agyModels, setAgyModels] = useState<string[]>([])
  const [agySkillsError, setAgySkillsError] = useState<string | null>(null)
  const [loadingAgySkills, setLoadingAgySkills] = useState(false)
  const [agySkillsLoaded, setAgySkillsLoaded] = useState(false)

  const update = (patch: Partial<Preset>) => onChange({ ...preset, ...patch })
  const setField = <K extends keyof Preset>(key: K, value: Preset[K] | null) =>
    update({ [key]: value } as Partial<Preset>)

  // Reason: parse the JSON social_sources string into typed objects for the UI.
  const parseSources = (): SocialSourceEntry[] => {
    if (!preset.social_sources) return []
    try {
      return JSON.parse(preset.social_sources)
    } catch {
      return []
    }
  }

  const [socialSources, setSocialSourcesInner] = useState<SocialSourceEntry[]>(parseSources)

  const setSocialSources = (sources: SocialSourceEntry[]) => {
    setSocialSourcesInner(sources)
    setField('social_sources', sources.length > 0 ? JSON.stringify(sources) : null)
  }

  // Sync parsed sources when the preset is loaded from the API.
  useEffect(() => {
    setSocialSourcesInner(parseSources())
  }, [preset.social_sources])

  const resolveChannel = async () => {
    const input = channelInput.trim()
    if (!input) return
    // Reason: split on commas so users can paste "channel1, channel2, channel3" and resolve each.
    const inputs = input.split(',').map((s) => s.trim()).filter(Boolean)
    setResolving(true)
    setResolveError(null)
    const newChannels: ResolvedChannel[] = []
    const errors: string[] = []
    for (const item of inputs) {
      try {
        const res: ChannelResolveResponse = await api.resolveChannel(item)
        const existingIds = new Set([
          ...resolvedChannels.map((c) => c.channelId),
          ...newChannels.map((c) => c.channelId),
        ])
        if (existingIds.has(res.channel_id)) {
          errors.push(`"${item}" → ${res.channel_title} is already in the list`)
          continue
        }
        newChannels.push({
          input: item,
          channelId: res.channel_id,
          channelTitle: res.channel_title,
        })
      } catch (e) {
        errors.push(`"${item}": ${(e as Error).message}`)
      }
    }
    if (newChannels.length > 0) {
      const updated = [...resolvedChannels, ...newChannels]
      setResolvedChannels(updated)
      updateChannelFields(updated)
    }
    if (errors.length > 0) {
      setResolveError(errors.join('; '))
    }
    setChannelInput('')
    setResolving(false)
  }

  const updateChannelFields = (channels: ResolvedChannel[]) => {
    // Reason: batch both field updates into a single update() call.
    // Calling setField twice in quick succession causes a stale-closure bug:
    // each setField spreads the current `preset` prop, but the prop hasn't
    // updated between the two calls (React state is async). The second call
    // would overwrite the first call's channel_list_id with the stale value,
    // causing channels to disappear on save.
    update({
      channel_list_id: channels.map((c) => c.channelId).join(',') || null,
      channel_names: channels.map((c) => c.channelTitle).join(',') || null,
    })
  }

  const removeChannel = (idx: number) => {
    const updated = resolvedChannels.filter((_, i) => i !== idx)
    setResolvedChannels(updated)
    updateChannelFields(updated)
  }

  const initFromExisting = () => {
    if (resolvedChannels.length === 0 && preset.channel_list_id) {
      const ids = preset.channel_list_id.split(',').map((s) => s.trim()).filter(Boolean)
      const names = (preset.channel_names || '').split(',').map((s) => s.trim()).filter(Boolean)
      if (ids.length > 0) {
        setResolvedChannels(
          ids.map((id, i) => ({
            input: id,
            channelId: id,
            channelTitle: names[i] || id,
          })),
        )
      }
    }
  }

  // Initialize resolved channels when the preset being edited changes.
  useEffect(() => {
    initFromExisting()
  }, [preset.channel_list_id])

  // Load prompt templates once on mount.
  useEffect(() => {
    api.listPrompts()
      .then(setPromptTemplates)
      .catch(() => {})
  }, [])

  // Reason: determine which backend is active from the outputs string.
  const getActiveBackend = (): ActiveBackend => {
    const outputs = (preset.outputs || '').toLowerCase()
    if (outputs.includes('agy')) return 'agy'
    if (outputs.includes('notebooklm')) return 'notebooklm'
    return '__none__'
  }

  const activeBackend = getActiveBackend()

  // Load AGY skills and models when the Antigravity backend is selected.
  useEffect(() => {
    if (activeBackend !== 'agy') return
    if (agySkillsLoaded) return
    setAgySkillsLoaded(true)
    setLoadingAgySkills(true)
    setAgySkillsError(null)
    Promise.all([api.agy.listSkills(), api.agy.supportedModels()])
      .then(([skills, models]) => {
        setAgySkills(skills)
        setAgyModels(models)
      })
      .catch((e) => {
        setAgySkillsError((e as Error).message)
        setAgySkills([])
        setAgyModels([])
      })
      .finally(() => setLoadingAgySkills(false))
  }, [activeBackend, agySkillsLoaded])

  // Reason: keep the template preview in sync with the selected template.
  const selectedTemplateName =
    activeBackend === 'agy' ? preset.agy_prompt_template : preset.notebooklm_prompt_template
  const selectedTemplate = promptTemplates.find((t) => t.name === (selectedTemplateName || ''))
  const isTemplateLocked = !!selectedTemplate

  useEffect(() => {
    setTemplatePreview(isTemplateLocked && selectedTemplate ? selectedTemplate.prompt : null)
  }, [isTemplateLocked, selectedTemplate])

  const nameConflict = existingPresets?.some(
    (p) => p.name === preset.name && p.id !== preset.id,
  )

  return (
    <div className="grid gap-4 py-2">
      <div className="grid gap-1.5">
        <Label htmlFor="name" className="text-xs">
          Preset Name
        </Label>
        <Input
          id="name"
          value={preset.name || ''}
          onChange={(e) => setField('name', e.target.value)}
          placeholder="e.g. Daily Trading Recap"
          disabled={disabled}
        />
        {nameConflict && (
          <p className="text-xs text-destructive">A preset with this name already exists.</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label className="text-xs">Preset Type</Label>
        <div className="flex rounded-lg border border-border p-0.5 bg-muted/50">
          <button
            type="button"
            className={cn(
              'flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              (!preset.preset_type || preset.preset_type === 'youtube')
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => setField('preset_type', 'youtube')}
            disabled={disabled}
          >
            YouTube
          </button>
          <button
            type="button"
            className={cn(
              'flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              preset.preset_type === 'social'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => setField('preset_type', 'social')}
            disabled={disabled}
          >
            Social
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
          {preset.preset_type === 'social'
            ? 'Collect posts from social platforms instead of YouTube videos.'
            : 'Process YouTube videos from specified channels.'}
        </p>
      </div>

      {(!preset.preset_type || preset.preset_type === 'youtube') && (
        <YouTubeSection
          preset={preset}
          channelInput={channelInput}
          setChannelInput={setChannelInput}
          resolving={resolving}
          resolveError={resolveError}
          resolvedChannels={resolvedChannels}
          onResolve={resolveChannel}
          onRemoveChannel={removeChannel}
          update={update}
          disabled={disabled}
        />
      )}

      {preset.preset_type === 'social' && (
        <SocialSection
          preset={preset}
          sources={socialSources}
          onSourcesChange={setSocialSources}
          update={update}
          disabled={disabled}
        />
      )}

      <PromptSection
        preset={preset}
        activeBackend={activeBackend}
        promptTemplates={promptTemplates}
        selectedTemplateName={selectedTemplateName}
        isTemplateLocked={isTemplateLocked}
        templatePreview={templatePreview}
        update={update}
        disabled={disabled}
      />

      <OutputSection preset={preset} update={update} disabled={disabled} />

      <BackendSection
        preset={preset}
        activeBackend={activeBackend}
        agySkills={agySkills}
        agyModels={agyModels}
        loadingAgySkills={loadingAgySkills}
        agySkillsError={agySkillsError}
        update={update}
        disabled={disabled}
      />

      <ScheduleRetentionSection preset={preset} update={update} disabled={disabled} />

      <div className="flex items-center gap-6 pt-1">
        <div className="flex items-center gap-2">
          <Switch
            checked={preset.skip_processed ?? true}
            onCheckedChange={(v) => setField('skip_processed', v)}
            disabled={disabled}
          />
          <Label className="text-xs">Skip Processed</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={preset.active ?? true}
            onCheckedChange={(v) => setField('active', v)}
            disabled={disabled}
          />
          <Label className="text-xs">Active</Label>
        </div>
      </div>
    </div>
  )
}
