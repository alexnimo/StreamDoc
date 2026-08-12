#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
# Dark Factory — Coding Agent Library
#
# Unified abstraction over external coding agents (devin, claude-code, etc.).
# Handles prompt-file patterns, permission modes, watchdog, and fallback.
#
# This is the ONLY place that knows about specific CLI flag differences
# between coding agent versions. Profile instructions reference these
# helpers, not raw invocations.
#
# Devin v2026.7.23 flags (verified):
#   --permission-mode: normal (default), dangerous (aliases: yolo, bypass)
#     yolo is the verified-safe alias for non-interactive -p runs.
#   --model: exact labels only (e.g. swe-1.7, claude-opus-4.6, kimi-k2.7, adaptive)
#   --prompt-file: load prompt from file (PREFER THIS FOR LONG INSTRUCTIONS)
#   -p, --print: non-interactive print/exit mode
#   --export: ATIF format conversation export
# ════════════════════════════════════════════════════════════════════

set -euo pipefail

DF_ROOT="${DF_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# shellcheck source=lib/common.sh
source "$DF_ROOT/lib/common.sh"

# ─── Public API ─────────────────────────────────────────────────────

# Determine if the installed coding agent binary is responsive.
# Returns 0 if available, 1 if not.
coding_agent_available() {
  local tool="${1:-devin}"
  if ! command -v "$tool" &>/dev/null; then
    return 1
  fi
  # Quick version check — don't block, just verify it runs
  "$tool" --version &>/dev/null 2>&1 || return 1
  return 0
}

# Get the model for a role from factory.yaml.
# Falls back to "adaptive" if not specified (let the router decide).
# Usage: coding_agent_model_for_role <role-name>
coding_agent_model_for_role() {
  local role="$1"
  local model
  model=$(get_yaml "profiles.${role}.coding_agent.model" 2>/dev/null || echo "")
  if [ -z "$model" ] || [ "$model" = "null" ]; then
    model=$(get_yaml "worker_defaults.coding_agent.model" 2>/dev/null || echo "")
  fi
  if [ -z "$model" ] || [ "$model" = "null" ]; then
    model="adaptive"  # safest default — router picks best
  fi
  echo "$model"
}

# Get the permission mode for a role from factory.yaml.
# Defaults to "yolo" — verified safe mode for non-interactive invocations
# on v2026.7.23 (prevents the permission approval hang in -p mode).
coding_agent_permission_mode() {
  local role="$1"
  local mode
  mode=$(get_yaml "profiles.${role}.coding_agent.permission_mode" 2>/dev/null || echo "")
  if [ -z "$mode" ] || [ "$mode" = "null" ]; then
    mode=$(get_yaml "worker_defaults.coding_agent.permission_mode" 2>/dev/null || echo "")
  fi
  if [ -z "$mode" ] || [ "$mode" = "null" ]; then
    mode="yolo"  # verified safe default for non-interactive -p mode
  fi
  # Reject "smart" (not in v2026.7.23) with a warning
  if [ "$mode" = "smart" ]; then
    log_warn "permission_mode 'smart' is not valid in Devin v2026.7.23 — falling back to 'yolo'"
    mode="yolo"
  fi
  case "$mode" in
    normal|auto|dangerous|yolo|bypass) echo "$mode" ;;
    *) echo "yolo" ;;  # unknown → safe default
  esac
}

