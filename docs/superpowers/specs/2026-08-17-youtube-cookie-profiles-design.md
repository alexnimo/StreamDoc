# YouTube Side-Loaded Cookie Profiles

**Date:** 2026-08-17
**Status:** Approved (pending implementation)
**Related:** POR-27 (agy integration), existing yt-dlp bypass system, NotebookLM/Social auth patterns

## Problem

YouTube IP-blocks DASH/HTTPS media downloads (returns HTTP 403 on format URLs)
for hosts that download heavily. The current bypass system (PO token + HLS
fallback) keeps downloads working but at reduced quality (HLS is typically
480p). The durable fix is authenticated cookies, but using the operator's real
browser profile risks getting their actual YouTube account banned.

Additionally, download failures are invisible in the UI — the `videos` table
records `media_status=failed` with no error detail, and there is no path to
solve YouTube CAPTCHA challenges that could unblock the IP.

## Solution

A side-loaded cookie profile system: isolated Playwright browser contexts that
the operator signs into YouTube with throwaway/burner accounts. Cookies are
exported to Netscape jar files and passed to yt-dlp. Profiles can be created,
switched, and deleted from the UI without ever touching the operator's real
browser. A CAPTCHA-solve flow re-opens a profile's browser context to lift IP
blocks. Per-video error tracking surfaces download failures in the UI.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Login flow | Playwright persistent context | Matches NotebookLM/Social pattern; never touches real browser |
| Profile switching | Manual | Explicit user control; no auto-rotation risk |
| Cookie delivery | Netscape jar file | Fast downloads, no browser process needed at download time |
| Bypass integration | Simple + Advanced mode | Simple = single mode; Advanced = ordered, reorable fallback chain |
| Health tracking | Passive status badge | healthy/flagged/unknown based on download errors; no active probing |
| CAPTCHA scope | Per-profile action | Profile is the browser context container; login not required for CAPTCHA |
| Error tracking | Per-video error column | Minimal schema change; immediate context in video list |
| Storage | File-based (manifest JSON) | Matches existing auth pattern; no DB migration for auth state |

## Architecture

### Module Structure

New module under `src/streamdoc/integrations/youtube/`, mirroring the existing
`notebooklm/` and `social/` integration layout:

```
src/streamdoc/integrations/youtube/
├── __init__.py
├── profile_manager.py     # YouTubeProfileManager — Playwright login, cookie export, CRUD, health
├── playwright_login.py     # Subprocess Playwright login/CAPTCHA (matches notebooklm pattern)
└── cookie_export.py        # Playwright cookies → Netscape jar conversion
```

### File-Based Storage

No database for auth state (matches NotebookLM/Social convention). All profile
metadata lives in a manifest JSON file:

```
data/integrations/youtube/
├── profiles_manifest.json          # Profile metadata + active profile pointer
├── profiles/
│   ├── burner1/
│   │   ├── browser_profile/        # Playwright persistent context dir
│   │   └── cookies.txt             # Exported Netscape jar (used by yt-dlp)
│   ├── burner2/
│   │   ├── browser_profile/
│   │   └── cookies.txt
│   └── ...
```

**`profiles_manifest.json` structure:**

```json
{
  "active_profile": "burner1",
  "profiles": {
    "burner1": {
      "name": "burner1",
      "status": "healthy",
      "created_at": "2026-08-17T12:00:00Z",
      "last_used": "2026-08-18T05:30:00Z",
      "last_error": null,
      "last_error_category": null,
      "error_count": 0
    }
  }
}
```

Status values: `healthy` (recent downloads succeeded), `flagged` (recent 403
or bot-detection error), `unknown` (never used or cleared).

Manifest updates are atomic (write to temp file, rename) to avoid corruption
from concurrent download workers.

## Components

### YouTubeProfileManager (`profile_manager.py`)

Core class managing the full profile lifecycle.

