#!/usr/bin/env bash
# Update agent context files with information from plan.md
#
# Usage:
#   ./update-agent-context.sh [agent-type]
#
# If agent-type is omitted, updates all existing agent files.
# Valid types: claude, gemini, copilot, cursor-agent, qwen, opencode, codex,
#              windsurf, kilocode, auggie, roo, codebuddy, amp, shai, q, agy, bob, qodercli, generic

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

AGENT_TYPE="${1:-}"

# Set feature paths
set_feature_paths

NEW_PLAN="$IMPL_PLAN"

# Agent file paths
CLAUDE_FILE="$REPO_ROOT/CLAUDE.md"
GEMINI_FILE="$REPO_ROOT/GEMINI.md"
COPILOT_FILE="$REPO_ROOT/.github/agents/copilot-instructions.md"
CURSOR_FILE="$REPO_ROOT/.cursor/rules/specify-rules.mdc"
QWEN_FILE="$REPO_ROOT/QWEN.md"
AGENTS_FILE="$REPO_ROOT/AGENTS.md"
WINDSURF_FILE="$REPO_ROOT/.windsurf/rules/specify-rules.md"
KILOCODE_FILE="$REPO_ROOT/.kilocode/rules/specify-rules.md"
AUGGIE_FILE="$REPO_ROOT/.augment/rules/specify-rules.md"
ROO_FILE="$REPO_ROOT/.roo/rules/specify-rules.md"
CODEBUDDY_FILE="$REPO_ROOT/CODEBUDDY.md"
QODER_FILE="$REPO_ROOT/QODER.md"
AMP_FILE="$REPO_ROOT/AGENTS.md"
SHAI_FILE="$REPO_ROOT/SHAI.md"
Q_FILE="$REPO_ROOT/AGENTS.md"
AGY_FILE="$REPO_ROOT/.agent/rules/specify-rules.md"
BOB_FILE="$REPO_ROOT/AGENTS.md"

TEMPLATE_FILE="$REPO_ROOT/.specify/templates/agent-file-template.md"

# Parsed plan data
NEW_LANG=""
NEW_FRAMEWORK=""
NEW_DB=""
NEW_PROJECT_TYPE=""

info()    { echo "INFO: $1"; }
success() { echo "✓ $1"; }
warn_msg(){ echo "WARNING: $1" >&2; }
err_msg() { echo "ERROR: $1" >&2; }

validate_environment() {
  if [ -z "$CURRENT_BRANCH" ]; then
    err_msg "Unable to determine current feature"
    if [ "$HAS_GIT" = "true" ]; then
      info "Make sure you're on a feature branch"
    else
      info "Set SPECIFY_FEATURE environment variable or create a feature first"
    fi
    exit 1
  fi
  if [ ! -f "$NEW_PLAN" ]; then
    err_msg "No plan.md found at $NEW_PLAN"
    info "Ensure you are working on a feature with a corresponding spec directory"
    exit 1
  fi
  if [ ! -f "$TEMPLATE_FILE" ]; then
    err_msg "Template file not found at $TEMPLATE_FILE"
    info "Run specify init to scaffold .specify/templates, or add agent-file-template.md there."
    exit 1
  fi
}

extract_plan_field() {
  local pattern="$1"
  local plan_file="$2"
  [ -f "$plan_file" ] || return
  # Match lines like **Language/Version**: Python 3.12
  local escaped_pattern
  escaped_pattern=$(printf '%s' "$pattern" | sed 's/[.[\*^$/]/\\&/g')
  grep -E "^\*\*${escaped_pattern}\*\*: .+" "$plan_file" 2>/dev/null | head -1 | sed "s/^\*\*${escaped_pattern}\*\*: //" | sed 's/^[[:space:]]*//' | grep -v -E '^(NEEDS CLARIFICATION|N/A)$' || true
}

parse_plan_data() {
  local plan_file="$1"
  if [ ! -f "$plan_file" ]; then
    err_msg "Plan file not found: $plan_file"
    return 1
  fi
  info "Parsing plan data from $plan_file"
  NEW_LANG=$(extract_plan_field "Language/Version" "$plan_file")
  NEW_FRAMEWORK=$(extract_plan_field "Primary Dependencies" "$plan_file")
  NEW_DB=$(extract_plan_field "Storage" "$plan_file")
  NEW_PROJECT_TYPE=$(extract_plan_field "Project Type" "$plan_file")

  [ -n "$NEW_LANG" ] && info "Found language: $NEW_LANG" || warn_msg "No language information found in plan"
  [ -n "$NEW_FRAMEWORK" ] && info "Found framework: $NEW_FRAMEWORK"
  [ -n "$NEW_DB" ] && [ "$NEW_DB" != "N/A" ] && info "Found database: $NEW_DB"
  [ -n "$NEW_PROJECT_TYPE" ] && info "Found project type: $NEW_PROJECT_TYPE"
  return 0
}

