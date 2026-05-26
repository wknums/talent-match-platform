#!/usr/bin/env bash
# ── deploy-functions.sh ───────────────────────────────────────────────────────
# Package and deploy function code to an Azure Functions Flex Consumption app
# using OneDeploy (`az functionapp deployment source config-zip`).
#
# Usage:
#   ./infra/scripts/deploy-functions.sh .env_qa test
#
# Reads from .env file:
#   AZ_CORE_RG_NAME      — resource group of the Function App
#   TF_PROJECT           — used to derive default app name
#   TF_ENVIRONMENT       — used to derive default app name
# Optional override:
#   FUNCTION_APP_NAME    — explicit Function App name (else: func-${TF_PROJECT}-${TF_ENVIRONMENT})
#   ZIP_PATH             — pre-built zip (else: build via package-functions.sh)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_FILE="${1:?Usage: deploy-functions.sh <env-file> [tf-env]}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=lib_envparse.sh
source "$SCRIPT_DIR/lib_envparse.sh"
parse_env_file "$REPO_ROOT/$ENV_FILE"

RG="$(get_env AZ_CORE_RG_NAME)"
PROJECT="$(get_env TF_PROJECT)"
ENVIRONMENT="$(get_env TF_ENVIRONMENT)"
APP_NAME="${FUNCTION_APP_NAME:-func-${PROJECT}-${ENVIRONMENT}}"

[[ -z "$RG"      ]] && { echo "ERROR: AZ_CORE_RG_NAME missing"      >&2; exit 1; }
[[ -z "$PROJECT" || -z "$ENVIRONMENT" ]] && { echo "ERROR: TF_PROJECT / TF_ENVIRONMENT missing" >&2; exit 1; }

ZIP_PATH="${ZIP_PATH:-$REPO_ROOT/dist/functions.zip}"
if [[ ! -f "$ZIP_PATH" ]]; then
  echo "▸ Building deployment package"
  "$SCRIPT_DIR/package-functions.sh" "$ZIP_PATH"
fi

# Convert to native Windows path for az on Git Bash (MSYS mangles /c/... otherwise).
if command -v cygpath >/dev/null 2>&1; then
  ZIP_ARG="$(cygpath -w "$ZIP_PATH")"
else
  ZIP_ARG="$ZIP_PATH"
fi

echo "▸ Deploying $ZIP_PATH → $APP_NAME (rg=$RG)"
az functionapp deployment source config-zip \
  --resource-group "$RG" \
  --name "$APP_NAME" \
  --src "$ZIP_ARG" \
  --build-remote true

# Print host URL + status
HOST="$(az functionapp show -g "$RG" -n "$APP_NAME" --query defaultHostName -o tsv | tr -d '\r')"
echo "✓ Deployed. Host: https://$HOST"