**Profile CRUD:**
- `list_profiles() -> list[ProfileInfo]` — reads manifest, returns all profiles with status
- `create_profile(name: str) -> ProfileInfo` — creates manifest entry + empty profile dir
- `delete_profile(name: str)` — removes manifest entry + `shutil.rmtree(profile_dir)`
- `get_active_profile() -> ProfileInfo | None` — returns active profile or None
- `activate_profile(name: str)` — sets `active_profile` in manifest
- `clear_flag(name: str)` — resets status to "healthy", clears last_error

**Playwright login (subprocess, non-blocking):**
- `login(name: str) -> str` — launches Playwright persistent context at
  `profiles/{name}/browser_profile/`, navigates to `https://www.youtube.com`,
  waits for user to sign in. Returns a job ID for status polling.
- Process-wide lock (`_LOGIN_LOCK`) prevents concurrent logins.
- Runs in subprocess via `uv run python -m streamdoc.integrations.youtube.playwright_login`
  to avoid blocking the API server.
- Success condition: YouTube session cookies present (SID, HSID, APISID, SAPISID).
- On success: exports cookies to `profiles/{name}/cookies.txt` via `cookie_export.py`.

**CAPTCHA solve (per-profile action):**
- `solve_captcha(name: str) -> str` — same Playwright persistent context, navigates
  to `https://www.youtube.com`, waits for the CAPTCHA challenge to disappear
  (user solves it in the opened browser). Returns a job ID for status polling.
- Reuses the same subprocess + lock infrastructure as `login()`.
- Does NOT require login — the profile is just a browser context container.
  The CAPTCHA itself is the human verification; post-CAPTCHA cookies lift the
  IP block even for unauthenticated sessions.
- On success: re-exports cookies to `cookies.txt`, clears the flag.

**Login status polling:**
- `get_login_status(job_id: str) -> LoginStatusResponse` — returns pending/completed/failed/timeout
- Status stored in a module-level dict (in-memory, lost on restart — acceptable
  since login is a short-lived interactive operation)

**Cookie export** (`cookie_export.py`):
- `export_cookies_to_netscape(cookies: list[dict], output_path: Path)` — converts
  Playwright's cookie dict format to Netscape `.txt` format (yt-dlp `--cookiefile` format)
- Filters to YouTube/Google domains only (matches Social auth domain filtering)
- Called after both `login()` and `solve_captcha()`

**Health tracking (passive):**
- `mark_flagged(name: str, error: str, category: str)` — called by downloader
  when a download using this profile's cookies fails with 403/bot-detection.
  Sets status to "flagged", records last_error, increments error_count.
- `mark_used(name: str)` — called on successful download. Updates last_used,
  resets status to "healthy".
- Both update the manifest file atomically.

### Bypass Mode Integration

**New bypass mode: `cookie_profile`**

Added to the existing bypass mode enum: `po_token | cookie | cookies_from_browser | cookie_profile | default`.

When active, the downloader resolves the active profile's `cookies.txt` path
dynamically and passes it to yt-dlp via `--cookiefile` (same mechanism as
`cookie` mode, but the jar path comes from the profile manager).

**Simple mode** (existing UI, extended):
- Bypass mode dropdown gets `cookie_profile` as a new option
- When selected, a profile selector appears showing available profiles with status badges
- One mode, one profile

**Advanced mode** (new):
- Toggle switches from single-mode dropdown to an ordered fallback chain
- New setting: `yt_dlp_bypass_chain: str` — comma-separated ordered list, e.g.
  `"po_token,cookie_profile,hls"`
- Downloader tries each mode in order. On retriable failure (403, bot-detection,
  cookie DB lock), logs and continues to next mode. On success, stops.
- UI shows a drag-to-reorder list with add/remove. Available modes: `po_token`,
  `cookie_profile`, `cookie`, `cookies_from_browser`, `hls`, `default`
- `hls` in the chain maps to the web_safari HLS fallback already implemented

**New config settings** (`config.py`):
```python
yt_dlp_bypass_mode: str = "po_token"          # Simple mode (+cookie_profile option)
yt_dlp_bypass_chain: str = ""                  # Advanced mode — empty = disabled
yt_dlp_advanced_bypass_enabled: bool = False   # Toggle simple/advanced
```

