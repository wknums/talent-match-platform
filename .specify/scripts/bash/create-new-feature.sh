#!/usr/bin/env bash
# Create a new feature

set -euo pipefail

# Parse arguments
JSON=false
SHORT_NAME=""
NUMBER=0
FEATURE_DESC=""

show_help() {
  cat <<EOF
Usage: ./create-new-feature.sh [OPTIONS] <feature description>

Options:
  --json                Output in JSON format
  --short-name <name>   Provide a custom short name (2-4 words) for the branch
  --number N            Specify branch number manually (overrides auto-detection)
  --help, -h            Show this help message

Examples:
  ./create-new-feature.sh 'Add user authentication system' --short-name 'user-auth'
  ./create-new-feature.sh 'Implement OAuth2 integration for API'
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json|-Json) JSON=true; shift ;;
    --short-name|-ShortName) SHORT_NAME="$2"; shift 2 ;;
    --number|-Number) NUMBER="$2"; shift 2 ;;
    --help|-h|-Help) show_help ;;
    -*) echo "Unknown option: $1"; exit 1 ;;
    *) FEATURE_DESC="${FEATURE_DESC:+$FEATURE_DESC }$1"; shift ;;
  esac
done

if [ -z "$FEATURE_DESC" ]; then
  echo "ERROR: Usage: ./create-new-feature.sh [--json] [--short-name <name>] <feature description>" >&2
  exit 1
fi

# --- Helper functions ---

find_repo_root() {
  local current="$1"
  while true; do
    for marker in .git .specify; do
      if [ -e "$current/$marker" ]; then
        echo "$current"
        return
      fi
    done
    local parent
    parent=$(dirname "$current")
    if [ "$parent" = "$current" ]; then
      return 1
    fi
    current="$parent"
  done
}

get_highest_from_specs() {
  local specs_dir="$1"
  local highest=0
  if [ -d "$specs_dir" ]; then
    for dir in "$specs_dir"/*/; do
      [ -d "$dir" ] || continue
      local name
      name=$(basename "$dir")
      if [[ "$name" =~ ^([0-9]+)- ]]; then
        local num=$((10#${BASH_REMATCH[1]}))
        [ "$num" -gt "$highest" ] && highest=$num
      fi
    done
  fi
  echo "$highest"
}

get_highest_from_branches() {
  local highest=0
  local branches
  branches=$(git branch -a 2>/dev/null) || { echo 0; return; }
  while IFS= read -r branch; do
    # Clean branch name
    local clean
    clean=$(echo "$branch" | sed 's/^[* ]*//' | sed 's|^remotes/[^/]*/||')
    if [[ "$clean" =~ ^([0-9]+)- ]]; then
      local num=$((10#${BASH_REMATCH[1]}))
      [ "$num" -gt "$highest" ] && highest=$num
    fi
  done <<< "$branches"
  echo "$highest"
}

get_next_branch_number() {
  local specs_dir="$1"
  # Fetch all remotes
  git fetch --all --prune 2>/dev/null || true
  local highest_branch highest_spec max_num
  highest_branch=$(get_highest_from_branches)
  highest_spec=$(get_highest_from_specs "$specs_dir")
  max_num=$((highest_branch > highest_spec ? highest_branch : highest_spec))
  echo $((max_num + 1))
}

clean_branch_name() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//'
}

get_branch_name() {
  local description="$1"
  local stop_words="i a an the to for of in on at by with from is are was were be been being have has had do does did will would should could can may might must shall this that these those my your our their want need add get set"

  local clean_name
  clean_name=$(echo "$description" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9 ]/ /g')

  local meaningful=()
  for word in $clean_name; do
    # Skip stop words
    local is_stop=false
    for sw in $stop_words; do
      if [ "$word" = "$sw" ]; then
        is_stop=true
        break
      fi
    done
    [ "$is_stop" = true ] && continue
    # Keep words length >= 3
    if [ "${#word}" -ge 3 ]; then
      meaningful+=("$word")
    fi
  done

  if [ "${#meaningful[@]}" -gt 0 ]; then
    local max_words=3
    [ "${#meaningful[@]}" -eq 4 ] && max_words=4
    local result
    result=$(printf '%s\n' "${meaningful[@]}" | head -n "$max_words" | paste -sd '-' -)
    echo "$result"
  else
    local fallback
    fallback=$(clean_branch_name "$description")
    echo "$fallback" | tr '-' '\n' | head -3 | paste -sd '-' -
  fi
}

# --- Main logic ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

fallback_root=$(find_repo_root "$SCRIPT_DIR") || {
  echo "Error: Could not determine repository root." >&2
  exit 1
}

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) && has_git=true || {
  repo_root="$fallback_root"
  has_git=false
}

cd "$repo_root"

specs_dir="$repo_root/specs"
mkdir -p "$specs_dir"

# Generate branch name
if [ -n "$SHORT_NAME" ]; then
  branch_suffix=$(clean_branch_name "$SHORT_NAME")
else
  branch_suffix=$(get_branch_name "$FEATURE_DESC")
fi

# Determine branch number
if [ "$NUMBER" -eq 0 ]; then
  if [ "$has_git" = true ]; then
    NUMBER=$(get_next_branch_number "$specs_dir")
  else
    NUMBER=$(( $(get_highest_from_specs "$specs_dir") + 1 ))
  fi
fi

feature_num=$(printf '%03d' "$NUMBER")
branch_name="$feature_num-$branch_suffix"

# GitHub enforces a 244-byte limit on branch names
max_branch_length=244
if [ "${#branch_name}" -gt "$max_branch_length" ]; then
  max_suffix_length=$((max_branch_length - 4))
  truncated_suffix="${branch_suffix:0:$max_suffix_length}"
  truncated_suffix=$(echo "$truncated_suffix" | sed 's/-$//')
  echo "WARNING: [specify] Branch name exceeded GitHub's 244-byte limit" >&2
  echo "WARNING: [specify] Truncated to: $feature_num-$truncated_suffix" >&2
  branch_name="$feature_num-$truncated_suffix"
fi

if [ "$has_git" = true ]; then
  git checkout -b "$branch_name" 2>/dev/null || echo "WARNING: Failed to create git branch: $branch_name" >&2
else
  echo "WARNING: [specify] Git repository not detected; skipped branch creation for $branch_name" >&2
fi

feature_dir="$specs_dir/$branch_name"
mkdir -p "$feature_dir"

template="$repo_root/.specify/templates/spec-template.md"
spec_file="$feature_dir/spec.md"
if [ -f "$template" ]; then
  cp "$template" "$spec_file"
else
  touch "$spec_file"
fi

# Set the SPECIFY_FEATURE environment variable
export SPECIFY_FEATURE="$branch_name"

if [ "$JSON" = true ]; then
  printf '{"BRANCH_NAME":"%s","SPEC_FILE":"%s","FEATURE_NUM":"%s","HAS_GIT":%s}\n' \
    "$branch_name" "$(to_native_path "$spec_file")" "$feature_num" "$has_git"
else
  echo "BRANCH_NAME: $branch_name"
  echo "SPEC_FILE: $(to_native_path "$spec_file")"
  echo "FEATURE_NUM: $feature_num"
  echo "HAS_GIT: $has_git"
  echo "SPECIFY_FEATURE environment variable set to: $branch_name"
fi
