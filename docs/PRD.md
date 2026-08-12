# StreamDoc — Product Requirements Document, v1

## 1. Problem

YouTube is a primary lecture, conference, and tutorial source.
Watching is inefficient; searchable, structured notes are the target format.
Manual download → transcribe → summarize → export to NotebookLM is repeatable
and automatable.

## 2. Goal

Build a single-user, local-first system that:
1. Watches subscribed YouTube channels and playlists on a schedule.
2. Downloads new videos when possible.
3. Extracts transcripts (preferred: official/proxy; fallback: local Whisper).
4. Produces NotebookLM-ready artifacts: PDF + Markdown input + NotebookLM
   integration, without manual browser steps.
5. Uses NotebookLM plug-ins/providers supported by the chosen Python library
   to generate downstream outputs such as slide decks, podcasts, and any other
   supported output formats.
6. Avoids depending on YouTube’s undoc API.
7. Survives common YouTube anti-bot blocks via layered bypass strategies.
8. Generates per-video visual summaries (key frames) and deduplicates them.
9. Supports multiple named presets with per-channel prompts and schedules.
10. Uses complementary metadata/tools alongside yt-dlp where they improve
    reliability or add features.

## 3. Non-goals (v1)

- Multi-user / auth
- Cloud hosting as primary deployment
- Browser automation for auth
- Realtime streaming ingest
- Chromecast / iOS / Android app
- Backup downloader alternatives

## 4. Success metrics

- Fresh video → working local file within N minutes of upload (target: 60),
  or `media_failed` is marked and the run continues.
- Channel/playlist resolution succeeds without YouTube Data API.
- Transcript coverage ≥ 90% for processed videos.
- Anti-bot bypass works without interactive login for the majority of videos;
  exception path is automatic and documented, not manual recovery.
- NotebookLM integration completes without user action; when it cannot, the run
  marks `integration-failed` and still retains PDF/Markdown.
- Produced PDF includes representative stills from the video.
- Key-frame dedup reduces duplicates by ≥80% versus naive sampling.
- Output generation is efficient: preset → artifact with minimal idle waiting.
- Runtime dependencies stay current with minimal user intervention.

## 5. User stories

1. As a user, I define a list of channels and a frequency.
2. As a user, the system fetches new videos and downloads media.
3. As a user, transcripts are available even when video download is blocked.
4. As a user, NotebookLM receives the new material without me opening a browser.
5. As a user, I can override downloader behavior per run.
6. As a user, I can create named presets with different prompts and schedules.
7. As a user, I can assign a preset to one or more channels.
8. As a user, I get outputs that have both text and visuals.
9. As a user, I can point a preset at a playlist, not just individual channels.
10. As a user, NotebookLM plug-in outputs match the library’s supported formats.
11. As a user, I get sponsor-blocked clean media/frames without manual editing.
12. As a user, runtime tools update automatically or via one command.
13. As a user, channel metadata resolves even when yt-dlp hits a block.
14. As a user, I can configure how far back we look for new content.
15. As a user, already-processed videos are never reprocessed.

## 6. Architecture

```
┌────────────────────────────┐    ┌───────────────────────┐    ┌────────────────────────────────────────┐
│  Channel feed / playlist   │ -> │ Scheduler / Fetch      │ -> │ Downloader / Media                      │
│  yt-dlp + metadata tools   │    │  fetch.py / preset     │    │  downloader.py / media.py               │
│  + YoutubeExplode fallback │    │  scheduler.py          │    │  + SponsorBlock + ffmpeg preprocessing  │
└────────────────────────────┘    └───────────────────────┘    └───────────────┬────────────────────────┘
                                                                                 │
                                                                   ┌───────────────▼─────────────────────────┐
                                                                   │ Frame extraction + dedup                  │
                                                                   │ frames.py (p-hash/dhash/ahash)            │
                                                                   │ ffmpeg-based sampling + scene detection   │
                                                                   └───────────────┬─────────────────────────┘
                                                                                 │
                                                                   ┌───────────────▼─────────────────────────┐
                                                                   │ Transcript Pipeline                       │
                                                                   │ transcript.py                             │
                                                                   │ youtube-transcript-api + faster-whisper   │
                                                                   │ audio norm / silence trim                  │
                                                                   └───────────────┬─────────────────────────┘
                                                                                 │
                                                                   ┌───────────────▼─────────────────────────┐
                                                                   │ Output Assembly                           │
                                                                   │ output.py (PDF/MD)                        │
                                                                   │ integration.py (NotebookLM plug-ins)       │
                                                                   └─────────────────────────────────────────┘
```

## 7. Component specs

### 7.1 Preset / channel wiring

`Preset` holds run-time contract for a scheduled job:
- id, name, channel_list_id
- prompt_md (freeform; default generated per channel or user-supplied)
- schedule (cron / interval)
- output_targets: `pdf | markdown | notebooklm | all`
- notebooklm_kind: optional hint for plug-in output, e.g. `slide_deck`, `podcast`
- lookback_hours: optional override for how far back to consider new videos
- skip_processed: default true; never reprocess a video already recorded in DB

