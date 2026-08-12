# Research Report: Google Antigravity CLI (`agy`)

> **Date:** 2026-07-23
> **Researched by:** POR-11 T2
> **Purpose:** Evaluate `agy` as a report-consumption destination for StreamDoc's YouTube-to-PDF pipeline

---

## 1. What Is Google Antigravity / `agy`?

**Google Antigravity** is Google's autonomous terminal AI coding agent — a direct competitor to Anthropic's Claude Code. The CLI binary is called `agy`.

It is a **terminal-based agent** (TUI + non-interactive modes) powered primarily by **Gemini models** (3.5 Flash, 3.1 Pro, etc.), with the ability to route to other models including **Claude Sonnet/Opus 4.6** and **gpt-oss-120b**. It can read code repositories, edit files, run terminal commands, execute multi-step reasoning, and produce various output formats.

Antigravity comes in three surfaces:
1. **Antigravity CLI (`agy`)** — lightweight keyboard-driven TUI for the terminal (v1.1.5 as of writing)
2. **Antigravity 2.0** — full visual desktop editor/IDE (v2.3.1)
3. **Antigravity IDE** — VS Code-based IDE (v2.1.1)
4. **Antigravity SDK** — programmatic SDK (v0.1.7)

The CLI and the 2.0 desktop app share the **same agent harness**, settings sync, and conversation export.

**Critical distinction:** There is a **separate** PyPI package also called `agy` (v1.0.0, by `big-picture` / Maximilian Vogel) which is an unrelated Python "agent flow engine." This is **NOT** Google's Antigravity CLI. Do not confuse the two.

---

## 2. CLI Command Surface

### Binary & Invocation

- **Binary name:** `agy`
- **Install location:** `~/.local/bin/agy` (macOS/Linux), `C:\Users\<User>\AppData\Local\agy\bin\agy.exe` (Windows)
- **Interactive mode:** Just run `agy` — opens a Gemini-powered TUI session
- **Non-interactive (print) mode:** `agy -p "<prompt>"` — used for automation/scripting

### Key Flags (from documentation and plugins)

| Flag | Description |
|---|---|
| `-p "..."` or `--print "..."` | Non-interactive print mode; run a prompt and output result to stdout |
| `--print-timeout <duration>` | Timeout for print mode (default 5m; raise to `10m`, `20m` for big jobs) |
| `--sandbox` | Sandbox mode (terminal restrictions) — safe for read-only jobs |
| `--dangerously-skip-permissions` | Bypass permission review prompts (required for non-interactive use) |
| `--model "<name>"` | Model selection (e.g. `"Gemini 3.5 Flash (Medium)"`, `"Gemini 3.5 Flash (High)"`) |
| `--continue` | Resume the most recent conversation |
| `--add-dir <path>` | Grant access to extra directories |

### Slash Commands (interactive TUI mode)