**Downloader changes** (`download()` in `downloader.py`):
- If `yt_dlp_advanced_bypass_enabled` and `yt_dlp_bypass_chain` non-empty: iterate
  the chain, trying each mode. On retriable failure, log and continue. On success, stop.
- If advanced mode off: existing behavior (single mode + existing fallback + HLS fallback)
- `cookie_profile` mode resolution: calls `YouTubeProfileManager.get_active_profile()`,
  gets jar path, passes to yt-dlp as `--cookiefile`. If no active profile or jar missing,
  logs warning and fails (so the chain moves to next mode).
- Health hooks: after download with `cookie_profile`, call `mark_used()` on success
  or `mark_flagged()` on 403/bot-detection.

**Python API path** (`build_ydl_opts` / `_apply_bypass_opts`):
- New `cookie_profile` case in `_apply_bypass_opts`: resolves active profile jar,
  sets `opts["cookiefile"]`. Same as `cookie` mode but dynamic path resolution.

### Download Error Tracking

**Per-video error columns** (minimal schema change to `videos` table):
- `media_error: str | None` — raw yt-dlp error message (tail 500 chars)
- `media_error_category: str | None` — classified category (`http_403`,
  `bot_detection`, `cookie_db_locked`, etc.)

**Where errors get recorded:**
In `src/streamdoc/core/fetch.py` `_download_media()`, after download failure:
```python
vmd.media_status = "failed"
vmd.media_error = result.stderr[-500:]
vmd.media_error_category = classify_download_error(result.stderr)
```
On successful download, both fields cleared to `None`.

**Migration:**
SQLite `ALTER TABLE videos ADD COLUMN` — two nullable columns. No backfill
needed (existing rows get NULL). Applied via existing migration mechanism on
startup.

**API exposure:**
Existing videos API endpoints serialize the `videos` model automatically. No
new routes needed. Frontend video cards show error badges.

### API Routes

New router `src/streamdoc/api/routes/youtube.py` (prefix `/youtube`, tag `youtube`):

**Profile management:**
```
GET    /youtube/profiles                       → list all profiles with status
POST   /youtube/profiles                       → create profile (body: {name})
DELETE /youtube/profiles/{name}                → delete profile + dirs
POST   /youtube/profiles/{name}/activate       → set as active profile
POST   /youtube/profiles/{name}/clear-flag     → reset status to healthy
```

**Authentication (Playwright, non-blocking + polling):**
```
POST   /youtube/profiles/{name}/login          → launch Playwright login (subprocess), returns {job_id}
POST   /youtube/profiles/{name}/solve-captcha  → launch Playwright CAPTCHA solve (subprocess), returns {job_id}
GET    /youtube/login-status/{job_id}          → poll login/solve subprocess result
```

Login and CAPTCHA solve start a background subprocess and return immediately
with a job ID. Frontend polls `login-status` with the job ID until it returns
`completed` / `failed` / `timeout`. The job ID is a short UUID; status is
stored in-memory in the profile manager (lost on restart — acceptable since
these are short-lived interactive operations).

**Bypass mode settings:**
Handled by existing `PUT /settings` endpoint (dynamic `model_fields` reflection).
No new routes needed.

**Schemas** (`src/streamdoc/api/schemas.py`):
```python
class YouTubeProfileInfo(BaseModel):
    name: str
    status: str          # healthy | flagged | unknown
    created_at: str
    last_used: str | None
    last_error: str | None
    last_error_category: str | None
    error_count: int
    is_active: bool
    has_cookies: bool    # whether cookies.txt exists

class CreateProfileRequest(BaseModel):
    name: str

class LoginStatusResponse(BaseModel):
    status: str          # pending | completed | failed | timeout
    message: str | None
```

### Frontend

**New "YouTube Profiles" section on the Settings page:**

Profile list panel:
- Card per profile: name, status badge (green=healthy, red=flagged, gray=unknown),
  "Active" indicator, last_used timestamp, error count
