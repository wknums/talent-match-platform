#!/usr/bin/env bash
# ── build-api-image.sh ────────────────────────────────────────────────────────
# Build and push the API container image to ACR via `az acr build` (server-side,
# no local Docker required). Idempotent and CI-friendly.
#
# Usage:
#   ./infra/scripts/build-api-image.sh .env_qa
#   IMAGE_TAG=git-sha ./infra/scripts/build-api-image.sh .env_qa
#
# Required env vars in the .env file:
#   AZ_ACR_NAME           — ACR resource name (e.g. acrawra082afe6)
#   TF_CONTAINER_IMAGE    — Full image ref (registry/repo:tag); tag is overridable
#
# Optional overrides (env or .env):
#   IMAGE_TAG             — Override the tag portion (default: from TF_CONTAINER_IMAGE)
#   DOCKERFILE            — Path to Dockerfile (default: ./Dockerfile)
#   BUILD_CONTEXT         — Build context dir   (default: .)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_FILE="${1:?Usage: build-api-image.sh <env-file>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=lib_envparse.sh
source "$SCRIPT_DIR/lib_envparse.sh"
parse_env_file "$REPO_ROOT/$ENV_FILE"

ACR_NAME="$(get_env AZ_ACR_NAME)"
FULL_IMAGE="$(get_env TF_CONTAINER_IMAGE)"
[[ -z "$ACR_NAME" ]] && { echo "ERROR: AZ_ACR_NAME missing in $ENV_FILE" >&2; exit 1; }
[[ -z "$FULL_IMAGE" ]] && { echo "ERROR: TF_CONTAINER_IMAGE missing in $ENV_FILE" >&2; exit 1; }

# Strip registry host → "repo:tag"
REPO_TAG="${FULL_IMAGE#*/}"
REPO="${REPO_TAG%:*}"
DEFAULT_TAG="${REPO_TAG##*:}"
TAG="${IMAGE_TAG:-$DEFAULT_TAG}"
IMAGE="${REPO}:${TAG}"

DOCKERFILE="${DOCKERFILE:-Dockerfile}"
BUILD_CONTEXT="${BUILD_CONTEXT:-.}"

echo "▸ Building image '${IMAGE}' in ACR '${ACR_NAME}'"
cd "$REPO_ROOT"
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE" \
  --file "$DOCKERFILE" \
  "$BUILD_CONTEXT"

echo "✓ Pushed ${ACR_NAME}.azurecr.io/${IMAGE}"