# Invoke a coding agent with a prompt file.
# This is the SINGLE function workers should call.
#
# Usage:
#   invoke_coding_agent \
#     [--tool devin] \
#     --role backend-dev \
#     --worktree /path/to/worktree \
#     --task-id T1 \
#     --prompt-file .devin-handoff.md \
#     [--timeout 3600] \
#     [--model <override>] \
#     [--permission-mode <override>]
#
# The tool name may be positional (legacy): `invoke_coding_agent devin --role ...`
#
# Returns:
#   0 = coding agent launched successfully in the background
#   2 = argument or environment error
#   127 = coding agent binary not found
invoke_coding_agent() {
  local tool="" role="" worktree="" prompt_file="" task_id="" timeout="3600"
  local model_override="" perm_override=""

  while [ $# -gt 0 ]; do
    case "$1" in
      devin|claude-code|antigravity)
        if [ -z "$tool" ]; then
          tool="$1"; shift
        else
          log_error "invoke_coding_agent: tool already set to '$tool', got '$1' as extra positional"
          return 2
        fi
        ;;
      --tool) tool="$2"; shift 2 ;;
      --role) role="$2"; shift 2 ;;
      --worktree) worktree="$2"; shift 2 ;;
      --task-id) task_id="$2"; shift 2 ;;
      --prompt-file) prompt_file="$2"; shift 2 ;;
      --timeout) timeout="$2"; shift 2 ;;
      --model) model_override="$2"; shift 2 ;;
      --permission-mode) perm_override="$2"; shift 2 ;;
      *) log_error "invoke_coding_agent: unknown arg: $1"; return 2 ;;
    esac
  done

  if [ -z "$tool" ] || [ -z "$role" ] || [ -z "$prompt_file" ]; then
    log_error "invoke_coding_agent requires --tool, --role, --prompt-file (and --worktree is strongly recommended)"
    return 2
  fi

  if ! command -v "$tool" &>/dev/null; then
    log_error "Coding agent '$tool' not on PATH"
    return 127
  fi

  # Resolve model + mode
  local model perm
  if [ -n "$model_override" ]; then
    model="$model_override"
  else
    model=$(coding_agent_model_for_role "$role")
  fi
  if [ -n "$perm_override" ]; then
    perm="$perm_override"
  else
    perm=$(coding_agent_permission_mode "$role")
  fi

  # Resolve absolute paths and Windows-native equivalents for the devin binary.
  local worktree_win="" prompt_file_win=""
  if [ -n "$worktree" ]; then
    worktree="$(cd "$worktree" && pwd)"
    if [ ! -d "$worktree" ]; then
      log_error "Worktree not found: $worktree"
      return 2
    fi
    worktree_win="$worktree"
    if command -v cygpath &>/dev/null; then
      worktree_win=$(cygpath -w "$worktree")
    fi
    # Only prepend worktree when prompt_file is relative.
    case "$prompt_file" in
      /*|[A-Za-z]:/*|[A-Za-z]:\\*) : ;;
      *) prompt_file="$worktree/$prompt_file" ;;
    esac
    prompt_file_win="$worktree_win\\$(basename "$prompt_file")"
  fi

  if [ ! -f "$prompt_file" ]; then
    log_error "Prompt file not found: $prompt_file"
    return 2
  fi

  # Ensure prompt_file_win is a native Windows path for the devin binary.
  if [ -z "$prompt_file_win" ]; then
    prompt_file_win="$prompt_file"
  fi
  if command -v cygpath &>/dev/null && [[ ! "$prompt_file_win" =~ ^[A-Za-z]: ]]; then
    prompt_file_win=$(cygpath -w "$prompt_file" 2>/dev/null || echo "$prompt_file_win")
  fi

  # Generate a log/export file path in the worktree (or /tmp if no worktree).
  local log_file export_file
  if [ -n "$worktree" ]; then
    if [ -n "$task_id" ]; then
      log_file="$worktree/.devin-out-${task_id}.log"
    else
      log_file="$worktree/.devin-out-$(date +%s).log"
    fi
  else
    if [ -n "$task_id" ]; then
      log_file="/tmp/.devin-out-${task_id}.log"
    else
      log_file="/tmp/.devin-out-$(date +%s).log"
    fi
  fi
  export_file="${log_file%.log}.json"

  log_info "Invoking $tool: model=$model mode=$perm timeout=${timeout}s"
  log_info "Prompt: $prompt_file (win: $prompt_file_win)"
  log_info "Log: $log_file"

  # Dispatch to tool-specific invoker
  case "$tool" in
    devin) _invoke_devin "$worktree" "$prompt_file_win" "$model" "$perm" "$timeout" "$log_file" "$export_file" ;;
    claude-code) _invoke_claude_code "$worktree" "$prompt_file" "$model" "$perm" "$timeout" "$log_file" ;;
    *) log_error "Unknown coding agent: $tool"; return 2 ;;
  esac
}

# ─── Tool-Specific Invokers ─────────────────────────────────────────

# Devin v2026.7.23 invocation.
# Runs non-interactively (`-p`) with `--prompt-file`, role model,
# `--permission-mode yolo`, and `--export`. The process is detached with
# `nohup` so the agent can poll `devin_check` without blocking.
_invoke_devin() {
  local worktree="$1" prompt_file="$2" model="$3" perm="$4" timeout="$5" log_file="$6" export_file="$7"

  # For non-interactive factory runs the only verified-safe mode is yolo.
  if [ "$perm" != "yolo" ]; then
    log_warn "Devin non-interactive mode requires 'yolo' — converting '$perm' to 'yolo'"
    perm="yolo"
  fi

  # Build the command as a bash string. Paths/model names with spaces are
  # protected by single quotes because the command is executed with bash -c.
  # Always use -p/--print so Devin exits after processing the prompt file.
  local cmd="devin -p --prompt-file '$prompt_file' --model '$model' --permission-mode '$perm' --export '$export_file'"

  if [ -n "$worktree" ]; then
    (
      cd "$worktree"
      log_info "cd $worktree && $cmd"
      # Run devin in the background with a hard timeout so the agent can
      # poll progress without blocking on the 600s terminal-tool limit.
      # Use /usr/bin/timeout explicitly: on Windows Git Bash, a bare `timeout`
      # can resolve to C:\Windows\System32\timeout.exe, which cannot execute
      # a command and uses a different syntax. Disown where possible.
      nohup /usr/bin/timeout "$timeout" bash -c "$cmd" > "$log_file" 2>&1 &
      local devin_pid=$!
      disown 2>/dev/null || true
      echo "$devin_pid" > "$worktree/.devin-pid"
    )
    log_ok "Devin started in background: pid=$(cat "$worktree/.devin-pid"), log=$log_file"
  else
    log_info "$cmd"
    nohup /usr/bin/timeout "$timeout" bash -c "$cmd" > "$log_file" 2>&1 &
    local devin_pid=$!
    disown 2>/dev/null || true
    echo "$devin_pid" > "/tmp/.devin-pid"
    log_ok "Devin started in background: pid=$devin_pid, log=$log_file"
  fi

  # Return success — the agent must poll `devin_check` to monitor completion.
  return 0
}

# Claude Code invocation (placeholder — adapt when needed)
_invoke_claude_code() {
  local worktree="$1" prompt_file="$2" model="$3" perm="$4" timeout="$5" log_file="$6"

  log_warn "claude-code invoker not fully implemented — falling back to generic"
  local cmd="claude"
  cmd+=" --model '$model'"
  cmd+=" --permission-mode '$perm'"

  if [ -n "$worktree" ]; then
    (
      cd "$worktree"
      /usr/bin/timeout "$timeout" bash -c "$cmd < '$prompt_file'" > "$log_file" 2>&1
    )
  else
    /usr/bin/timeout "$timeout" bash -c "$cmd < '$prompt_file'" > "$log_file" 2>&1
  fi
}

# ─── Polling Helpers ────────────────────────────────────────────────

# Check on a running devin process. Returns:
#   0  = devin exited cleanly (or with failure)
#   1  = devin still running
#   2  = devin PID not found / log file missing
# Usage: devin_check <worktree>
devin_check() {
  local worktree="$1"
  local pid_file="$worktree/.devin-pid"
  local log_file
  log_file=$(ls -t "$worktree"/.devin-out-*.log 2>/dev/null | head -1)

  if [ ! -f "$pid_file" ]; then
    log_warn "No .devin-pid in $worktree — was devin started here?"
    return 2
  fi
  local pid
  pid=$(cat "$pid_file")

  if ! kill -0 "$pid" 2>/dev/null; then
    log_ok "Devin PID $pid has exited"
    return 0
  fi

  log_info "Devin PID $pid still running (log: $log_file)"
  return 1
}

# Get the devin session ID for resume.
# Usage: devin_session_id <worktree>
devin_session_id() {
  local worktree="$1"
  (
    cd "$worktree"
    devin list --format json 2>/dev/null \
      | python_win -c "import json,sys; d=json.load(sys.stdin); print(d[0]['id']) if d else print('')"
  )
}

# ─── Process Hygiene ────────────────────────────────────────────────

# Kill stale devin.exe children from prior killed sessions.
# This prevents zombie `devin.exe --resume` or `--prompt-file` processes from
# competing for ports, trusted-directory state, and cloud session quota.
# Usage: kill_stale_devin
kill_stale_devin() {
  if command -v taskkill &>/dev/null; then
    # Windows: taskkill by image name (best-effort, not fatal)
    taskkill /F /IM devin.exe /T 2>/dev/null || true
  else
    # POSIX/WSL: kill matching processes
    local pids
    pids=$(ps -ef 2>/dev/null | grep -E 'devin\.exe.*(--resume|--prompt-file)' | grep -v grep | awk '{print $2}' || true)
    if [ -n "$pids" ]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
    fi
  fi
}

# ─── Handoff File Builder ───────────────────────────────────────────

# Write a structured handoff file that Devin can consume.
# Usage:
#   build_devin_handoff <output-file> \
#     --task "Title" \
#     --context-file <path> \
#     --acceptance "criterion 1" --acceptance "criterion 2" \
#     --constraint "use UV" --constraint "no new deps"
build_devin_handoff() {
  local output="$1"; shift
  local task="" context_file="" constraints=() acceptance=()

  while [ $# -gt 0 ]; do
    case "$1" in
      --task) task="$2"; shift 2 ;;
      --context-file) context_file="$2"; shift 2 ;;
      --acceptance) acceptance+=("$2"); shift 2 ;;
      --constraint) constraints+=("$2"); shift 2 ;;
      *) log_error "build_devin_handoff: unknown arg: $1"; return 2 ;;
    esac
  done

  # Ensure the parent directory exists before writing the handoff file.
  mkdir -p "$(dirname "$output")"

  {
    echo "# Devin Task: $task"
    echo
    echo "## Context"
    if [ -n "$context_file" ] && [ -f "$context_file" ]; then
      cat "$context_file"
    else
      echo "(no additional context)"
    fi
    echo
    if [ ${#acceptance[@]} -gt 0 ]; then
      echo "## Acceptance Criteria"
      for c in "${acceptance[@]}"; do
        echo "- [ ] $c"
      done
      echo
    fi
    if [ ${#constraints[@]} -gt 0 ]; then
      echo "## Constraints"
      for c in "${constraints[@]}"; do
        echo "- $c"
      done
      echo
    fi
    echo "## Project Rules"
    echo "Read and follow the project's AGENTS.md and .agents/FACTORY.md before starting."
  } > "$output"

  log_ok "Wrote handoff: $output"
}
