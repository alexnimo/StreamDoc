# POR-11 T11: Sample social preset YAML + agy sample templates + docs Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Create a shipped sample social preset YAML, shipped sample agy templates (presentation + JSON export), the `config/presets/` directory, and documentation so users know how to author a social preset and an agy template.

**Architecture:** This is a documentation/content task. Create tracked sample files in `assets/` that seed to `config/` on first run (mirroring the existing `assets/prompts/notebooklm/` → `config/prompts/notebooklm/` pattern). Update `.gitignore` to track the sample preset while ignoring user presets. Add a short docs file explaining the two preset types and authoring guide.

**Tech Stack:** YAML, Markdown, existing preset loading infrastructure.

---

### Task 1: Create `config/presets/` directory with `.gitkeep`

**Objective:** Create the presets directory so `autoload_presets()` can find shipped sample presets.

**Files:**
- Create: `config/presets/.gitkeep`

**Step 1: Create directory and gitkeep**

```bash
mkdir -p /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/presets
touch /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/presets/.gitkeep
```

**Step 2: Verify directory exists**

```bash
ls -la /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/presets/
```
Expected: `.gitkeep` file present.

**Step 3: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add config/presets/.gitkeep
git commit -m "chore: add config/presets directory for sample presets"
```

---

### Task 2: Create shipped sample social preset YAML

**Objective:** Create `config/presets/sample-social.yaml` demonstrating all social preset fields.

**Files:**
- Create: `config/presets/sample-social.yaml`

**Step 1: Write the sample preset YAML**

```yaml
name: "sample-social"
preset_type: "social"
social_sources:
  - platform: "reddit"
    identifier: "finance"
    max_posts: 50
  - platform: "stocktwits"
    identifier: "AAPL"
    max_posts: 100
social_lookback_hours: 12
social_max_posts: 200
outputs: "pdf,markdown,notebooklm,agy"
cli_tool: "agy"
cli_tool_template: "presentation"
schedule: "interval:43200"
active: true
retention_enabled: true
file_retention_hours: 24
notebook_retention_hours: 168
```

**Step 2: Write to file**

```bash
cat > /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/presets/sample-social.yaml << 'EOF'
name: "sample-social"
preset_type: "social"
social_sources:
  - platform: "reddit"
    identifier: "finance"
    max_posts: 50
  - platform: "stocktwits"
    identifier: "AAPL"
    max_posts: 100
social_lookback_hours: 12
social_max_posts: 200
outputs: "pdf,markdown,notebooklm,agy"
cli_tool: "agy"
cli_tool_template: "presentation"
schedule: "interval:43200"
active: true
retention_enabled: true
file_retention_hours: 24
notebook_retention_hours: 168
EOF
```

**Step 3: Verify file content**

```bash
cat /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/presets/sample-social.yaml
```

**Step 4: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add config/presets/sample-social.yaml
git commit -m "feat: add sample social preset YAML"
```

---

### Task 3: Update `.gitignore` to track sample preset but ignore user presets

**Objective:** Adjust `.gitignore` so `config/presets/sample-social.yaml` is tracked while user-created presets stay ignored.

**Files:**
- Modify: `.gitignore` (lines 22-26)

**Step 1: Update .gitignore**

Replace:
```
# ── User config (presets, prompts — gitignored, not committed) ────────
# Reason: user-created presets and prompts live in config/ so they never
# pollute the tracked repo. Sample prompts in assets/prompts/ ARE tracked.
config/presets/
config/prompts/
```

With:
```
# ── User config (presets, prompts — gitignored, not committed) ────────
# Reason: user-created presets and prompts live in config/ so they never
# pollute the tracked repo. Sample prompts in assets/prompts/ ARE tracked.
# Shipped sample presets in config/presets/sample-*.yaml ARE tracked.
config/presets/*
!config/presets/sample-*.yaml
config/prompts/
```

**Step 2: Apply patch**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
patch .gitignore << 'PATCH'
--- .gitignore
+++ .gitignore
@@ -22,7 +22,8 @@
 # ── User config (presets, prompts — gitignored, not committed) ────────
 # Reason: user-created presets and prompts live in config/ so they never
 # pollute the tracked repo. Sample prompts in assets/prompts/ ARE tracked.
