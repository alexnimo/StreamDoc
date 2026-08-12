# StreamDoc Repository Layout

## Top-level
```
streamdoc/
├── pyproject.toml          # Build/runtime metadata + scripts
├── Dockerfile              # Multi-stage or single-stage app image
├── docker-compose.yml      # Local runtime: app + optional redis/worker
├── Makefile                # Shortcuts: install, test, lint, update-deps
├── README.md
├── .env.example
├── .env                    # Local-only; git-ignored
├── LICENSE
└── project-registry.json   # Project self-reference / resume point
```

## Application
```
└── src/
    └── streamdoc/
        ├── __init__.py
        ├── config.py          # Settings/env/schema
        ├── db.py              # SQLAlchemy engine/session
        ├── models/            # Domain models
        │   ├── __init__.py
        │   ├── channel.py
        │   ├── video.py
        │   ├── preset.py
        │   └── output.py
        ├── core/
        │   ├── youtube.py     # yt-dlp driver + YoutubeExplode metadata fallback
        │   ├── channel.py     # Channel resolution / link normalization
        │   ├── fetch.py       # New-video window filter / incremental fetch
        │   ├── transcript.py  # Native + Whisper fallback pipeline
        │   ├── media.py       # ffmpeg frame extraction pipelines
        │   ├── dedupe.py      # Perceptual hash + similarity reduction
        │   ├── pdf.py         # ReportLab/WeasyPrint PDF builder
        │   └── prompts.py     # Preset loading / templating
        ├── integrations/
        │   ├── __init__.py
        │   └── notebooklm.py  # Handoff to user-provided MCP/package
        ├── scheduler.py       # APScheduler / schedule manager
        └── updater.py         # Multi-track updater (yt-dlp, ffmpeg, whisper)
```

## API / UI
```
src/streamdoc/
├── api/
│   ├── __init__.py
│   ├── app.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── channels.py
│   │   ├── lists.py
│   │   ├── presets.py
│   │   ├── runs.py
│   │   └── integrations.py
│   └── dependencies.py
```

## Assets / Reference
```
├── assets/
│   ├── prompts/           # Preset YAML/JSON/MD templates
│   │   └── finance.md
│   │   └── technology.md
│   └── scripts/
│       └── bootstrap.sh   # First-run setup: deps, whisper, ffmpeg check
```

## Documentation (reference material we depend on)
```
├── docs/
│   ├── architecture.md
│   ├── runbook.md
│   └── ffmpeg-cheatsheet.md   # Mirrored from rendi-api/ffmpeg-cheatsheet
```

## Tests
```
tests/
├── conftest.py
├── test_youtube.py
├── test_transcript.py
├── test_media.py
├── test_dedupe.py
└── test_updater.py
```

## Scripts / Ops
```
scripts/
├── init-db.sh
└── seed-demo-data.sh
```

## Runtime data (not committed)
```
data/
├── State/                  # DB and scheduler state
├── Media/                  # Downloaded video/audio/frames
├── Outputs/                # Built PDFs
└── Models/                 # Whisper model cache / artifacts
```

## Hermes agent artifacts
```
.hermes/
└── plans/                  # Session plan files
```

```