Resolution rules:
- One channel can belong to multiple presets.
- One preset can include many channels AND playlists.
- Per-run config may override global `yt-dlp` bypass mode.
- A preset is the unit of scheduled execution.
- Within a run, candidate videos are filtered to the preset/channel list first,
  then deduped against existing DB records before download/transcript.

### 7.2 Scheduler / polling

- APScheduler-backed runner.
- CLI: `streamdoc schedule list|add|remove|run`
- Persist scheduler state in SQLite / file; jobs survive restart.
- Run modes: `once`, `interval`, `cron`.

### 7.3 Channel + video resolution

- Input: channel URL, handle, playlist URL, or custom RSS/playlist URL.
- Output: `Channel` with `id`, `title`, `source`.
- Failure: retry once, then mark channel `error`.
- Implementation priority:
  1. `core/channel.py` uses `yt-dlp --dump-json` / flat playlist.
  2. Metadata fallback: `YoutubeExplode`-style metadata resolution for channel ID,
     playlist items, and basic video metadata where API keys are absent.
     Run in-process or via a tiny local metadata service if the library is
     .NET-only; do not block downloads on metadata fallback.

### 7.4 Media downloader

Primary tooling: `yt-dlp`.
Output template: `{media_root}/{channel_id}/%(id)s.%(ext)s`.

#### 7.4.1 YouTube bypass strategy

1. PO-Token provider.
   - Extractor args: `youtube:player_client=web;pot_provider=bgutil`.
   - Requires a compatible `bgutil-ytdlp-pot-provider` installation.
2. Cookie jar from an exported browser profile.
   - Path from config / env `STREAMDOC_YT_DLP_COOKIEJAR_PATH`.
   - Store cookies in a top-level mounted directory on the host.
   - Mount into container if running containerized, so the browser stays closed
     and setup is non-interactive.
3. Metadata tools complement yt-dlp when page constraints change; evaluate and
   wire into channel resolution/verification as needed.
4. Default: plain `yt-dlp` with no bypass args.

#### 7.4.2 SponsorBlock / segment cleanup

- Trim or skip known sponsor segments before frame extraction to reduce visual
  noise in summaries.
- Tools: SponsorBlock integration via `yt-dlp` sponsorblock plugin or the
  `Spoticord/yt-dlp-sponsorblock` wrapper pattern.
- Failure policy: if SponsorBlock lookup fails, proceed without trimming.

#### 7.4.3 Audio preprocessing before transcription

- Normalize loudness with ffmpeg EBU R128 or `ffmpeg-normalize`.
- Optional silence trimming / time-stretch via `podarch` / `audiotsm` patterns
  when transcript quality is poor.
- Only applied when local Whisper fallback is used.

#### 7.4.4 Frame extraction and deduplication

- Source: downloaded video file.
- Sampling: scene-change-aware + fixed interval for videos with static scenes.
- Interface: `core/frames.py`
  - `extract_frames(video_path) -> list[Path]`
  - `dedup_frames(paths) -> list[Path]` using `p-hash` | `d-hash` | `a-hash`
    via `imagehash` + optional chroma store.
  - config: `frame_max_count`, `frame_min_interval_s`, `frame_hash_algo`
- Storage: `{media_root}/{channel_id}/{video_id}/frames/{hash}.jpg`
- Quality: scale long edge to 1280 max; JPEG quality ~80–85.
- Filtering: drop highly similar frames (hamming threshold ~10).
- Store frame metadata: `video_id`, `frame_path`, `timestamp_s`, `hash`.

### 7.5 Transcript pipeline

- Preferred: transcript extraction from official/proxy sources alongside yt-dlp.
- Supported languages: `en`, `he`, `ar`.
- Fallback: local `faster-whisper` (SYSTRAN/faster-whisper).
  - Invoked only when no transcript/subtitles are available.
  - Typical for long and live videos.
- Storage: `data/State/<video_id>.transcript.json`.
- Output: transcript is optional for NotebookLM; PDF generation must degrade
  gracefully without it.

### 7.6 Output assembly

Responsibilities: build PDF and Markdown from transcript + frames.

PDF pipeline (reportlab / fpdf2 / WeasyPrint):
- Cover page: channel, title, published_at, source URL.
- TOC by section/timestamp (when available).
- Content blocks:
  - Markdown-like headings per chapter/topic.
  - Transcript passages.
  - Representative frames inserted at meaningful timestamps.
- Metadata: provenance, generated_at, preset name, channel.

Markdown export:
- YAML front matter for NotebookLM upload.
- Transcript as structured sections.
- Frame images as relative paths or base64 inline images (configurable).
- Used as NotebookLM source when upload is enabled.

NotebookLM integration:
- Preferred: upload Markdown file via `notebooklm-py`.
- Alternative: upload extracted frames bundle (zip) if supported.
- Failure policy: mark `integration-failed` and keep local PDF/MD.

### 7.7 NotebookLM integration / plug-ins

- The preset defines:
  - input sources: channels, playlists
  - prompt + instructions
  - NotebookLM destination or plug-in target
  - output kind hint: `slide_deck`, `podcast`, or library-native defaults