format_technology_stack() {
  local parts=()
  [ -n "$NEW_LANG" ] && [ "$NEW_LANG" != "NEEDS CLARIFICATION" ] && parts+=("$NEW_LANG")
  [ -n "$NEW_FRAMEWORK" ] && [ "$NEW_FRAMEWORK" != "NEEDS CLARIFICATION" ] && [ "$NEW_FRAMEWORK" != "N/A" ] && parts+=("$NEW_FRAMEWORK")
  if [ ${#parts[@]} -eq 0 ]; then
    echo ""
  else
    local IFS=" + "
    echo "${parts[*]}"
  fi
}

get_project_structure() {
  if [[ "${NEW_PROJECT_TYPE:-}" =~ web ]]; then
    printf 'backend/\nfrontend/\ntests/'
  else
    printf 'src/\ntests/'
  fi
}

get_commands_for_language() {
  local lang="${1:-}"
  case "$lang" in
    *Python*) echo "cd src; pytest; ruff check ." ;;
    *Rust*) echo "cargo test; cargo clippy" ;;
    *JavaScript*|*TypeScript*) echo "npm test; npm run lint" ;;
    *) echo "# Add commands for $lang" ;;
  esac
}

get_language_conventions() {
  local lang="${1:-}"
  if [ -n "$lang" ]; then
    echo "${lang}: Follow standard conventions"
  else
    echo "General: Follow standard conventions"
  fi
}

