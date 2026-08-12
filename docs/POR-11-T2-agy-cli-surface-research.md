# POR-11 T2: Research Agy (Google Antigravity) CLI Surface for Report Consumption

**Date:** 2026-07-23
**Researcher:** Hermes Researcher profile
**Task:** t_4db2b304
**Originating Issue:** POR-11 (Social Sentiment Preset)

---

## Question

What is the Google Antigravity CLI (`agy`) — its command-line surface, installation, capabilities, free-tier limits, and optimal integration pattern for StreamDoc's social-sentiment preset pipeline to consume aggregated Markdown/PDF reports?

---

## Findings

### 1. What is Google Antigravity / `agy`?

**Google Antigravity** is Google's agent-first AI coding CLI, announced at Google I/O 2026. It serves as the successor to the Gemini CLI (deprecated 2026-06-18). The binary is named `agy`.

- **GitHub:** https://github.com/google-antigravity/antigravity-cli (★1703)
- **Official docs:** https://antigravity.google/docs/cli/overview
- **Product page:** https://antigravity.google/product/antigravity-cli
- **SDK:** https://github.com/google-antigravity/antigravity-sdk-python (★2586, `pip install google-antigravity`)

Antigravity CLI runs as a **terminal UI (TUI)** by default but supports a **non-interactive print mode** (`-p` flag) that is the primary surface for automation and scripting. It shares a common agent engine with Antigravity 2.0 (the GUI version).

### 2. CLI Command Surface

| Command / Flag | Purpose |
|---|---|
| `agy` | Launch interactive TUI session |
| `agy -p "<prompt>"` | **Non-interactive print mode** — runs a single prompt and prints the response to stdout |
| `agy -c` / `--continue` | Continue the most recent conversation |
| `agy --conversation <id>` | Resume a specific conversation by ID |
| `agy --add-dir <path>` | Add workspace directories (repeatable) |
| `agy --sandbox` | Run in sandbox mode (isolated from system) |
| `agy --dangerously-skip-permissions` | Skip all permission prompts (for CI/CD) |
| `agy --version` | Print version |
| `agy models` | List available AI models |
| `agy update` | Self-update the binary |
| `agy changelog` | View release notes |
| `agy plugin <args>` | Plugin management (list, install, enable) |
| `/logout` | Sign out (within interactive session) |
| `/resume` | Interactive picker for past conversations |

**Exit code contract:**
- `0` — success
- `1` — error
- `2` — timeout (when used with `--timeout` via wrappers)

**Key finding for integration:** The `-p` (print mode) flag is the sole documented route for non-interactive, scripted usage. It runs a single prompt and exits.

### 3. Installation

**macOS / Linux:**
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

