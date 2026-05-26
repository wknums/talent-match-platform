#!/usr/bin/env bash
# ── deploy.sh ─────────────────────────────────────────────────────────────────
# Reads an .env file, exports TF_VAR_* reuse variables, and runs terraform.
#
# Usage:
#   ./infra/scripts/deploy.sh .env_local dev plan
#   ./infra/scripts/deploy.sh .env_qa    test apply
#   ./infra/scripts/deploy.sh .env_prod  prod apply --auto-approve
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_FILE="${1:?Usage: deploy.sh <env-file> <tf-env> <action> [--auto-approve]}"
TF_ENV="${2:?Usage: deploy.sh <env-file> <tf-env> <action> [--auto-approve]}"
ACTION="${3:-plan}"
AUTO_APPROVE="${4:-}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE_PATH="$REPO_ROOT/$ENV_FILE"
TF_DIR="$REPO_ROOT/infra/terraform/envs/$TF_ENV"

if [[ ! -f "$ENV_FILE_PATH" ]]; then
  echo "ERROR: Env file not found: $ENV_FILE_PATH" >&2
  exit 1
fi

if [[ ! -d "$TF_DIR" ]]; then
  echo "ERROR: Terraform env directory not found: $TF_DIR" >&2
  exit 1
fi

# ── Regenerate terraform.tfvars from the env file (single source of truth) ────
if [[ -x "$REPO_ROOT/infra/scripts/generate-tfvars.sh" ]]; then
  "$REPO_ROOT/infra/scripts/generate-tfvars.sh" "$ENV_FILE" "$TF_ENV"
fi