- Actions per profile: "Login", "Solve CAPTCHA", "Activate", "Clear Flag", "Delete" (with confirm)
- "Create Profile" button at top — opens name input dialog
- Active profile highlighted with border/accent

Login/CAPTCHA flow (modal):
- On click, modal opens showing "Launching browser..." then polls `login-status` every 2s
- Shows: "Waiting for you to sign in / solve CAPTCHA in the browser window..."
- On completion: "Success — cookies exported" or "Failed — timeout" with error detail
- Modal closes, profile list refreshes

Bypass mode toggle:
- Existing dropdown stays for Simple mode, with `cookie_profile` added
- When `cookie_profile` selected, profile selector dropdown appears below it
- "Advanced mode" toggle switches to ordered chain UI:
  - Drag-to-reorder list of modes
  - Add/remove buttons per entry
  - Saved to `yt_dlp_bypass_chain` as comma-separated string

Video error display:
- Failed videos show red "Failed" badge + error category badge (e.g. "HTTP 403")
- Tooltip on hover shows raw `media_error` message

Contextual unblock prompt:
- When po_token mode gets 403 errors and no profiles exist, UI shows:
  *"Downloads are failing with HTTP 403. Create a YouTube profile to solve a
  CAPTCHA and unblock your IP."* with a "Create Profile" button.

Components (following existing frontend structure):
- `YouTubeProfiles.tsx` — profile management panel
- `BypassModeSelector.tsx` — simple/advanced toggle + chain editor
- Reuses existing Card/Button/Badge/Dialog patterns

## CAPTCHA Flow Summary

**No profile exists + blocked (po_token setup):**
1. UI shows contextual prompt: "Create a profile to solve CAPTCHA"
2. User creates a profile (one click, no login needed)
3. User clicks "Solve CAPTCHA" on the new profile
4. Playwright opens to youtube.com — user solves CAPTCHA (does NOT sign in)
5. Post-CAPTCHA cookies exported to `cookies.txt`
6. IP block lifted. User switches to `cookie_profile` mode or back to `po_token`

**Profile exists + flagged:**
1. User clicks "Solve CAPTCHA" on the flagged profile
2. Same Playwright flow — cookies re-exported, flag cleared

**Login is never required for CAPTCHA solve.** The profile is just a browser
context container. Login is a separate, optional action for authenticated
downloads.

## Error Handling

- Playwright subprocess timeout: login/CAPTCHA sessions time out after
  `social_login_timeout_seconds` (300s default, reused from existing config).
  Status returns "timeout", user can retry.
- No active profile + `cookie_profile` mode: downloader logs warning, download
  fails (so advanced chain moves to next mode). Simple mode shows UI error.
- Cookie jar missing/stale: downloader logs warning, treats as no cookies.
- Manifest corruption: on read error, log warning and treat as no profiles.
  Does not crash the server.
- Concurrent manifest writes: atomic write (temp + rename) prevents corruption.

## Testing

- Unit tests for `YouTubeProfileManager` (CRUD, health tracking, manifest R/W)
- Unit tests for `cookie_export.py` (Playwright cookie dict → Netscape format)
- Unit tests for bypass chain iteration logic in `download()`
- Unit tests for `cookie_profile` mode in `_apply_bypass_opts` / `build_common_args`
- Unit tests for error classification + `media_error` recording
- Integration test: create profile → mock Playwright login → export cookies →
  download with `cookie_profile` mode → verify `--cookiefile` passed to yt-dlp
- All tests in `/tests` folder, following existing `test_downloader.py` patterns

## Out of Scope

- Automatic profile rotation (explicitly rejected — manual switch only)
- Active health probing (passive badge only — no periodic YouTube API calls)
- Database model for profiles (file-based manifest only)
- Standalone CAPTCHA unblock without a profile (per-profile only)
- Cookie refresh/keepalive for YouTube profiles (unlike NotebookLM which has
  long-lived sessions; YouTube profiles are re-opened on demand)