**Windows PowerShell:**
```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

**macOS (Homebrew):**
```bash
brew install --cask antigravity-cli
```

The binary installs to `~/.local/bin/agy` (Unix) or `%LOCALAPPDATA%\agy\bin\agy.exe` (Windows). First run requires Google OAuth sign-in (browser-based, one-time).

### 4. Free Tier & Pricing

Based on the PRD context and references, `agy` uses the **Antigravity/Gemini subscription model**. The PRD describes it as having a "generous free tier instead of paid NotebookLM." Specifically:

- Free tier provides access to Gemini models (Flash, Pro) with rate limits
- GCP enterprise tier for Vertex AI-backed usage
- Google subscription (Gemini Advanced / Google One) unlocks higher-tier models

The PRD specifically positions agy as a free-tier or low-cost alternative to NotebookLM's paid generation, for tasks like building presentations and emitting JSON.

### 5. How `agy` Consumes Reports

`agy` is an **AI coding agent** — it reads files from its workspace directory and processes them based on natural-language instructions. The consumption pattern for StreamDoc would be:

1. StreamDoc places the aggregated report(s) (.md, .pdf) into a workspace directory
2. StreamDoc invokes `agy -p "<prompt_from_template>"` where the prompt instructs agy to:
   - Read the specified report files
   - Process them (generate presentation, emit JSON, etc.)
   - Write output files to a specified directory
3. agy reads the files, uses its AI capabilities, and produces the requested output

**Critical limitation discovered:** As of `agy` v1.0.2, **print mode (`-p`) output renders only to an interactive TTY**. When stdout is captured/redirected, the output is empty. This means StreamDoc **cannot programmatically capture agy's output** via `subprocess.run()` with `capture_output=True`. This was verified by the `agy-py` project (an unofficial Python wrapper).

**Mitigation:** The wrapper approach used by `agy-py` (inheriting the terminal) would not work for StreamDoc, which needs to capture results. However, agy can **write output files to disk** (e.g., "Generate a presentation and save it to /path/to/output/") — the agent has file-writing capabilities. StreamDoc should:
- Pass a prompt that instructs agy to **write its output to a specific directory** (not stdout)
- Then read those files from the expected output path

**Alternative (recommended for deeper integration):** The **Antigravity SDK** (`pip install google-antigravity`) provides a Python API that can be used programmatically, avoiding the subprocess approach entirely:
- `Agent` class with streaming responses
- `Conversation` for stateful sessions
- File attachments via `from_file()` or content classes
- Custom tool registration
- MCP integration

### 6. Output Formats

Since agy is a general-purpose AI coding agent, its **output format is determined entirely by the prompt**, not by built-in command flags. Through prompt engineering, it can produce:

- **Presentations** (markdown → pandoc/ reveal.js / Marp)
- **JSON** (structured data export for 3rd-party systems)
- **HTML** (web reports)
- **Markdown** (formatted reports)
- **Code** (any language)
- **LaTeX/PDF** (via toolchain)
- **Any other format** the agent can generate via installed tooling

The PRD specifically mentions "build presentations, emit JSON consumed by 3rd-party systems, and trigger downstream pipelines."

### 7. Model Options

Available through `agy` (from the cc-to-antigravity-cli-bridge docs):

| Model | Reasoning Tiers |
|---|---|
| Gemini 3.5 Flash | Low / Medium / High |
| Gemini 3.1 Pro | Low / High |
| Claude Sonnet 4.6 | Thinking |
| Claude Opus 4.6 | Thinking |
| GPT-OSS 120B | Medium |

Model is set config-driven (not via `-m` flag). The `-p` flag works with the configured default model.

### 8. Configuration & Skills System

- **`~/.gemini/antigravity-cli/settings.json`** — Main configuration file
- **`AGENTS.md`** — Per-project instructions (analogous to `CLAUDE.md` for Claude Code)
- **`~/.gemini/AGENTS.md`** — Global instructions
- **Agent Skills** — `.md` skill files with instructions for specific tasks
- **Extensions** — Plugin system for additional capabilities

---

## Options for Integration

### Option A: Subprocess invocation via `agy -p` (lightweight, no SDK dependency)

**Pattern:**
```python
import subprocess
# Place reports in workspace
# Invoke agy with a prompt template
result = subprocess.run(
    ["agy", "-p", prompt_text],
    capture_output=False,  # can't capture stdout
    cwd=workspace_dir,
)
# Read output files written by agy
```

**What it does well:**
- Zero Python dependencies beyond the agy binary
- Simple, transparent architecture
- Uses existing `subprocess.run` pattern (matches yt-dlp invocations in `core/downloader.py`)
- Works with user-editable YAML prompt templates (as designed in the PRD)

**What it does poorly:**
- **Cannot capture stdout** — real terminal required for output rendering in v1.0.2
- Workaround: agy must write output to files (prompt-dependent)
- One-shot only; no conversation state management
- Workspace trust prompt on first access to a new directory
- Slow startup for each invocation (model loading)

**Risks:**
- Workspace trust requires `--dangerously-skip-permissions` (security concern) or pre-configuration
- Binary may not be installed (detection needed)
- Version compatibility: future `agy` releases may change `-p` behavior

### Option B: Antigravity SDK Python API (full programmatic control)

**Pattern:**
```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import from_file

async with Agent(config) as agent:
    reports = [from_file("report.pdf"), from_file("report.md")]
    prompt = [
        "Generate a JSON summary from these reports:",
        *reports,
        "Save the output to /path/to/output.json"
    ]
    response = await agent.chat(prompt)
```

**What it does well:**
- Full programmatic control over prompts, attachments, output
- File attachments via `from_file()` (auto-detects MIME types for PDF, images, etc.)
- Streaming responses (real-time output)
- Custom tool registration for downstream pipeline triggers
- Conversation state management
- No TTY/capture limitations

**What it does poorly:**
- Adds `google-antigravity` as a Python dependency (compiled binary, ~50MB+)
- Added complexity of async Python
- The SDK is still evolving (new at Google I/O 2026)
- May not be available on all platforms (compiled binary requirement)

**Risks:**
- SDK binary size and platform compatibility
- API stability (new SDK, likely to change)
- Overkill for simple "run one prompt" use case

### Option C: Hybrid — `agy -p` for simple tasks, SDK for complex workflows

**Pattern:**
```python
# For simple report → presentation/JSON:
# Use subprocess with prompt template (Option A)

