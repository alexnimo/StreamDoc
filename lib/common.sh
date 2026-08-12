#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
# Dark Factory — Common Library
# Shared helpers: env loading, YAML parsing, logging, dependency checks.
# Target runtime: Git Bash on Windows (and WSL/Linux compatible).
# ════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Logging ───────────────────────────────────────────────────────

log_info()  { printf '\033[0;34m[INFO]\033[0m  %s\n' "$*" >&2; }
log_warn()  { printf '\033[0;33m[WARN]\033[0m %s\n' "$*" >&2; }
log_error() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; }
log_ok()    { printf '\033[0;32m[OK]\033[0m   %s\n' "$*" >&2; }

# ─── Factory Root ───────────────────────────────────────────────────
# Scripts must set DF_ROOT before sourcing this library. If not set,
# compute it from the location of this file.

if [ -z "${DF_ROOT:-}" ]; then
  DF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  export DF_ROOT
fi

CONFIG_DIR="${DF_ROOT}/config"
ENV_FILE="${CONFIG_DIR}/.env"

# Single config file. The old split into factory.yaml, pollers.yaml, and
# projects.yaml was consolidated into dark-factory.yaml. All three variables
# point to the same file for backward compat with scripts that refer to each.
FACTORY_CONFIG="${CONFIG_DIR}/dark-factory.yaml"
POLLERS_CONFIG="${CONFIG_DIR}/dark-factory.yaml"
PROJECTS_CONFIG="${CONFIG_DIR}/dark-factory.yaml"

# Backward compat: some scripts reference CONFIG_FILE. Point it at factory.yaml
# since that's the most commonly used file.
CONFIG_FILE="$FACTORY_CONFIG"

# Windows-native Python (Git Bash) cannot read /c/... paths. Convert when needed.
config_path_for_python() {
  local path="${1//$'\r'/}"
  # If the path is already a Windows absolute path, return it as-is.
  # wslpath/cygpath would otherwise treat "C:/..." as a relative path
  # and prepend the current WSL/Git Bash working directory.
  if [[ "$path" =~ ^[A-Za-z]:[/\\] ]]; then
    echo "$path"
    return 0
  fi
  if command -v cygpath &>/dev/null; then
    cygpath -w "$path"
  elif command -v wslpath &>/dev/null; then
    wslpath -w "$path"
  else
    echo "$path"
  fi
}

# Pre-compute Windows paths for all config files.
FACTORY_CONFIG_WIN="$(config_path_for_python "$FACTORY_CONFIG")"
POLLERS_CONFIG_WIN="$(config_path_for_python "$POLLERS_CONFIG")"
PROJECTS_CONFIG_WIN="$(config_path_for_python "$PROJECTS_CONFIG")"
CONFIG_FILE_WIN="$FACTORY_CONFIG_WIN"
export FACTORY_CONFIG_WIN POLLERS_CONFIG_WIN PROJECTS_CONFIG_WIN CONFIG_FILE_WIN

# ─── Environment Loading ─────────────────────────────────────────────

load_env() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi
}

require_var() {
  local var="$1"
  if [ -z "${!var:-}" ]; then
    log_error "Required environment variable is not set: $var"
    exit 1
  fi
}

# ─── Dependency Checks ─────────────────────────────────────────────
# Git Bash often lacks jq/python3; we probe for common aliases.

find_python() {
  # Test actual execution (Windows app-execution aliases may be on PATH but fail).
  # Prefer Windows-native python on WSL/Git Bash because config_path_for_python
  # returns Windows paths.
  if command -v python.exe &>/dev/null && python.exe -c "import yaml" >/dev/null 2>&1; then
    echo "python.exe"
  elif command -v python &>/dev/null && python -c "import yaml" >/dev/null 2>&1; then
    echo "python"
  elif command -v python3 &>/dev/null && python3 -c "import yaml" >/dev/null 2>&1; then
    echo "python3"
  else
    echo ""
  fi
}

# Windows-native Python emits CRLF on stdout. Strip \r so shell consumers stay clean.
python_win() {
  "$PYTHON_BIN" "$@" | tr -d '\r'
}