create_agent_file() {
  local target_file="$1"
  local project_name="$2"
  local date_str="$3"

  if [ ! -f "$TEMPLATE_FILE" ]; then
    err_msg "Template not found at $TEMPLATE_FILE"
    return 1
  fi

  local tmpfile
  tmpfile=$(mktemp)
  cp "$TEMPLATE_FILE" "$tmpfile"

  local project_structure commands language_conventions
  project_structure=$(get_project_structure)
  commands=$(get_commands_for_language "$NEW_LANG")
  language_conventions=$(get_language_conventions "$NEW_LANG")

  local tech_stack_template=""
  if [ -n "$NEW_LANG" ] && [ -n "$NEW_FRAMEWORK" ]; then
    tech_stack_template="- $NEW_LANG + $NEW_FRAMEWORK ($CURRENT_BRANCH)"
  elif [ -n "$NEW_LANG" ]; then
    tech_stack_template="- $NEW_LANG ($CURRENT_BRANCH)"
  elif [ -n "$NEW_FRAMEWORK" ]; then
    tech_stack_template="- $NEW_FRAMEWORK ($CURRENT_BRANCH)"
  fi

  local recent_changes_template=""
  if [ -n "$NEW_LANG" ] && [ -n "$NEW_FRAMEWORK" ]; then
    recent_changes_template="- ${CURRENT_BRANCH}: Added ${NEW_LANG} + ${NEW_FRAMEWORK}"
  elif [ -n "$NEW_LANG" ]; then
    recent_changes_template="- ${CURRENT_BRANCH}: Added ${NEW_LANG}"
  elif [ -n "$NEW_FRAMEWORK" ]; then
    recent_changes_template="- ${CURRENT_BRANCH}: Added ${NEW_FRAMEWORK}"
  fi

  local content
  content=$(cat "$tmpfile")
  content="${content//\[PROJECT NAME\]/$project_name}"
  content="${content//\[DATE\]/$date_str}"
  content="${content//\[EXTRACTED FROM ALL PLAN.MD FILES\]/$tech_stack_template}"
  content="${content//\[ACTUAL STRUCTURE FROM PLANS\]/$project_structure}"
  content="${content//\[ONLY COMMANDS FOR ACTIVE TECHNOLOGIES\]/$commands}"
  content="${content//\[LANGUAGE-SPECIFIC, ONLY FOR LANGUAGES IN USE\]/$language_conventions}"
  content="${content//\[LAST 3 FEATURES AND WHAT THEY ADDED\]/$recent_changes_template}"

  # Prepend Cursor frontmatter for .mdc files
  if [[ "$target_file" == *.mdc ]]; then
    local frontmatter
    frontmatter="---
description: Project Development Guidelines
globs: [\"**/*\"]
alwaysApply: true
---
"
    content="$frontmatter$content"
  fi

  mkdir -p "$(dirname "$target_file")"
  printf '%s' "$content" > "$target_file"
  rm -f "$tmpfile"
  return 0
}

update_existing_agent_file() {
  local target_file="$1"
  local date_str="$2"

  if [ ! -f "$target_file" ]; then
    create_agent_file "$target_file" "$(basename "$REPO_ROOT")" "$date_str"
    return $?
  fi

  local tech_stack
  tech_stack=$(format_technology_stack)

  local new_tech_entries=()
  if [ -n "$tech_stack" ] && ! grep -qF "$tech_stack" "$target_file"; then
    new_tech_entries+=("- $tech_stack ($CURRENT_BRANCH)")
  fi
  if [ -n "$NEW_DB" ] && [ "$NEW_DB" != "N/A" ] && [ "$NEW_DB" != "NEEDS CLARIFICATION" ] && ! grep -qF "$NEW_DB" "$target_file"; then
    new_tech_entries+=("- $NEW_DB ($CURRENT_BRANCH)")
  fi

  local new_change_entry=""
  if [ -n "$tech_stack" ]; then
    new_change_entry="- ${CURRENT_BRANCH}: Added ${tech_stack}"
  elif [ -n "$NEW_DB" ] && [ "$NEW_DB" != "N/A" ] && [ "$NEW_DB" != "NEEDS CLARIFICATION" ]; then
    new_change_entry="- ${CURRENT_BRANCH}: Added ${NEW_DB}"
  fi

  local tmpfile
  tmpfile=$(mktemp)
  local in_tech=false in_changes=false tech_added=false change_added=false existing_changes=0

  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$line" = "## Active Technologies" ]; then
      echo "$line" >> "$tmpfile"
      in_tech=true
      continue
    fi
    if [ "$in_tech" = true ] && [[ "$line" =~ ^##\  ]]; then
      if [ "$tech_added" = false ] && [ ${#new_tech_entries[@]} -gt 0 ]; then
        printf '%s\n' "${new_tech_entries[@]}" >> "$tmpfile"
        tech_added=true
      fi
      echo "$line" >> "$tmpfile"
      in_tech=false
      continue
    fi
    if [ "$in_tech" = true ] && [ -z "${line// /}" ]; then
      if [ "$tech_added" = false ] && [ ${#new_tech_entries[@]} -gt 0 ]; then
        printf '%s\n' "${new_tech_entries[@]}" >> "$tmpfile"
        tech_added=true
      fi
      echo "$line" >> "$tmpfile"
      continue
    fi
    if [ "$line" = "## Recent Changes" ]; then
      echo "$line" >> "$tmpfile"
      if [ -n "$new_change_entry" ]; then
        echo "$new_change_entry" >> "$tmpfile"
        change_added=true
      fi
      in_changes=true
      continue
    fi
    if [ "$in_changes" = true ] && [[ "$line" =~ ^##\  ]]; then
      echo "$line" >> "$tmpfile"
      in_changes=false
      continue
    fi
    if [ "$in_changes" = true ] && [[ "$line" =~ ^-\  ]]; then
      if [ "$existing_changes" -lt 2 ]; then
        echo "$line" >> "$tmpfile"
        existing_changes=$((existing_changes + 1))
      fi
      continue
    fi
    if [[ "$line" =~ \*\*Last\ updated\*\*:.*[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
      echo "$line" | sed "s/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/$date_str/" >> "$tmpfile"
      continue
    fi
    echo "$line" >> "$tmpfile"
  done < "$target_file"

  # Post-loop: if still in Active Technologies and haven't added
  if [ "$in_tech" = true ] && [ "$tech_added" = false ] && [ ${#new_tech_entries[@]} -gt 0 ]; then
    printf '%s\n' "${new_tech_entries[@]}" >> "$tmpfile"
  fi

  # Ensure Cursor .mdc files have frontmatter
  if [[ "$target_file" == *.mdc ]]; then
    local first_line
    first_line=$(head -1 "$tmpfile")
    if [ "$first_line" != "---" ]; then
      local tmpfile2
      tmpfile2=$(mktemp)
      printf '%s\n' "---" "description: Project Development Guidelines" 'globs: ["**/*"]' "alwaysApply: true" "---" "" > "$tmpfile2"
      cat "$tmpfile" >> "$tmpfile2"
      mv "$tmpfile2" "$tmpfile"
    fi
  fi

  mv "$tmpfile" "$target_file"
  return 0
}

update_agent_file() {
  local target_file="$1"
  local agent_name="$2"
  [ -z "$target_file" ] || [ -z "$agent_name" ] && { err_msg "update_agent_file requires target_file and agent_name"; return 1; }
  info "Updating $agent_name context file: $target_file"
  local project_name date_str
  project_name=$(basename "$REPO_ROOT")
  date_str=$(date +%Y-%m-%d)

  mkdir -p "$(dirname "$target_file")"

  if [ ! -f "$target_file" ]; then
    if create_agent_file "$target_file" "$project_name" "$date_str"; then
      success "Created new $agent_name context file"
    else
      err_msg "Failed to create new agent file"
      return 1
    fi
  else
    if update_existing_agent_file "$target_file" "$date_str"; then
      success "Updated existing $agent_name context file"
    else
      err_msg "Failed to update agent file"
      return 1
    fi
  fi
  return 0
}

update_specific_agent() {
  local agent_type="$1"
  case "$agent_type" in
    claude)       update_agent_file "$CLAUDE_FILE"   "Claude Code" ;;
    gemini)       update_agent_file "$GEMINI_FILE"   "Gemini CLI" ;;
    copilot)      update_agent_file "$COPILOT_FILE"  "GitHub Copilot" ;;
    cursor-agent) update_agent_file "$CURSOR_FILE"   "Cursor IDE" ;;
    qwen)         update_agent_file "$QWEN_FILE"     "Qwen Code" ;;
    opencode)     update_agent_file "$AGENTS_FILE"   "opencode" ;;
    codex)        update_agent_file "$AGENTS_FILE"   "Codex CLI" ;;
    windsurf)     update_agent_file "$WINDSURF_FILE" "Windsurf" ;;
    kilocode)     update_agent_file "$KILOCODE_FILE" "Kilo Code" ;;
    auggie)       update_agent_file "$AUGGIE_FILE"   "Auggie CLI" ;;
    roo)          update_agent_file "$ROO_FILE"      "Roo Code" ;;
    codebuddy)    update_agent_file "$CODEBUDDY_FILE" "CodeBuddy CLI" ;;
    qodercli)     update_agent_file "$QODER_FILE"    "Qoder CLI" ;;
    amp)          update_agent_file "$AMP_FILE"      "Amp" ;;
    shai)         update_agent_file "$SHAI_FILE"     "SHAI" ;;
    q)            update_agent_file "$Q_FILE"        "Amazon Q Developer CLI" ;;
    agy)          update_agent_file "$AGY_FILE"      "Antigravity" ;;
    bob)          update_agent_file "$BOB_FILE"      "IBM Bob" ;;
    generic)      info "Generic agent: no predefined context file." ;;
    *) err_msg "Unknown agent type '$agent_type'"; return 1 ;;
  esac
}

