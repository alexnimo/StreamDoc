# Social Platform Setup

StreamDoc can collect posts from **X (Twitter)**, **Reddit**, and **Stocktwits** for social sentiment presets. This guide covers installing the required CLI tools, authenticating, and verifying everything from the UI.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) installed
- `twitter` CLI for X
- `rdt` CLI for Reddit
- Stocktwits works without authentication

## X (Twitter) Setup

1. Install `twitter-cli` (latest version from the public-clis repository):
   ```bash
   uv tool install --upgrade git+https://github.com/public-clis/twitter-cli.git
   # or from PyPI:
   uv tool install twitter-cli
   ```
2. Log in to [x.com](https://x.com) in a supported browser (Chrome, Edge, Firefox, Brave, Arc).
3. Run authentication:
   ```bash
   twitter login
   ```
4. Or use **Settings > Social** in the StreamDoc UI and click **Authorize** under X.

## Reddit Setup

1. Install `rdt-cli` (latest version from the public-clis repository):
   ```bash
   uv tool install --upgrade git+https://github.com/public-clis/rdt-cli.git
   # or from PyPI:
   uv tool install rdt-cli
   ```
2. Log in to [reddit.com](https://www.reddit.com) in a supported browser.
3. Run authentication:
   ```bash
   rdt login
   ```
4. Or use **Settings > Social** in the StreamDoc UI and click **Authorize** under Reddit.

## Stocktwits

No authentication required. The collector uses HTTP requests with browser-like headers and a `curl_cffi` fallback to bypass Cloudflare if needed.

You can override the API base URL in **Settings > Social** or with:

```bash
STREAMDOC_STOCKTWITS_API_BASE=https://api.stocktwits.com/api/2/
```

## Automated setup with just

```bash
just setup-social
```

This installs the CLIs if missing, guides you through `twitter login` and `rdt login`, and reports final status.

## Verification

Visit **Settings > Social** in the StreamDoc UI. You will see:

- **Green checkmark** — configured and authenticated
- **Yellow warning** — binary found but not authenticated
- **Red error** — not configured or unreachable

You can also test the API directly:

```bash
curl http://localhost:5454/api/social/status
```

Expected response:

```json
{
  "twitter": {
    "binary_found": true,
    "version": "twitter-cli x.y.z",
    "authenticated": true,
    "last_check": "2026-07-24T12:00:00Z",
    "message": "Authenticated"
  },
  "reddit": {
    "binary_found": true,
    "version": "rdt-cli x.y.z",
    "authenticated": true,
    "last_check": "2026-07-24T12:00:00Z",
    "message": "Cookies present"
  },
  "stocktwits": {
    "api_reachable": true,
    "last_check": "2026-07-24T12:00:00Z",
    "rate_limit_remaining": null,
    "message": "Stocktwits API is reachable."
  }
}
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `twitter binary not found` | Run `uv tool install twitter-cli` or set `STREAMDOC_TWITTER_CLI_BINARY_PATH` to the binary. |
| `rdt binary not found` | Run `uv tool install rdt-cli` or set `STREAMDOC_RDT_CLI_BINARY_PATH` to the binary. |
| `Not authenticated` for X | Log in to x.com in your browser, then run `twitter login` again. |
| `Not authenticated` for Reddit | Log in to reddit.com in your browser, then run `rdt login` again. |
| `Cookie expired` | Re-run `twitter login` or `rdt logout && rdt login`. |
| Stocktwits unreachable | Check your network; the API may be rate-limiting. Wait a minute and retry. |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `STREAMDOC_TWITTER_CLI_BINARY_PATH` | auto | Absolute path to the `twitter` binary. |
| `STREAMDOC_RDT_CLI_BINARY_PATH` | auto | Absolute path to the `rdt` binary. |
| `STREAMDOC_REDDIT_COOKIE` | — | Optional cookie header for direct Reddit fallback. |
| `STREAMDOC_CURL_CFFI_IMPERSONATE` | `chrome133a` | Browser impersonation profile for `curl_cffi`. |
| `STREAMDOC_STOCKTWITS_API_BASE` | `https://api.stocktwits.com/api/2/` | Stocktwits API base URL. |