# Windows-native jq also emits CRLF line endings. Wrap it to keep shell variables clean.
jq_win() {
  jq "$@" | tr -d '\r'
}

find_jq() {
  if command -v jq &>/dev/null; then
    echo "jq_win"
  else
    echo ""
  fi
}

PYTHON_BIN="${PYTHON_BIN:-$(find_python)}"
JQ_BIN="${JQ_BIN:-$(find_jq)}"

check_dependencies() {
  local missing=()

  command -v bash &>/dev/null   || missing+=("bash")
  command -v git &>/dev/null    || missing+=("git")
  command -v curl &>/dev/null   || missing+=("curl")
  command -v date &>/dev/null   || missing+=("date")
  command -v sha256sum &>/dev/null || missing+=("sha256sum")
  type -P hermes &>/dev/null || type -P hermes.exe &>/dev/null || missing+=("hermes")

  if [ -z "$JQ_BIN" ]; then
    missing+=("jq")
  fi
  if [ -z "$PYTHON_BIN" ]; then
    missing+=("python3 or python")
  fi

  if [ ${#missing[@]} -gt 0 ]; then
    log_error "Missing required dependencies: ${missing[*]}"
    log_info "Install them and rerun. jq/python may be required for config parsing."
    exit 1
  fi
}

# ─── YAML Parsing (requires python3) ─────────────────────────────────
# get_yaml searches all three config files in order (factory, pollers,
# projects) and returns the first non-empty match. This lets callers use
# a single key path (e.g., "profiles.architect.model" or "pollers.linear")
# without knowing which file it lives in.
#
# get_yaml_from reads from a specific config file (first arg = Windows path).

get_yaml() {
  local key="$1"
  python_win -c "
import yaml, sys
config_paths = [
    r'''${FACTORY_CONFIG_WIN}''',
    r'''${POLLERS_CONFIG_WIN}''',
    r'''${PROJECTS_CONFIG_WIN}''',
]
keys = '''${key}'''.split('.')
for config_path in config_paths:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except (FileNotFoundError, OSError):
        continue
    if data is None:
        continue
    val = data
    found = True
    for k in keys:
        if not isinstance(val, dict):
            found = False
            break
        val = val.get(k)
        if val is None:
            found = False
            break
    if found and val is not None:
        if isinstance(val, (list, dict)):
            print(yaml.dump(val, default_flow_style=False).strip())
        elif isinstance(val, bool):
            print('true' if val else 'false')
        else:
            print(val)
        sys.exit(0)
print('')
"
}

get_yaml_from() {
  local file_win="$1"
  local key="$2"
  python_win -c "
import yaml, sys
config_path = r'''${file_win}'''
with open(config_path, 'r', encoding='utf-8') as f:
    data = yaml.safe_load(f)
keys = '''${key}'''.split('.')
val = data
for k in keys:
    if not isinstance(val, dict):
        print('')
        sys.exit(0)
    val = val.get(k)
    if val is None:
        print('')
        sys.exit(0)
if isinstance(val, (list, dict)):
    print(yaml.dump(val, default_flow_style=False).strip())
elif isinstance(val, bool):
    print('true' if val else 'false')
else:
    print(val)
"
}

get_yaml_array() {
  local key="$1"
  python_win -c "
import yaml, sys
config_paths = [
    r'''${FACTORY_CONFIG_WIN}''',
    r'''${POLLERS_CONFIG_WIN}''',
    r'''${PROJECTS_CONFIG_WIN}''',
]
keys = '''${key}'''.split('.')
for config_path in config_paths:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except (FileNotFoundError, OSError):
        continue
    if data is None:
        continue
    val = data
    found = True
    for k in keys:
        if not isinstance(val, dict):
            found = False
            break
        val = val.get(k, [])
    if found and isinstance(val, list):
        for item in val:
            print(item)
        sys.exit(0)
print('')
"
}

get_yaml_bool() {
  local val
  val=$(get_yaml "$1")
  case "${val,,}" in
    true|1|yes|on)  return 0 ;;
    *)              return 1 ;;
  esac
}

