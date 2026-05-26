#!/usr/bin/env bash
# ── deploy-code.sh ────────────────────────────────────────────────────────────
# End-to-end application code deployment for an environment:
#   1. Build & push API container image to ACR  (build-api-image.sh)
#   2. Restart the API web app so it pulls the new image
#   3. Package and deploy Functions code        (deploy-functions.sh)
#
# Usage:
#   ./infra/scripts/deploy-code.sh .env_qa test
#   SKIP_API=1   ./infra/scripts/deploy-code.sh .env_qa test
#   SKIP_FUNCS=1 ./infra/scripts/deploy-code.sh .env_qa test
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_FILE="${1:?Usage: deploy-code.sh <env-file> <tf-env>}"
TF_ENV="${2:?Usage: deploy-code.sh <env-file> <tf-env>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=lib_envparse.sh
source "$SCRIPT_DIR/lib_envparse.sh"
parse_env_file "$REPO_ROOT/$ENV_FILE"

RG="$(get_env AZ_CORE_RG_NAME)"
PROJECT="$(get_env TF_PROJECT)"
ENVIRONMENT="$(get_env TF_ENVIRONMENT)"
API_APP_NAME="${API_APP_NAME:-app-${PROJECT}-${ENVIRONMENT}}"

if [[ "${SKIP_API:-0}" != "1" ]]; then
  echo "═══ API ═══"
  "$SCRIPT_DIR/build-api-image.sh" "$ENV_FILE"
  echo "▸ Restarting web app $API_APP_NAME so it pulls the new image"
  az webapp restart --resource-group "$RG" --name "$API_APP_NAME" >/dev/null
  echo "✓ API restart issued"
fi

if [[ "${SKIP_FUNCS:-0}" != "1" ]]; then
  echo "═══ Functions ═══"
  "$SCRIPT_DIR/deploy-functions.sh" "$ENV_FILE" "$TF_ENV"
fi

echo "═══ Done ═══"
