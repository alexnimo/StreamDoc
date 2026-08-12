# StreamDoc — Integrations & Auth Design

## Source of truth for providers

- **NotebookLM provider**: [teng-lin/notebooklm-py](https://github.com/teng-lin/notebooklm-py)
  - MIT license — see [project README](https://github.com/teng-lin/notebooklm-py#readme)
  - auth modes:
    - interactive browser login (`notebooklm login`)
    - browser-cookie import (`--browser-cookies chrome`)
    - headless with preloaded `storage_state.json`
  - risky assumption to depend on: it uses Google’s **undocumented internal APIs**, so breakage is possible; therefore the provider interface in StreamDoc must stay thin.

## Secret / credential boundary

Owned by StreamDoc:
- app API keys, feature flags, internal config

Not owned by StreamDoc:
- NotebookLM Google session (cookies / storage state)
- future provider credentials

Rule: StreamDoc must **never** store raw NotebookLM Google cookies or OAuth tokens itself unless the user explicitly opts into a managed location, because:
- they expire,
- they’re sensitive,
- browser-cookie imports are the lowest-friction-supported path right now.

## Practical handling for NotebookLM in v1

Recommended flow:
1. User prepares NotebookLM auth outside StreamDoc using `notebooklm-py`:
   - `notebooklm login`
   - or `notebooklm login --browser-cookies chrome`
2. StreamDoc reads the resulting profile from the environment/file location the provider expects:
   - `storage_state.json` if using headless library mode,
   - or Chromium profile directory if browser-cookie mode is live.
3. StreamDoc passes only the minimal hook-through: provider profile path or account label.

Local-first configuration layout:
```
config/
  integrations/
    notebooklm/
      mode: storage_state | cookies | managed
      storage_state_path: data/integrations/notebooklm/storage_state.json
      profile: default
      account: user@gmail.com
```

Docker guidance:
- Mount the NotebookLM auth directory/file as a volume.
- Do **not** bake credentials into the image.

```yaml
services:
  app:
    volumes:
      - ./data/integrations/notebooklm:/app/data/integrations/notebooklm
```

## Provider interface contract

`src/streamdoc/integrations/` defines a small abstract surface:

- `list_notebooks()`
- `create_notebook(name)`
- `add_sources(notebook_id, sources=[url|file|text])`
- `generate(notebook_id, kind, prompt, wait=True)`
- `download_artifact(notebook_id, kind, destination)`

`notebooklm.py` implements this using `notebooklm-py`.
Future providers implement the same interface.

## Retry / resilience

- Treat NotebookLM as an external, rate-limited, undocumented API.
- Retries with backoff on failure.
- Failure policy: mark run as integration-failed, do not discard local PDF.
- Observability: log provider state, response codes where available, last-known auth status.

## Retention / cleanup

- NotebookLM notebooks created by StreamDoc may be tagged/metadata-tracked.
- The user decides retention/time-to-live externally (your prior requirement).
- StreamDoc can optionally delete or archive notes after a configured TTL.
