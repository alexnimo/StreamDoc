# Social Sentiment Pipeline

StreamDoc's social sentiment pipeline collects posts from multiple platforms,
deduplicates them, builds a single unified Markdown/PDF report containing all
posts with their metadata and images, and dispatches it to configured
destinations (agy, NotebookLM).

---

## Architecture

```
  Preset
  ┌─────────────────────────────────┐
  │ social_sources: [...]           │
  │ social_lookback_hours: 24       │
  │ social_max_posts: 500           │
  │ skip_processed: true            │
  └─────────────┬───────────────────┘
                │
    ┌───────────▼───────────┐
    │   fetch._run_social() │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐     ┌──────────────────┐
    │ For each source:      │────►│ SocialSource      │
    │ {platform, identifier,│     │ .collect(         │
    │  max_posts}           │     │   preset,         │
    │                       │     │   descriptor,     │
    │  + DedupStore         │     │   cutoff,         │
    │                       │     │   dedup_store,    │
    │                       │     │   max_posts,      │
    │                       │     │   skip_processed  │
    └───────────┬───────────┘     │ ) → SocialPost[]  │
                │                 └────────┬─────────┘
                ▼                          │
    ┌───────────────────────┐              │
    │ SocialPost[] deduped  │◄─────────────┘
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │ build_unified_social  │
    │ _outputs              │
    │ → social-<date>.md    │
    │ → social-<date>.pdf   │
    │   (all platforms,     │
    │    all posts, images) │
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │ _send_reports()       │
    │ → agy or notebooklm   │
    └───────────────────────┘
```

---

## Schema

### SocialSourceConfig (preset model)

```python
@dataclass
class SocialSourceConfig:
    platform: str      # "reddit" | "stocktwits" | "x"
    identifier: str    # platform-specific descriptor (see below)
    max_posts: int | None = None  # per-source override
```

Stored in preset as `social_sources` — a JSON array of these objects.

### SocialPost (dataclass)

```python
@dataclass
class SocialPost:
    platform: str            # "reddit" | "stocktwits" | "x"
    source_id: str           # platform-native post ID
    author: str              # username / display name
    text: str                # post body text
    published_at: datetime   # UTC timestamp
    url: str | None          # permalink
    images: list[str]        # downloaded image file paths
```

### Dedup Key Format

The `SocialPostStore` deduplicates by: `{platform}:{source_id}`.

If a post with the same platform + source_id already exists in the store,
it is silently skipped, even if the cutoff would accept it. This prevents
duplicates across multiple collectors for the same platform.

---

## Descriptor Formats (by Platform)

### Reddit (`reddit`)

| Descriptor Pattern | Example | Action |
|---|---|---|
| `r/<subreddit>` | `r/wallstreetbets` | Hot posts from subreddit |
| `r/<subreddit>/new` | `r/stocks/new` | New posts from subreddit |
| `r/<subreddit>/top` | `r/options/top` | Top posts from subreddit |

Data source: Reddit public JSON API at `https://www.reddit.com/r/{name}/hot/.json`

### Stocktwits (`stocktwits`)

| Descriptor Pattern | Example | Action |
|---|---|---|
| `$SYMBOL` | `$AAPL` | Recent posts about symbol |
| `@user` | `@trader42` | Recent posts by user |
| `trending` | `trending` | Currently trending symbols |

Data source: Stocktwits public API at `https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json`

### X / Twitter (`x`)

| Descriptor Pattern | Example | Action |
|---|---|---|
| `@username` | `@elonmusk` | User timeline |
| `list/<id>` | `list/12345` | List timeline |
| `search/<query>` | `search/AAPL` | Search tweets |
| `<tweet_id>` | `123456` | Single tweet by ID |

