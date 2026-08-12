# Social Presets & agy Templates

StreamDoc supports two preset types:

## 1. YouTube Presets (`preset_type: youtube`)

The original preset type for processing YouTube channels. Downloads videos, extracts transcripts, captures frames, and generates Markdown/PDF reports. Can optionally push to NotebookLM for AI generation.

**Key fields:**
- `channel_list_id` or `channel_names` — channels to process
- `lookback_hours`, `max_videos` — time window and video limit
- `outputs` — `pdf,markdown,notebooklm` (comma-separated)
- `notebooklm_kind`, `notebooklm_prompt_template` — NotebookLM generation options

## 2. Social Presets (`preset_type: social`)

New in POR-11. Fetches posts from social platforms (Reddit, StockTwits, X) for sentiment analysis. Generates aggregated reports and can dispatch to agy (Antigravity) for presentation or JSON export.

**Key fields:**
- `social_sources` — list of source objects:
  - `platform`: `reddit` | `stocktwits` | `x`
  - `identifier`: subreddit name (e.g. `finance`), ticker symbol (e.g. `AAPL`), or X query
  - `max_posts`: max posts per source (optional, defaults to `social_max_posts`)
- `social_lookback_hours` — time window to fetch (default: 12)
- `social_max_posts` — global max posts across all sources (default: 200)
- `outputs` — `pdf,markdown,notebooklm,agy` (comma-separated)
- `cli_tool` — `agy` (required for agy output)
- `cli_tool_template` — agy template name: `presentation` | `json_export`
- `schedule` — e.g. `interval:43200` (12 hours)

### Example Social Preset

```yaml
name: "my-social-preset"
preset_type: "social"
social_sources:
  - platform: "reddit"
    identifier: "wallstreetbets"
    max_posts: 100
  - platform: "stocktwits"
    identifier: "TSLA"
    max_posts: 50
social_lookback_hours: 24
social_max_posts: 200
outputs: "pdf,markdown,agy"
cli_tool: "agy"
cli_tool_template: "presentation"
schedule: "interval:43200"
active: true
```

## agy Template Seeding Flow

StreamDoc ships sample agy templates in `assets/templates/agy/` (tracked in git):
- `presentation.yaml` — builds a web presentation from the sentiment report
- `json_export.yaml` — emits structured JSON for 3rd-party consumption

On first run (or when `config/templates/agy/` is empty), these are **copied** to:
```
config/templates/agy/
```

This mirrors the NotebookLM prompt seeding (`assets/prompts/notebooklm/` → `config/prompts/notebooklm/`).

**After seeding:**
- **User edits and new templates** go in `config/templates/agy/` — **never committed** (gitignored)
- **Shipped samples** in `assets/templates/agy/` remain read-only references
- To add a new template for all users: add `*.yaml` to `assets/templates/agy/` and commit

## Paid APIs: Out of Scope

The social sentiment pipeline uses **public/free endpoints only**:
- Reddit: public JSON endpoints (no auth required for basic access)
- StockTwits: public API (rate-limited, no auth for basic use)
- X/Twitter: public search (highly rate-limited; consider paid API for production)

**No paid API keys are required or supported** in the shipped configuration. Operators needing higher rate limits or full-archive search must integrate their own API clients externally.

## Quick Start

1. Copy the sample preset:
   ```bash
   cp config/presets/sample-social.yaml config/presets/my-preset.yaml
   ```
2. Edit `config/presets/my-preset.yaml` with your sources
3. Run it:
   ```bash
   uv run streamdoc fetch my-preset
   ```
4. Or schedule it:
   ```bash
   uv run streamdoc schedule add my-preset "interval:43200"
   ```

The agy templates will be seeded automatically on first run. Check `config/templates/agy/` for your local copies.