- Flow:
  1. Build local PDF/Markdown.
  2. Pass output + prompt + source context into NotebookLM integration.
  3. Download/export generated artifact if available.
- Supported outputs via the chosen NotebookLM Python library:
  - slide deck
  - podcast
  - other supported formats as the library exposes them
- Policy: treat notebooklm as a mandatory first-class output target with
  explicit failure handling; do not block the rest of the pipeline if it fails.

### 7.8 Update mechanism

See `docs/updater-design.md`.

## 8. Data model changes

```text
Channel/Playlist reference
  - source_kind: str         # channel | playlist | feed
  - source_url: str
  - resolved_id: str         # channel_id or playlist_id
  - title: str

Video
  - webpage_url: str | None
  - transcript_status: str  # missing | pending | ready | failed
  - media_status: str       # missing | pending | ready | failed
  - output_status: str      # missing | pending | ready | failed | integration-failed
  - sponsorblock_clean: bool
  - audio_preprocessed: bool

Frame
  - video_id: str (FK)
  - frame_path: str
  - timestamp_s: float
  - hash: str
  - bytes: int
  - status: str

Preset
  - id: str (PK)
  - name: str
  - prompt_md: str
  - outputs: str          # csv or list: pdf|markdown|notebooklm
  - notebooklm_kind: str | None
  - schedule: str | None   # cron/interval DSL
  - lookback_hours: int | None
  - skip_processed: bool
  - channel_list_id: str | None
  - active: bool
  - created_at, updated_at
```

## 9. Configuration schema

Prior keys plus:
- `STREAMDOC_FRAME_MAX_COUNT`
- `STREAMDOC_FRAME_MIN_INTERVAL_S`
- `STREAMDOC_FRAME_HASH_ALGO` = `phash|dhash|ahash`
- `STREAMDOC_FRAME_LONG_EDGE`
- `STREAMDOC_FRAME_JPEG_QUALITY`
- `STREAMDOC_OUTPUT_FORMATS` = `pdf,markdown,notebooklm`
- `STREAMDOC_PRESETS_PATH`
- `STREAMDOC_YT_DLP_COOKIEJAR_PATH`
- `STREAMDOC_YT_DLP_BYPASS_MODE` = `default|po_token|cookie`
- `STREAMDOC_NOTEBOOKLM_*`
- `STREAMDOC_SPONSORBLOCK_ENABLED` = `true|false`
- `STREAMDOC_AUDIO_NORMALIZE_ENABLED` = `true|false`

## 10. Docker layout

Prior layout plus:
```yaml
services:
  app:
    ...
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./cookies:/app/cookies:ro
      - ./presets:/app/presets:ro
```

## 11. Build / dev requirements

Same as before plus:
- testing for p-hash and frame sampling
- testing for sponsorblock segment skipping
- testing for metadata fallback resolver
- testing for audio normalizer/silence trim pipeline

## 12. Error handling policy

Extended:
- `frames` pipeline failure → mark `frames_failed`, continue to transcript if available.
- PDF export failure → retry once; if still failing, produce Markdown only.
- NotebookLM exporter/plug-in failure → mark `integration-failed`, keep local PDF/MD.
- SponsorBlock lookup failure → log and continue without segment removal.
- Metadata fallback failure → log and fall back to yt-dlp default resolution.

## 13. Observability

Add:
- `frames_extracted`, `frames_kept_after_dedup`, `pdf_pages`.
- `notebooklm_status`, `plugin_output_kind`.
- `sponsorblock_segments_removed`.
- `audio_norm_applied`, `whisper_model_used`.
- `metadata_resolver_used`.

## 14. Milestones

1. Project scaffold + config + Docker + updater.
2. Channel + video resolution + presets + scheduler + metadata fallback.
3. Media downloader + PO-Token + cookie + SponsorBlock + bypass strategy.
4. Frame extraction + p-hash dedup.
5. Transcript pipeline + audio preprocessing + Whisper fallback.
6. PDF/Markdown/NotebookLM output assembly + plug-ins.
7. Update tooling + CLI + validation.

## 15. Acceptance criteria

- `streamdoc fetch <preset>` completes a run.
- Runs honor `lookback_hours` by only considering videos newer than that window.
- Already-processed videos from DB are skipped; no duplicate output artifacts.
- All watched new videos are recorded in DB with status flags.
- Media appears in `media_root` or is marked `media_failed`.
- Frames extracted and deduplicated under `media_root`.
- Transcripts stored or marked `transcript_failed`.
- PDF built from transcript + frames; Markdown generated.
- NotebookLM output generated or marked `integration-failed`; local PDF/Markdown is always viable fallback.
- Docs include cookie jar setup for Docker and desktop.
- Multiple presets with different channels and prompts run on independent schedules.
- Playlist-based presets work the same way as channel-based presets.
- SponsorBlock segments are removed where available, skipped otherwise.
- Audio normalization is applied before Whisper when enabled.
- Metadata resolution falls back to YoutubeExplode-style metadata when yt-dlp resolution is blocked.
- Runtime dependencies update via `streamdoc update`.