Data source: `twitter-cli` npm package (see [Open Source Attribution](#open-source-attribution)).

The `x` collector shells out to the `twitter-cli` binary via subprocess with
`--json` output, matching the existing yt-dlp subprocess pattern used by the
video pipeline. If `twitter-cli` is not installed, the collector raises
`XSourceNotInstalledError` with an installation hint.

For high-volume sources, the X collector paginates list timelines using the
`nextCursor` field returned by `twitter-cli` and stops as soon as the lookback
window is exhausted. `max_posts` is treated as a target cap across all pages
(rather than a per-page limit) and is hard-capped at `1000` per source to
prevent runaway collection.

---

## Report Format

The unified social report is written to:

```
output_root/<preset.name>/social-<YYYY-MM-DD>.md
output_root/<preset.name>/social-<YYYY-MM-DD>.pdf
```

The report is organized into **one dedicated section per platform**, so each
platform reads as its own standalone report within the unified document.
Every platform section follows the same document pattern.

Structure:
- Title: `# Social Report — <preset.name>`
- Global summary: total post count, total image count, platforms with posts,
  generation timestamp
- Preset instructions / prompt (if configured)
- For each platform that returned at least one post (in stable display order:
  X / Twitter, Reddit, Stocktwits, then any future platforms alphabetically):
  - Section header: `## <Platform Label> Report`
  - Per-platform summary: post count, image count, platform identifier
  - Each post: `### Post {idx}: @author on PLATFORM — YYYY-MM-DD HH:MM UTC`
    - Author, platform, publish time, post ID
    - Source link
    - Full text
    - Images embedded directly into the Markdown (base64) and scaled into the PDF

**Empty platforms are omitted entirely.** If a platform collects zero posts
(e.g. X returned nothing but Reddit did), no section is emitted for that
platform, and the report only contains sections for platforms with posts.
When *all* platforms collect zero posts, no report is built and nothing is
dispatched to destinations (agy / NotebookLM) — no tokens or compute are
spent on an empty run.

---

## Image Download

When a post references media (images on X/Twitter, previews on Stocktwits), the
collector downloads them to:

```
media_root/social/<platform>/<source_id>/<filename>
```

These downloaded files are cleaned up by `cleanup_social()` when they exceed
the retention threshold (default: 48 hours).

---

## Cleanup

`cleanup_social()` in `src/streamdoc/core/cleanup.py` removes:

1. **SocialPost records** older than `social_retention_hours` (default: 48h)
   from the database.
2. **Downloaded media directories** under `media_root/social/` whose mtime
   exceeds the retention threshold.

Wired into the aggregate `run_cleanup()` function alongside media, reports,
and NotebookLM cleanup.

---

## Destination Dispatch

After the report is generated, `_send_reports()` in `fetch.py` dispatches
via the configured preset destinations:

- **agy (Antigravity)**: Uploads the report via `agy upload`. Uses the
  `AgyCLI` tool from `streamdoc.integrations.cli_tools`, following the
  same yt-dlp-style subprocess pattern.
- **NotebookLM**: Uploads the report content to a NotebookLM notebook for
  AI-generated analysis. Handled by the existing NotebookLM integration
  in `streamdoc.integrations.notebooklm`.

---

## Open Source Attribution

StreamDoc's social sentiment pipeline uses the following open-source
libraries and tools. We thank their maintainers for their work.

### twitter-cli

**twitter-cli** — A command-line Twitter client that handles authentication
and anti-detection, producing structured JSON output suitable for automation.
([https://github.com/jackwener/opencli](https://github.com/jackwener/opencli))

`twitter-cli` is a component of the **opencli** project by jackwener. It is
used via subprocess (the `twitter-cli` binary must be installed separately
via `npm install -g twitter-cli` or `npx twitter-cli`).

### Reddit Public JSON API

StreamDoc accesses Reddit content via its **public JSON API** at
`https://www.reddit.com/*/.json`. No library is used — HTTP requests
are made directly via Python's stdlib `urllib.request`.

- Reddit: [https://www.reddit.com](https://www.reddit.com)

### Stocktwits Public API

StreamDoc accesses Stocktwits content via their **public API** at
`https://api.stocktwits.com/api/2/`. No library is used — HTTP requests
are made directly via Python's stdlib `urllib.request`.

- Stocktwits: [https://stocktwits.com](https://stocktwits.com)

### Python Standard Library

The pipeline relies on Python's standard library (`urllib.request`,
`subprocess`, `json`, `datetime`, `pathlib`, `shutil`) — no external
HTTP or CLI abstraction dependencies were introduced.

---

## Adding a New Platform

1. Create a new collector file (`src/streamdoc/integrations/social/<name>.py`)
   implementing the `SocialSource` protocol:
   ```python
   @dataclass
   class SocialSource:
       def collect(
           self,
           preset,
           source_descriptor,
           cutoff,
           dedup_store,
           max_posts=None,
           skip_processed=True,
       ) -> list[SocialPost]: ...
   ```
2. Register it in `src/streamdoc/integrations/social/__init__.py`:
   ```python
   from streamdoc.integrations.social.<name> import <Name>Source
   register_source("<platform>", <Name>Source)
   ```
3. Update this document with the new platform's descriptor formats.
4. Add tests in `tests/test_social_collectors.py`.