update_all_existing_agents() {
  local found=false ok=true

  for entry in \
    "$CLAUDE_FILE:Claude Code" \
    "$GEMINI_FILE:Gemini CLI" \
    "$COPILOT_FILE:GitHub Copilot" \
    "$CURSOR_FILE:Cursor IDE" \
    "$QWEN_FILE:Qwen Code" \
    "$AGENTS_FILE:Codex/opencode" \
    "$WINDSURF_FILE:Windsurf" \
    "$KILOCODE_FILE:Kilo Code" \
    "$AUGGIE_FILE:Auggie CLI" \
    "$ROO_FILE:Roo Code" \
    "$CODEBUDDY_FILE:CodeBuddy CLI" \
    "$QODER_FILE:Qoder CLI" \
    "$SHAI_FILE:SHAI" \
    "$AGY_FILE:Antigravity" \
    "$BOB_FILE:IBM Bob"
  do
    local file="${entry%%:*}"
    local name="${entry#*:}"
    if [ -f "$file" ]; then
      update_agent_file "$file" "$name" || ok=false
      found=true
    fi
  done

  if [ "$found" = false ]; then
    info "No existing agent files found, creating default Claude file..."
    update_agent_file "$CLAUDE_FILE" "Claude Code" || ok=false
  fi
  [ "$ok" = true ]
}

print_summary() {
  echo ""
  info "Summary of changes:"
  [ -n "$NEW_LANG" ] && echo "  - Added language: $NEW_LANG"
  [ -n "$NEW_FRAMEWORK" ] && echo "  - Added framework: $NEW_FRAMEWORK"
  [ -n "$NEW_DB" ] && [ "$NEW_DB" != "N/A" ] && echo "  - Added database: $NEW_DB"
  echo ""
  info "Usage: ./update-agent-context.sh [claude|gemini|copilot|cursor-agent|qwen|opencode|codex|windsurf|kilocode|auggie|roo|codebuddy|amp|shai|q|agy|bob|qodercli|generic]"
}

# --- Main ---
validate_environment
info "=== Updating agent context files for feature $CURRENT_BRANCH ==="
parse_plan_data "$NEW_PLAN" || { err_msg "Failed to parse plan data"; exit 1; }

agent_ok=true
if [ -n "$AGENT_TYPE" ]; then
  info "Updating specific agent: $AGENT_TYPE"
  update_specific_agent "$AGENT_TYPE" || agent_ok=false
else
  info "No agent specified, updating all existing agent files..."
  update_all_existing_agents || agent_ok=false
fi

print_summary

if [ "$agent_ok" = true ]; then
  success "Agent context update completed successfully"
  exit 0
else
  err_msg "Agent context update completed with errors"
  exit 1
fi