# For complex multi-step workflows:
# Use SDK (Option B) when more control is needed
```

**What it does well:**
- Right tool for the job
- Simple path works for 80% of cases
- SDK available for power users

**What it does poorly:**
- Two integration paths to maintain
- SDK may not be installed (optional dependency)

---

## Recommendation

**Option A (subprocess `agy -p`) for StreamDoc v1**, with these specifics:

1. **Binary path detection** — Mirror the `yt_dlp_path` / `yt_dlp_module_path` pattern from `config.py`: search PATH first, allow override via `STREAMDOC_AGY_BINARY_PATH`

2. **Detection method** — Use `shutil.which("agy")` + version check via `agy --version`

3. **Invocation pattern** — Call `agy -p "<prompt>"` with `shell=False`, `cwd=workspace_dir`. Do NOT use `capture_output=True` (doesn't work in v1.0.2). Instead, instruct agy via prompt to write output to a known directory, then read from there.

4. **Template system** — YAML prompt templates under `config/templates/agy/` (user-editable) and `assets/templates/agy/` (shipped samples), exactly as designed in the POR-11 PRD. The prompt should:
   - Tell agy what report files to read (from the workspace)
   - Specify the desired output format (e.g., "Generate a LinkedIn post series" or "Produce a JSON sentiment summary")
   - Tell agy where to save output files

5. **Workspace trust** — On first run, StreamDoc should:
   - Add the workspace path to agy's `trustedWorkspaces` via `settings.json` manipulation
   - OR run with `--dangerously-skip-permissions` in CI/headless mode only
   - The `installCLITool` guidance route (from POR-11 PRD) should document this step

6. **Async execution** — Use `asyncio.create_subprocess_exec` (matching the `run_async` pattern already used for NotebookLM) rather than blocking `subprocess.run`, so the pipeline doesn't block on agy

7. **Fallback/recommendation** — If the `-p` TTY limitation is resolved in a future version of agy, StreamDoc can start capturing stdout output. If the limitation persists, consider upgrading to the SDK (Option B) for deeper integration.

---

## Next Steps for Implementation

1. **Create the `BaseCLITool` ABC + `AgyCLI` adapter** under `integrations/cli_tools/` with:
   - `is_installed()` — `shutil.which("agy")` check
   - `detect()` — returns version or None
   - `ensure_installed(prompt=True)` — returns install instructions URL
   - `run(report_paths, template, out_dir)` — invokes `agy -p` with rendered prompt

2. **Create sample prompt templates** under `assets/templates/agy/`:
   - `presentation.yaml` — "Generate a slide deck summarizing these reports"
   - `json_export.yaml` — "Extract structured JSON data from these reports"
   - `sentiment_summary.yaml` — "Summarize the social sentiment from these reports"

3. **Add settings** to `config.py`:
   - `STREAMDOC_AGY_BINARY_PATH` (optional override, default None = search PATH)
   - `STREAMDOC_AGY_TEMPLATES_DIR` (default `config/templates/agy`)
   - `STREAMDOC_AGY_SAMPLE_TEMPLATES_DIR` (default `assets/templates/agy`)

4. **Wire the `agy` destination** into `_send_reports` in `fetch.py` and `_send_to_destination` in `jobs.py`, using the same symmetry as the `notebooklm` branch

5. **Document the TTY limitation** in the CLI-tools admin page so users know agy works via file output, not stdout capture

---

## References

- **Antigravity CLI GitHub:** https://github.com/google-antigravity/antigravity-cli (★1703)
- **Antigravity SDK Python:** https://github.com/google-antigravity/antigravity-sdk-python (★2586, `pip install google-antigravity`)
- **Official docs:** https://antigravity.google/docs/cli/overview
- **Product page:** https://antigravity.google/product/antigravity-cli
- **Agy-py (unofficial Python wrapper):** https://github.com/ddtraveller/antigravity-py — verified command surface against v1.0.2, exposed the TTY output limitation
- **Claude-Antigravity bridge:** https://github.com/yyu0310/cc-to-antigravity-cli-bridge — documented model list and `-p` usage patterns
- **Agy plugin for Claude Code:** https://github.com/romacv/agy-plugin-cc — documented permissions model and non-interactive flags
- **Awesome Antigravity CLI:** https://github.com/delfinadap/awesome-antigravity-cli — curated list of tools, skills, and integrations
- **Antigravity CLI install script:** https://antigravity.google/cli/install.sh
- **Claude Code Antigravity Agents skill:** https://github.com/markfulton/claude-antigravity-agents (★105) — detailed sub-agent delegation patterns