# List the keys under a given path in a specific config file.
# Args: file_win  key_path
# Output: one key per line on stdout.
get_yaml_keys_from() {
  local file_win="$1"
  local key_path="$2"
  python_win -c "
import yaml, sys
config_path = r'''${file_win}'''
with open(config_path, 'r', encoding='utf-8') as f:
    data = yaml.safe_load(f)
keys = '''${key_path}'''.split('.') if '''${key_path}''' else []
val = data
for k in keys:
    if not isinstance(val, dict):
        sys.exit(0)
    val = val.get(k)
    if val is None:
        sys.exit(0)
if isinstance(val, dict):
    for k in val:
        print(k)
elif isinstance(val, list):
    for i, item in enumerate(val):
        if isinstance(item, dict) and 'name' in item:
            print(item['name'])
        else:
            print(str(i))
"
}

# List keys under a path, searching all config files. Returns keys from
# the first file that has a non-empty dict/list at that path.
get_yaml_keys() {
  local key_path="$1"
  local f
  for f in "$FACTORY_CONFIG_WIN" "$POLLERS_CONFIG_WIN" "$PROJECTS_CONFIG_WIN"; do
    local result
    result=$(get_yaml_keys_from "$f" "$key_path")
    if [ -n "$result" ]; then
      echo "$result"
      return 0
    fi
  done
}

# ─── Date helper ────────────────────────────────────────────────────

date_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ" | tr -d '\r'
}

# ─── Safe temp file creation ─────────────────────────────────────────

make_temp() {
  mktemp 2>/dev/null || mktemp -t df-XXXXXX
}

# ─── Project validation ─────────────────────────────────────────────

project_config_path() {
  local slug="$1"
  local path
  path=$(get_yaml "projects.${slug}.path")
  # Expand ~ if present
  path="${path/#\~/$HOME}"
  echo "$path"
}

project_exists_in_config() {
  local slug="$1"
  [ -n "$(get_yaml "projects.${slug}.path")" ]
}

# ─── Dry-run guard ────────────────────────────────────────────────────

is_dry_run() {
  [ "${DF_DRY_RUN:-false}" = "true" ]
}

run_or_dry() {
  if is_dry_run; then
    log_info "[DRY-RUN] would execute: $*"
    return 0
  fi
  "$@"
}

# ─── Hermes CLI wrapper ──────────────────────────────────────────────
# Cron jobs and minimal PATH environments may not find the hermes binary,
# and on Windows the executable is often named hermes.exe. HERMES_BIN
# overrides auto-resolution; otherwise we probe for hermes then hermes.exe.

hermes() {
  local hermes_bin="${HERMES_BIN:-}"
  if [ -z "$hermes_bin" ]; then
    hermes_bin=$(type -P hermes || type -P hermes.exe || true)
  fi
  if [ -z "$hermes_bin" ]; then
    log_error "hermes binary not found in PATH"
    return 127
  fi
  command "$hermes_bin" "$@"
}

# ─── Hermes Home / Scripts Directory ─────────────────────────────────
# Hermes on Windows stores its home under %LOCALAPPDATA%\hermes, not
# ~/.hermes. Resolve the actual home from `hermes config path` and
# convert to a shell-usable Unix path.

hermes_home_dir() {
  local config_path
  config_path=$(hermes config path 2>/dev/null | tr -d '\r' || true)
  if [ -z "$config_path" ]; then
    config_path="${HOME}/.hermes/config.yaml"
  fi
  # Convert only Windows-style paths. On WSL, `hermes config path` already
  # returns a Unix path; wslpath -u would incorrectly remap it under /mnt/c.
  if [[ "$config_path" =~ ^[A-Za-z]:[\\/] ]] || [[ "$config_path" =~ ^\\\\ ]]; then
    if command -v cygpath &>/dev/null; then
      config_path=$(cygpath -u "$config_path" 2>/dev/null || echo "$config_path")
    elif command -v wslpath &>/dev/null; then
      config_path=$(wslpath -u "$config_path" 2>/dev/null || echo "$config_path")
    fi
  fi
  dirname "$config_path"
}

hermes_scripts_dir() {
  echo "$(hermes_home_dir)/scripts"
}