# ── Parse .env file ───────────────────────────────────────────────────────────
declare -A ENV_VARS
while IFS='=' read -r key value; do
  # Skip blanks and comments BEFORE any quote-sensitive trimming.
  [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
  key="${key//[[:space:]]/}"
  # Only accept valid shell-style identifiers.
  [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && continue
  value="${value%$'\r'}"
  value="${value%%#*}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  ENV_VARS["$key"]="$value"
done < "$ENV_FILE_PATH"

get_env() { echo "${ENV_VARS[$1]:-$2}"; }
to_bool() { [[ "${1^^}" == "TRUE" ]] && echo "true" || echo "false"; }

# ── Map .env → TF_VAR_* ──────────────────────────────────────────────────────

# Reuse flags
export TF_VAR_reuse_storage=$(to_bool "$(get_env AZ_STORAGE_REUSE FALSE)")
export TF_VAR_reuse_appinsights=$(to_bool "$(get_env AZ_APPINSIGHTS_REUSE FALSE)")
export TF_VAR_reuse_service_bus=$(to_bool "$(get_env AZ_SERVICE_BUS_REUSE FALSE)")
export TF_VAR_reuse_key_vault=$(to_bool "$(get_env AZ_KEY_VAULT_REUSE FALSE)")
export TF_VAR_reuse_apim=$(to_bool "$(get_env AZ_APIM_REUSE FALSE)")
export TF_VAR_reuse_loganalytics=$(to_bool "$(get_env AZ_LOGANALYTICS_REUSE FALSE)")
export TF_VAR_reuse_identities=$(to_bool "$(get_env AZ_IDENTITIES_REUSE FALSE)")
export TF_VAR_reuse_core_rg=$(to_bool "$(get_env AZ_CORE_RG_REUSE FALSE)")
export TF_VAR_existing_core_rg_name="$(get_env AZ_CORE_RG_NAME '')"

# Existing resource details
export TF_VAR_existing_storage_name="$(get_env AZ_STORAGE_NAME '')"
export TF_VAR_existing_storage_rg="$(get_env AZ_STORAGE_RG '')"

export TF_VAR_existing_appinsights_name="$(get_env AZ_APPINSIGHTS_NAME '')"
export TF_VAR_existing_appinsights_rg="$(get_env AZ_APPINSIGHTS_RG '')"

export TF_VAR_existing_service_bus_name="$(get_env AZ_SERVICE_BUS_NAME '')"
export TF_VAR_existing_service_bus_rg="$(get_env AZ_SERVICE_BUS_RG '')"

export TF_VAR_existing_key_vault_name="$(get_env AZ_KEY_VAULT_NAME '')"
export TF_VAR_existing_key_vault_rg="$(get_env AZ_KEY_VAULT_RG '')"

export TF_VAR_existing_apim_name="$(get_env AZ_APIM_NAME '')"
export TF_VAR_existing_apim_rg="$(get_env AZ_APIM_RG '')"

export TF_VAR_existing_loganalytics_name="$(get_env AZ_LOGANALYTICS_NAME '')"
export TF_VAR_existing_loganalytics_rg="$(get_env AZ_LOGANALYTICS_RG '')"

export TF_VAR_existing_identities_api_name="$(get_env AZ_IDENTITIES_API_NAME '')"
export TF_VAR_existing_identities_func_name="$(get_env AZ_IDENTITIES_FUNC_NAME '')"
export TF_VAR_existing_identities_rg="$(get_env AZ_IDENTITIES_RG '')"

# Feature toggles
export TF_VAR_enable_apim=$(to_bool "$(get_env AZ_APIM_ENABLED FALSE)")
export TF_VAR_enable_acr_pull=$(to_bool "$(get_env AZ_ACR_REUSE FALSE)")
export TF_VAR_existing_acr_name="$(get_env AZ_ACR_NAME '')"
export TF_VAR_existing_acr_rg="$(get_env AZ_ACR_RG '')"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  AWR Platform - Terraform Deploy"
echo "═══════════════════════════════════════════════════════════"
echo "  Env File : $ENV_FILE"
echo "  TF Env   : $TF_ENV"
echo "  Action   : $ACTION"
echo ""
echo "  Resource Reuse:"
for r in storage appinsights service_bus key_vault apim loganalytics identities; do
  var="TF_VAR_reuse_$r"
  val="${!var}"
  if [[ "$val" == "true" ]]; then
    printf "    [REUSE] %s\n" "$r"
  else
    printf "    [NEW]   %s\n" "$r"
  fi
done
echo ""

# ── Destroy safety gate ───────────────────────────────────────────────────────
if [[ "$ACTION" == "destroy" ]]; then
    echo ""
    echo -e "\033[0;31m╔═══════════════════════════════════════════════════════════╗\033[0m"
    echo -e "\033[0;31m║  DESTROY REQUESTED                                      ║\033[0m"
    echo -e "\033[0;31m╠═══════════════════════════════════════════════════════════╣\033[0m"
    echo -e "\033[0;31m║  For safety, consider using the dedicated script:        ║\033[0m"
    echo -e "\033[1;33m║  ./infra/scripts/deprovision.sh $ENV_FILE $TF_ENV        ║\033[0m"
    echo -e "\033[0;31m╚═══════════════════════════════════════════════════════════╝\033[0m"
    echo ""

    echo "  Proceeding with destroy via deploy script..."
    echo ""

    # Show abbreviated reuse protection status
    echo -e "\033[0;32m  PROTECTED (will NOT be destroyed):\033[0m"
    has_destroy_protected=false
    for r in storage appinsights service_bus key_vault apim loganalytics identities; do
        var="TF_VAR_reuse_$r"
        val="${!var}"
        if [[ "$val" == "true" ]]; then
            has_destroy_protected=true
            printf "\033[0;32m    [PROTECTED] %s\033[0m\n" "$r"
        fi
    done
    if ! $has_destroy_protected; then
        echo -e "\033[0;90m    (none)\033[0m"
    fi

    echo -e "\033[0;31m  WILL DESTROY:\033[0m"
    for r in storage appinsights service_bus key_vault apim loganalytics identities; do
        var="TF_VAR_reuse_$r"
        val="${!var}"
        if [[ "$val" != "true" ]]; then
            printf "\033[0;31m    [DESTROY]   %s\033[0m\n" "$r"
        fi
    done
    echo -e "\033[0;31m    [DESTROY]   resource_group (always managed)\033[0m"
    echo -e "\033[0;31m    [DESTROY]   networking (always managed)\033[0m"
    echo -e "\033[0;31m    [DESTROY]   app_host (always managed)\033[0m"
    echo -e "\033[0;31m    [DESTROY]   functions_host (always managed)\033[0m"
    echo ""

    if [[ "$AUTO_APPROVE" != "--auto-approve" ]]; then
        read -rp "  Type '$TF_ENV' to confirm destruction: " confirm
        if [[ "$confirm" != "$TF_ENV" ]]; then
            echo "  Aborted."
            exit 0
        fi
    fi
fi

# ── Run Terraform ─────────────────────────────────────────────────────────────
cd "$TF_DIR"

echo "Running terraform init..."
terraform init -input=false

TF_ARGS=("$ACTION")
if [[ -f "terraform.tfvars" ]]; then
  TF_ARGS+=("-var-file=terraform.tfvars")
fi

if [[ "$ACTION" == "apply" && "$AUTO_APPROVE" == "--auto-approve" ]]; then
  TF_ARGS+=("-auto-approve")
fi

if [[ "$ACTION" == "destroy" && "$AUTO_APPROVE" == "--auto-approve" ]]; then
  TF_ARGS+=("-auto-approve")
fi

echo "Running terraform ${TF_ARGS[*]}..."
terraform "${TF_ARGS[@]}"

echo ""
echo "Done."