From the docs navigation (https://antigravity.google/docs/cli/overview):
- `/agents` — Manage sub-agents
- `/codesearch` — Code search
- `/credits` — AI credits management
- `/diff` — Diff review
- `/permissions` — Permission management
- `/resume` — Resume conversation
- `/statusline` — Status line customization
- `/title` — Window title
- `/usage`, `/quota` — Model quota

### Sub-agents

The CLI supports a `subagent` system. A common pattern is the `agy:runner` subagent, used by third-party plugins (Claude Code plugins, MCP bridges) to delegate tasks to Antigravity.

### Non-interactive Automation Patterns

The most relevant pattern for StreamDoc integration:
```bash
agy -p "<task description>" --print-timeout 10m --sandbox --dangerously-skip-permissions </dev/null
```

The `</dev/null` is **critical** — `agy` blocks forever if stdin is an open pipe.

---

## 3. How Can It Consume Markdown/PDF Reports as Input?

Based on available documentation and third-party tooling:

- **CLI-level file reading:** `agy` can read local files via its agent capabilities — you can instruct it in the `-p` prompt with phrases like "read report.md" or "analyze this PDF."
- **`search_files()` built-in action:** The CLI supports searching local files and parsing PDF, DOCX, XLSX, TXT, HTML content (from the `load_files_text()` action).
- **Standard input via pipe:** You can pipe content into `agy` via stdin, since it operates as a standard terminal agent.
- **Command-line argument:** The `-p` flag accepts a prompt string that can reference file paths.
- **Stochastic agents:** The CLI can accept "requests" items in its flow language (FLOWSY) that reference external files.

**For StreamDoc specifically:** The most practical approach would be to either:
1. Pipe the Markdown/PDF report content into `agy` as part of the prompt
2. Save the report to a known file path and instruct `agy` to read and process it
3. Use the `--add-dir` flag to give `agy` access to a directory containing reports

**Note:** There is no native "watch a directory and consume new files" daemon mode — it's a task-oriented agent that executes jobs on demand.

---

## 4. Installation

### Official Install Methods

**macOS / Linux:**
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```
Binary registered at: `~/.local/bin/agy`

**Windows (PowerShell):**
```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```
Binary registered at: `C:\Users\<Username>\AppData\Local\agy\bin\agy.exe`

**Windows (CMD):**
```cmd
curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd
```

### Package Managers
- **Not on pip/npm as an official Google package.** The PyPI `agy` package is unrelated.
- There are community npm wrappers (e.g. `@bash0816/agy-termux`, `agyw` for profile switching) but these are third-party.

### Authentication
After installation, run `agy` once in an interactive terminal to complete Google OAuth. After that, non-interactive `agy -p` jobs work without further prompts.

Can also use `ANTIGRAVITY_API_KEY` environment variable for headless auth.

---

## 5. Output Formats

Based on the documentation and plugin integrations:

- **Text/stdout (default):** In `-p` print mode, output goes to stdout as raw text.
- **Presentations:** `agy` can generate images via its built-in `generate_image` tool (powered by Imagen). It can produce structured Markdown reports, slide decks, etc. through prompt instructions. The `python-pptx` dependency in the unrelated PyPI `agy` suggests PowerPoint generation is a pattern, but for Google's Antigravity CLI, output is what you instruct the agent to produce.
- **JSON:** `agy` can be instructed to emit structured JSON. The CLI can output to stdout in formats you define via prompts.
- **Artifacts:** Generated files (images, docs) are stored in `~/.gemini/antigravity-cli/brain/<uuid>/` by default.
- **Code diffs:** `git diff` output for code changes.
- **Conversation export:** Sessions can be exported from CLI to Antigravity 2.0.

**Key insight for StreamDoc:** Since `agy` is an LLM agent, its output format is determined by what you ask it to produce. You can prompt: "Read this report and output a JSON summary," "Create a presentation from this Markdown," or "Analyze this PDF and emit structured data."

---

## 6. Free Tier & Pricing

Based on the https://antigravity.google/pricing page:

| Tier | Price | Key Features |
|---|---|---|
| **Individual (Free)** | **$0/month** | Access to Gemini 3.5 Flash, Gemini 3.1 Pro, Gemini 3 Flash, Claude Sonnet & Opus 4.6, gpt-oss-120b. Unlimited Tab completions. Unlimited Command requests. **Basic weekly rate limits.** |
| **Google AI Pro** | Paid (Google AI Pro subscription) | Everything in Individual plus more generous rate limits, flexible AI credit pool |
| **Google AI Ultra** | Paid (Google AI Ultra subscription) | Everything in Pro plus more generous rate limits, flexible AI credit pool, access to latest Gemini models |
| **Enterprise / Organization** | Via Google Cloud | Access under Google Cloud Terms of Service, Google Cloud Project Integration, Consumption-Based API Pricing |

**The "generous free tier" is confirmed:** $0/month individual plan with access to multiple leading models. The limits are "basic weekly rate limits" — exact numbers are not publicly shown but appear sufficient for individual/developer use.

---

## 7. Official Documentation, Repositories, and Home Page

### Official Google Properties

| Resource | URL |
|---|---|
| **Home page** | https://antigravity.google/ |
| **Pricing page** | https://antigravity.google/pricing |
| **CLI Overview** | https://antigravity.google/docs/cli/overview |
| **CLI Getting Started** | https://antigravity.google/docs/cli/getting-started |
| **CLI Installation & Auth** | https://antigravity.google/docs/cli/installation |
| **CLI Tutorial** | https://antigravity.google/docs/cli/tutorial |
| **CLI Features** | https://antigravity.google/docs/cli/features |
| **CLI Prompting** | https://antigravity.google/docs/cli/prompting |
| **CLI Artifacts** | https://antigravity.google/docs/cli/artifacts |
| **CLI Commands** | https://antigravity.google/docs/cli/commands (nav reference: `/agents`, `/codesearch`, `/credits`, `/diff`, `/permissions`, `/resume`, `/statusline`, `/title`, `/usage`, `/quota`) |
| **Blog** | https://antigravity.google/blog |
| **Changelog** | https://antigravity.google/changelog |
| **CLI Install Script** | https://antigravity.google/cli/install.sh |
| **CLI Install (PowerShell)** | https://antigravity.google/cli/install.ps1 |

### Third-Party Ecosystem (Notable)

| Resource | URL | Description |
|---|---|---|
| Claude Code Skill | https://github.com/markfulton/claude-antigravity-agents | Skill to delegate work from Claude Code to agy (105 stars) |
| Claude Code Plugin | https://github.com/simplybychris/antigravity-plugin-cc | `/agy:ask`, `/agy:delegate`, `/agy:research`, `/agy:image`, `/agy:review` commands (56 stars) |
| MCP Bridge | https://github.com/sshahzaiib/agy-bridge | MCP bridge for Claude Code ↔ agy delegation |
| VS Code Extension | https://github.com/lyadhgod/antigravity-vscode | Antigravity in VS Code with chat UI, Google sign-in |
| Antigravity for Claude Code | https://github.com/yuting0624/antigravity-for-claude-code | Alternative Claude Code plugin (198 stars) |

---

## Key Findings for StreamDoc Integration

1. **`agy` is real and production-ready.** It's Google's official AI coding agent CLI, currently at v1.1.5. The free tier ($0/month) is confirmed and includes access to multiple models with "basic weekly rate limits."

2. **Input consumption:** Reports (Markdown/PDF) can be fed to `agy` via prompt instructions referencing file paths, stdin pipes, or `--add-dir` directory access. It natively parses PDF, DOCX, XLSX, TXT, and HTML.

3. **Output formats:** Fully prompt-defined — can produce JSON, presentations, Markdown reports, or any other text format. For structured data consumption downstream, instructing it to emit JSON is straightforward.

4. **Installation is simple:** Single curl/powershell command, no package manager needed. Auth is Google OAuth (one-time interactive setup, then headless).

5. **Primary limitation:** `agy` is task-oriented, not a persistent daemon. Each invocation is a fresh job. For StreamDoc, you'd invoke `agy` per-report rather than maintaining a long-lived connection.

6. **The PyPI `agy` package is unrelated.** The StreamDoc team should use the official Google installer, not `pip install agy`.
