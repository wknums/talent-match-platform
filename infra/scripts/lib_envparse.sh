#!/usr/bin/env bash
# Shared .env parser. Sources via:  source lib_envparse.sh; parse_env_file path
# Populates the associative array ENV_VARS and provides get_env / to_bool.

# Ensure MSYS does not mangle ARM resource IDs on Git Bash (Windows).
export MSYS_NO_PATHCONV="${MSYS_NO_PATHCONV:-1}"

declare -gA ENV_VARS

parse_env_file() {
  local env_file="$1"
  if [[ ! -f "$env_file" ]]; then
    echo "ERROR: env file not found: $env_file" >&2
    return 1
  fi
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key="${key//[[:space:]]/}"
    [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && continue
    value="${value%$'\r'}"
    value="${value%%#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    ENV_VARS["$key"]="$value"
  done < "$env_file"
}

get_env() { echo "${ENV_VARS[$1]:-${2:-}}"; }
to_bool() { [[ "${1^^}" == "TRUE" ]] && echo "true" || echo "false"; }