-config/presets/
+config/presets/*
+!config/presets/sample-*.yaml
 config/prompts/
PATCH
```

**Step 3: Verify change**

```bash
cat /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/.gitignore | head -30
```

**Step 4: Test git tracking**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git status
```
Expected: `config/presets/sample-social.yaml` shows as new file, not ignored.

**Step 5: Commit**

```bash
git add .gitignore config/presets/sample-social.yaml
git commit -m "chore: update .gitignore to track sample presets"
```

---

### Task 4: Create shipped sample agy template: presentation.yaml

**Objective:** Create `assets/templates/agy/presentation.yaml` that instructs agy to build a presentation from aggregated social sentiment report.

**Files:**
- Create: `assets/templates/agy/presentation.yaml`

**Step 1: Write the presentation template**

```yaml
name: "presentation"
description: "Build a social sentiment presentation from aggregated report"
target_types:
  - web_video_presentation
prompt: |
  You are a senior web presentation engineer. Produce a self-contained `presentation.html`
  with a fixed 16:9 stage that scales to the viewport from the provided social sentiment
  analysis report.

  Source material: {context}
  Target audience: {audience}

  Requirements:
  - Turn the social sentiment data into a click-driven sequence of full-screen beats
  - Each beat focuses on one key insight (overall sentiment, top tickers, platform breakdown,
    trending topics, risk signals)
  - Embed any provided charts or visualizations as `<img>` or inline SVG
  - Use a clean, professional visual style appropriate for financial content
  - Avoid generic AI clichés (purple-pink gradients, emoji-as-icons, default Inter)
  - Optionally write a concise `script.md` narration outline
  - Emit `Artifact: presentation.html` on stdout and exit 0 when done

  Structure suggestion:
  1. Title slide: "Social Sentiment Report — {date_range}"
  2. Executive summary: overall sentiment score, post volume, top platforms
  3. Platform breakdown: Reddit vs StockTwits volume and sentiment
  4. Top tickers mentioned with sentiment distribution
  5. Trending topics / keywords
  6. Risk signals (extreme sentiment, manipulation indicators)
  7. Methodology & data sources
variables:
  context: "Aggregated social sentiment analysis from Reddit and StockTwits"
  audience: "Financial analysts and portfolio managers"
```

**Step 2: Write to file**

```bash
cat > /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/assets/templates/agy/presentation.yaml << 'EOF'
name: "presentation"
description: "Build a social sentiment presentation from aggregated report"
target_types:
  - web_video_presentation
prompt: |
  You are a senior web presentation engineer. Produce a self-contained `presentation.html`
  with a fixed 16:9 stage that scales to the viewport from the provided social sentiment
  analysis report.

  Source material: {context}
  Target audience: {audience}

  Requirements:
  - Turn the social sentiment data into a click-driven sequence of full-screen beats
  - Each beat focuses on one key insight (overall sentiment, top tickers, platform breakdown,
    trending topics, risk signals)
  - Embed any provided charts or visualizations as `<img>` or inline SVG
  - Use a clean, professional visual style appropriate for financial content
  - Avoid generic AI clichés (purple-pink gradients, emoji-as-icons, default Inter)
  - Optionally write a concise `script.md` narration outline
  - Emit `Artifact: presentation.html` on stdout and exit 0 when done

  Structure suggestion:
  1. Title slide: "Social Sentiment Report — {date_range}"
  2. Executive summary: overall sentiment score, post volume, top platforms
  3. Platform breakdown: Reddit vs StockTwits volume and sentiment
  4. Top tickers mentioned with sentiment distribution
  5. Trending topics / keywords
  6. Risk signals (extreme sentiment, manipulation indicators)
  7. Methodology & data sources
variables:
  context: "Aggregated social sentiment analysis from Reddit and StockTwits"
  audience: "Financial analysts and portfolio managers"
EOF
```

**Step 3: Verify file**

```bash
cat /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/assets/templates/agy/presentation.yaml
```

**Step 4: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add assets/templates/agy/presentation.yaml
git commit -m "feat: add sample agy presentation template"
```

---

### Task 5: Create shipped sample agy template: json_export.yaml

**Objective:** Create `assets/templates/agy/json_export.yaml` that instructs agy to emit JSON for 3rd-party consumption.

**Files:**
- Create: `assets/templates/agy/json_export.yaml`

**Step 1: Write the JSON export template**

```yaml
name: "json_export"
description: "Emit structured JSON from social sentiment report for 3rd-party consumption"
target_types:
  - web_design_engineer
prompt: |
  You are a data engineer. Produce a clean, well-structured JSON artifact from the
  provided social sentiment analysis report.

  Source material: {context}
  Target audience: {audience}

  Requirements:
  - Output a single JSON object to `artifact/sentiment_report.json`
  - Include all key metrics: overall sentiment, post counts, platform breakdown,
    ticker mentions with sentiment scores, trending topics, risk signals
  - Use consistent field naming (snake_case), include units where applicable
  - Include metadata: generated_at, date_range, sources, methodology
  - Ensure valid JSON (no trailing commas, proper escaping)
  - Do not include any markdown formatting or explanatory text in the output
  - Emit `Artifact: artifact/sentiment_report.json` on stdout and exit 0 when done

  Expected JSON structure:
  {
    "metadata": {
      "generated_at": "ISO8601",
      "date_range": "start..end",
      "sources": ["reddit", "stocktwits"],
      "methodology": "VADER/FinBERT sentiment on post text"
    },
    "summary": {
      "total_posts": 150,
      "overall_sentiment": 0.12,
      "sentiment_label": "slightly_positive"
    },
    "platforms": {
      "reddit": {"posts": 50, "sentiment": 0.08},
      "stocktwits": {"posts": 100, "sentiment": 0.14}
    },
    "tickers": [
      {"symbol": "AAPL", "mentions": 45, "sentiment": 0.23, "sentiment_label": "positive"},
      {"symbol": "TSLA", "mentions": 38, "sentiment": -0.11, "sentiment_label": "negative"}
    ],
    "trending_topics": [
      {"topic": "earnings", "mentions": 32, "sentiment": 0.15},
      {"topic": "fed_rate", "mentions": 28, "sentiment": -0.05}
    ],
    "risk_signals": [
      {"type": "extreme_sentiment", "ticker": "GME", "score": 0.89, "description": "Unusually high positive sentiment"}
    ]
  }
variables:
  context: "Aggregated social sentiment analysis from Reddit and StockTwits"
  audience: "Data engineers and API consumers"
```

**Step 2: Write to file**

```bash
cat > /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/assets/templates/agy/json_export.yaml << 'EOF'
name: "json_export"
description: "Emit structured JSON from social sentiment report for 3rd-party consumption"
target_types:
  - web_design_engineer
prompt: |
  You are a data engineer. Produce a clean, well-structured JSON artifact from the
  provided social sentiment analysis report.

  Source material: {context}
  Target audience: {audience}

  Requirements:
  - Output a single JSON object to `artifact/sentiment_report.json`
  - Include all key metrics: overall sentiment, post counts, platform breakdown,
    ticker mentions with sentiment scores, trending topics, risk signals
  - Use consistent field naming (snake_case), include units where applicable
  - Include metadata: generated_at, date_range, sources, methodology
  - Ensure valid JSON (no trailing commas, proper escaping)
  - Do not include any markdown formatting or explanatory text in the output
  - Emit `Artifact: artifact/sentiment_report.json` on stdout and exit 0 when done

  Expected JSON structure:
  {
    "metadata": {
      "generated_at": "ISO8601",
      "date_range": "start..end",
      "sources": ["reddit", "stocktwits"],
      "methodology": "VADER/FinBERT sentiment on post text"
    },
    "summary": {
      "total_posts": 150,
      "overall_sentiment": 0.12,
      "sentiment_label": "slightly_positive"
    },
    "platforms": {
      "reddit": {"posts": 50, "sentiment": 0.08},
      "stocktwits": {"posts": 100, "sentiment": 0.14}
    },
    "tickers": [
      {"symbol": "AAPL", "mentions": 45, "sentiment": 0.23, "sentiment_label": "positive"},
      {"symbol": "TSLA", "mentions": 38, "sentiment": -0.11, "sentiment_label": "negative"}
    ],
    "trending_topics": [
      {"topic": "earnings", "mentions": 32, "sentiment": 0.15},
      {"topic": "fed_rate", "mentions": 28, "sentiment": -0.05}
    ],
    "risk_signals": [
      {"type": "extreme_sentiment", "ticker": "GME", "score": 0.89, "description": "Unusually high positive sentiment"}
    ]
  }
variables:
  context: "Aggregated social sentiment analysis from Reddit and StockTwits"
  audience: "Data engineers and API consumers"
EOF
```

**Step 3: Verify file**

```bash
cat /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/assets/templates/agy/json_export.yaml
```

**Step 4: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add assets/templates/agy/json_export.yaml
git commit -m "feat: add sample agy JSON export template"
```

---

### Task 6: Create `config/templates/agy/.gitkeep` for seeded directory

**Objective:** Create the target directory that receives seeded templates on first run.

**Files:**
- Create: `config/templates/agy/.gitkeep`

**Step 1: Create directory and gitkeep**

```bash
mkdir -p /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/templates/agy
touch /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/templates/agy/.gitkeep
```

**Step 2: Verify**

```bash
ls -la /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/config/templates/agy/
```

**Step 3: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add config/templates/agy/.gitkeep
git commit -m "chore: add config/templates/agy directory for seeded templates"
```

---

### Task 7: Create documentation: `docs/social-presets.md`

**Objective:** Write documentation explaining the two preset types, how to author a social preset YAML, the agy template seeding flow, and that paid APIs are out of scope.

**Files:**
- Create: `docs/social-presets.md`

**Step 1: Write the documentation**

```markdown
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
```

**Step 2: Write to file**

```bash
cat > /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/docs/social-presets.md << 'EOF'
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
EOF
```

**Step 3: Verify file**

```bash
cat /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/docs/social-presets.md
```

**Step 4: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add docs/social-presets.md
git commit -m "docs: add social-presets.md with authoring guide"
```

---

### Task 8: Add README cross-reference

**Objective:** Add a brief note in README.md pointing to the new social-presets.md doc.

**Files:**
- Modify: `README.md` (around line 370-376, Documentation section)

**Step 1: Find the Documentation section**

```bash
grep -n "## Documentation" /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/README.md
```

**Step 2: Add link to social-presets.md**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
patch README.md << 'PATCH'
--- README.md
+++ README.md
@@ -370,6 +370,7 @@
 ## Documentation
 
 - [Product Requirements](docs/PRD.md) — specs and acceptance criteria
+- [Social Presets & agy Templates](docs/social-presets.md) — authoring guide for social presets and agy templates
 - [System Architecture](.agents/SYSTEM.md) — module map and design decisions
 - [Integrations & Auth](docs/integrations-auth.md) — NotebookLM auth and secret boundary
 - [Design Brief](docs/design-brief.md) — UI/UX direction
PATCH
```

**Step 3: Verify change**

```bash
grep -A 5 "## Documentation" /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04/README.md
```

**Step 4: Commit**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git add README.md
git commit -m "docs: add social-presets.md link to README"
```

---

### Task 9: Verify preset loading works

**Objective:** Test that the sample preset loads correctly via `autoload_presets()`.

**Files:** None (verification only)

**Step 1: Run a quick Python test**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
uv run python -c "
from streamdoc.presets import autoload_presets
presets = autoload_presets()
for p in presets:
    print(f'Loaded: {p.name} (type={p.preset_type})')
    print(f'  social_sources: {p.social_sources}')
    print(f'  social_lookback_hours: {p.social_lookback_hours}')
    print(f'  outputs: {p.outputs}')
    print(f'  cli_tool: {p.cli_tool}')
    print(f'  cli_tool_template: {p.cli_tool_template}')
    print(f'  schedule: {p.schedule}')
"
```

**Expected output:**
```
Loaded: sample-social (type=social)
  social_sources: reddit,finance,50,stocktwits,AAPL,100
  social_lookback_hours: 12
  outputs: pdf,markdown,notebooklm,agy
  cli_tool: agy
  cli_tool_template: presentation
  schedule: interval:43200
```

**Note:** The `social_sources` is stored as comma-separated string in SQLite (see `presets.py:34-35`). The list format in YAML is converted on load.

**Step 2: If test passes, task is complete. If not, debug and fix.**

---

### Task 10: Final verification and commit summary

**Objective:** Verify all acceptance criteria are met.

**Checklist:**
- [ ] `config/presets/` directory exists with `.gitkeep`
- [ ] `config/presets/sample-social.yaml` exists and has all required fields
- [ ] `assets/templates/agy/presentation.yaml` exists
- [ ] `assets/templates/agy/json_export.yaml` exists
- [ ] `config/templates/agy/.gitkeep` exists
- [ ] `docs/social-presets.md` exists with all required sections
- [ ] `.gitignore` updated to track `sample-*.yaml` but ignore other presets
- [ ] README.md links to `docs/social-presets.md`
- [ ] `autoload_presets()` loads the sample preset correctly

**Step 1: Run final verification**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
git status
ls -la config/presets/
ls -la assets/templates/agy/
ls -la config/templates/agy/
ls -la docs/social-presets.md
```

**Step 2: Run tests to ensure nothing broke**

```bash
cd /c/Users/alexn/projects/StreamDoc/.worktrees/t_95dc0e04
uv run pytest tests/ -m "not live" -q --tb=short
```
Expected: All 190 tests pass (same as parent task completion).

**Step 3: Final commit summary**

All tasks complete. The implementation provides:
- Shipped sample social preset demonstrating all POR-11 fields
- Two shipped agy templates (presentation + JSON export)
- Directory structure for preset/template seeding
- Documentation for users to author their own presets
- Proper gitignore rules separating shipped samples from user data