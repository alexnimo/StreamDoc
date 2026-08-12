# StreamDoc Update Mechanism Design

## Goal
Keep runtime dependencies current with minimal friction:
- `yt-dlp` (primary downloader)
- `ffmpeg` / `ffprobe` (media processing)
- `faster-whisper` + model refresh (local transcription fallback)
- optional tools: SponsorBlock helper, audio normalizer

## Update policies by runtime mode

| Dependency      | Local install behavior                    | Docker behavior                                   |
|-----------------|------------------------------------------|---------------------------------------------------|
| `yt-dlp`        | Upgrade via pip / standalone binary       | Image rebuild OR bind-mounted binary refresh       |
| `ffmpeg`        | System pkg manager or static binary       | Image rebuild OR bind-mounted binary refresh       |
| `faster-whisper`| Upgrade via pip; model pull on demand     | Image rebuild OR mounted model cache refresh       |
| Models          | HuggingFace cache under `data/Models/`   | Same mounted path; pull on demand if missing       |

## Update tracks

1. **App release** — tagged builds of StreamDoc itself shipped via GitHub Releases.
2. **Tooling track** — `yt-dlp`, `ffmpeg`, `faster-whisper` updated by the updater.
3. **Model track** — only pulled when a Whisper fallback is needed and cache is absent or stale.

## Update triggers

- **CLI / on demand**: `streamdoc update [--tool yt-dlp] [--tool ffmpeg] [--tool whisper]`
- **Startup check**: optional flag `updater.check_on_startup`; default weekly cadence.
- **Error retry path**: if a download fails with signature indicating an outdated `yt-dlp`, retry once after an auto-update.
- **CI / container**: separate workflow rebuilds image at image-weekly cadence; tool update still layered in via pinned versions in `pyproject.toml`.

## Version contract

- Updater stores last-known versions in `data/State/updater-state.json`.
- A version is reported as one of:
  - installed string/bin path mtime
  - pip package version
  - remote latest via API/release endpoint

## Implementation shape

File: `src/streamdoc/updater.py`

- `check(tool: str) -> dict` — returns current/latest/outdated.
- `update(tool: str) -> dict` — performs update and records new state.
- supported tools: `yt-dlp`, `ffmpeg`, `faster-whisper`, `models`.

CLI wiring:
- Hermes/cron can invoke `streamdoc update` in local mode.
- Docker entrypoint supports `ENTRYPOINT ["streamdoc", "update-and-run"]` for fresh containers.

## Failure modes

- Network unavailable: fall back to existing installed tools; no hard failure.
- Partial failure: log and continue; schedule one retry.
- Binary replacement in-use on Windows: stop dependent process or defer to next restart; prefer graceful shutdown in service mode.
