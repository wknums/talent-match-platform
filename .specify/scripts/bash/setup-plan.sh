#!/usr/bin/env bash
# Setup implementation plan for a feature

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
JSON=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json|-Json) JSON=true; shift ;;
    --help|-h|-Help)
      echo "Usage: ./setup-plan.sh [--json] [--help]"
      echo "  --json     Output results in JSON format"
      echo "  --help     Show this help message"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Source common functions
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# Get feature paths
set_feature_paths

# Check if we're on a proper feature branch
if ! test_feature_branch "$CURRENT_BRANCH" "$HAS_GIT"; then
  exit 1
fi

# Ensure the feature directory exists
mkdir -p "$FEATURE_DIR"

# Copy plan template if it exists
template="$REPO_ROOT/.specify/templates/plan-template.md"
if [ -f "$template" ]; then
  cp "$template" "$IMPL_PLAN"
  echo "Copied plan template to $IMPL_PLAN"
else
  echo "WARNING: Plan template not found at $template" >&2
  touch "$IMPL_PLAN"
fi

# Output results
if [ "$JSON" = true ]; then
  printf '{"FEATURE_SPEC":"%s","IMPL_PLAN":"%s","SPECS_DIR":"%s","BRANCH":"%s","HAS_GIT":%s}\n' \
    "$(to_native_path "$FEATURE_SPEC")" "$(to_native_path "$IMPL_PLAN")" "$(to_native_path "$FEATURE_DIR")" "$CURRENT_BRANCH" "$HAS_GIT"
else
  echo "FEATURE_SPEC: $(to_native_path "$FEATURE_SPEC")"
  echo "IMPL_PLAN: $(to_native_path "$IMPL_PLAN")"
  echo "SPECS_DIR: $(to_native_path "$FEATURE_DIR")"
  echo "BRANCH: $CURRENT_BRANCH"
  echo "HAS_GIT: $HAS_GIT"
fi
