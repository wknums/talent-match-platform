#!/usr/bin/env bash
# Common bash functions for Spec-Driven Development workflow

get_repo_root() {
  local root
  root=$(git rev-parse --show-toplevel 2>/dev/null)
  if [ $? -eq 0 ] && [ -n "$root" ]; then
    echo "$root"
    return
  fi
  # Fall back to script location for non-git repos
  echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
}

get_current_branch() {
  # First check if SPECIFY_FEATURE environment variable is set
  if [ -n "${SPECIFY_FEATURE:-}" ]; then
    echo "$SPECIFY_FEATURE"
    return
  fi

  # Then check git if available
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ $? -eq 0 ] && [ -n "$branch" ]; then
    echo "$branch"
    return
  fi

  # For non-git repos, try to find the latest feature directory
  local repo_root specs_dir latest_feature highest num
  repo_root=$(get_repo_root)
  specs_dir="$repo_root/specs"

  if [ -d "$specs_dir" ]; then
    highest=0
    latest_feature=""
    for dir in "$specs_dir"/*/; do
      [ -d "$dir" ] || continue
      local name
      name=$(basename "$dir")
      if [[ "$name" =~ ^([0-9]{3})- ]]; then
        num=$((10#${BASH_REMATCH[1]}))
        if [ "$num" -gt "$highest" ]; then
          highest=$num
          latest_feature=$name
        fi
      fi
    done
    if [ -n "$latest_feature" ]; then
      echo "$latest_feature"
      return
    fi
  fi

  echo "main"
}

has_git() {
  git rev-parse --show-toplevel &>/dev/null
}

test_feature_branch() {
  local branch="$1"
  local has_git_flag="${2:-true}"

  if [ "$has_git_flag" != "true" ]; then
    echo "WARNING: [specify] Git repository not detected; skipped branch validation" >&2
    return 0
  fi

  if ! [[ "$branch" =~ ^[0-9]{3}- ]]; then
    echo "ERROR: Not on a feature branch. Current branch: $branch"
    echo "Feature branches should be named like: 001-feature-name"
    return 1
  fi
  return 0
}

get_feature_dir() {
  local repo_root="$1"
  local branch="$2"
  echo "$repo_root/specs/$branch"
}

# Sets global variables for feature paths
set_feature_paths() {
  REPO_ROOT=$(get_repo_root)
  CURRENT_BRANCH=$(get_current_branch)
  HAS_GIT=$(has_git && echo "true" || echo "false")
  FEATURE_DIR=$(get_feature_dir "$REPO_ROOT" "$CURRENT_BRANCH")
  FEATURE_SPEC="$FEATURE_DIR/spec.md"
  IMPL_PLAN="$FEATURE_DIR/plan.md"
  TASKS="$FEATURE_DIR/tasks.md"
  RESEARCH="$FEATURE_DIR/research.md"
  DATA_MODEL="$FEATURE_DIR/data-model.md"
  QUICKSTART="$FEATURE_DIR/quickstart.md"
  CONTRACTS_DIR="$FEATURE_DIR/contracts"
}

test_file_exists() {
  local path="$1"
  local description="$2"
  if [ -f "$path" ]; then
    echo "  ✓ $description"
    return 0
  else
    echo "  ✗ $description"
    return 1
  fi
}

test_dir_has_files() {
  local path="$1"
  local description="$2"
  if [ -d "$path" ] && [ -n "$(find "$path" -maxdepth 1 -type f 2>/dev/null | head -1)" ]; then
    echo "  ✓ $description"
    return 0
  else
    echo "  ✗ $description"
    return 1
  fi
}

# Returns true if running inside WSL
is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qi microsoft /proc/version 2>/dev/null
}

# Converts a path to the native OS format.
# On WSL, converts /mnt/c/... to C:/... so Windows tools can consume the path.
# On native Linux/macOS, returns the path unchanged.
to_native_path() {
  local path="$1"
  if is_wsl && command -v wslpath &>/dev/null; then
    wslpath -m "$path"
  else
    echo "$path"
  fi
}
