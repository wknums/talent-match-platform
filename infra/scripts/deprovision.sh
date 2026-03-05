#!/usr/bin/env bash
# ── deprovision.sh ────────────────────────────────────────────────────────────
# Safely deprovisions AWR Platform infrastructure, protecting reuse-flagged
# resources from destruction.
#
# Safety guarantees:
#   - Reuse-flagged resources (AZ_*_REUSE=TRUE) are NEVER destroyed.
#     They have count=0 in Terraform state, so nothing exists to destroy.
#   - A summary table shows [DESTROY] vs [PROTECTED] for every resource.
#   - Interactive confirmation is required unless --force is specified.
#   - The script refuses to run without an .env file.
#
# Usage:
#   ./infra/scripts/deprovision.sh .env_local dev                 # interactive
#   ./infra/scripts/deprovision.sh .env_qa    test --dry-run      # plan only
#   ./infra/scripts/deprovision.sh .env_prod  prod --force        # CI/CD
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# ── Args ──────────────────────────────────────────────────────────────────────
ENV_FILE="${1:?Usage: deprovision.sh <env-file> <tf-env> [--dry-run|--force]}"
TF_ENV="${2:?Usage: deprovision.sh <env-file> <tf-env> [--dry-run|--force]}"
FLAG="${3:-}"

DRY_RUN=false
FORCE=false
if [[ "$FLAG" == "--dry-run" ]]; then DRY_RUN=true; fi
if [[ "$FLAG" == "--force" ]];   then FORCE=true; fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE_PATH="$REPO_ROOT/$ENV_FILE"
TF_DIR="$REPO_ROOT/infra/terraform/envs/$TF_ENV"

# ── Validate paths ───────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE_PATH" ]]; then
    echo ""
    echo -e "${RED}ERROR: Env file not found: $ENV_FILE_PATH${NC}"
    echo ""
    echo -e "${RED}A .env file is REQUIRED for deprovisioning to ensure reuse-flagged${NC}"
    echo -e "${RED}resources are protected. Running terraform destroy without reuse${NC}"
    echo -e "${RED}flags would destroy ALL resources, including shared ones.${NC}"
    echo ""
    echo -e "${YELLOW}Available env files:${NC}"
    echo -e "${GRAY}  .env_local  ->  dev  (local development)${NC}"
    echo -e "${GRAY}  .env_qa     ->  test (QA / staging)${NC}"
    echo -e "${GRAY}  .env_prod   ->  prod (production)${NC}"
    echo ""
    exit 1
fi

if [[ ! -d "$TF_DIR" ]]; then
    echo -e "${RED}ERROR: Terraform env directory not found: $TF_DIR${NC}" >&2
    exit 1
fi

# ── Parse .env file ───────────────────────────────────────────────────────────
declare -A ENV_VARS
while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    [[ -z "$key" || "$key" == \#* ]] && continue
    ENV_VARS["$key"]="$value"
done < "$ENV_FILE_PATH"

get_env() { echo "${ENV_VARS[$1]:-${2:-}}"; }
to_bool() { [[ "${1^^}" == "TRUE" ]] && echo "true" || echo "false"; }

# ── Map .env → TF_VAR_* ──────────────────────────────────────────────────────

# Reuse flags
export TF_VAR_reuse_storage=$(to_bool "$(get_env AZ_STORAGE_REUSE FALSE)")
export TF_VAR_reuse_appinsights=$(to_bool "$(get_env AZ_APPINSIGHTS_REUSE FALSE)")
export TF_VAR_reuse_service_bus=$(to_bool "$(get_env AZ_SERVICE_BUS_REUSE FALSE)")
export TF_VAR_reuse_sql=$(to_bool "$(get_env AZ_SQL_REUSE FALSE)")
export TF_VAR_reuse_key_vault=$(to_bool "$(get_env AZ_KEY_VAULT_REUSE FALSE)")
export TF_VAR_reuse_apim=$(to_bool "$(get_env AZ_APIM_REUSE FALSE)")
export TF_VAR_reuse_loganalytics=$(to_bool "$(get_env AZ_LOGANALYTICS_REUSE FALSE)")
export TF_VAR_reuse_identities=$(to_bool "$(get_env AZ_IDENTITIES_REUSE FALSE)")

# Existing resource details
export TF_VAR_existing_storage_name="$(get_env AZ_STORAGE_NAME '')"
export TF_VAR_existing_storage_rg="$(get_env AZ_STORAGE_RG '')"

export TF_VAR_existing_appinsights_name="$(get_env AZ_APPINSIGHTS_NAME '')"
export TF_VAR_existing_appinsights_rg="$(get_env AZ_APPINSIGHTS_RG '')"

export TF_VAR_existing_service_bus_name="$(get_env AZ_SERVICE_BUS_NAME '')"
export TF_VAR_existing_service_bus_rg="$(get_env AZ_SERVICE_BUS_RG '')"

export TF_VAR_existing_sql_server_name="$(get_env AZ_SQL_SERVER_NAME '')"
export TF_VAR_existing_sql_db_name="$(get_env AZ_SQL_DB_NAME '')"
export TF_VAR_existing_sql_rg="$(get_env AZ_SQL_RG '')"

export TF_VAR_existing_key_vault_name="$(get_env AZ_KEY_VAULT_NAME '')"
export TF_VAR_existing_key_vault_rg="$(get_env AZ_KEY_VAULT_RG '')"

export TF_VAR_existing_apim_name="$(get_env AZ_APIM_NAME '')"
export TF_VAR_existing_apim_rg="$(get_env AZ_APIM_RG '')"

export TF_VAR_existing_loganalytics_name="$(get_env AZ_LOGANALYTICS_NAME '')"
export TF_VAR_existing_loganalytics_rg="$(get_env AZ_LOGANALYTICS_RG '')"

export TF_VAR_existing_identities_api_name="$(get_env AZ_IDENTITIES_API_NAME '')"
export TF_VAR_existing_identities_func_name="$(get_env AZ_IDENTITIES_FUNC_NAME '')"
export TF_VAR_existing_identities_rg="$(get_env AZ_IDENTITIES_RG '')"

# ── Build resource disposition ────────────────────────────────────────────────
# Reusable resources  (name, env_flag_prefix, tf_var_value)
declare -a RESOURCE_NAMES=("Storage Account" "Application Insights" "Service Bus" "SQL Server + DB" "Key Vault" "API Management" "Log Analytics" "Managed Identities")
declare -a RESOURCE_FLAGS=("AZ_STORAGE" "AZ_APPINSIGHTS" "AZ_SERVICE_BUS" "AZ_SQL" "AZ_KEY_VAULT" "AZ_APIM" "AZ_LOGANALYTICS" "AZ_IDENTITIES")
declare -a RESOURCE_TF_VALS=("$TF_VAR_reuse_storage" "$TF_VAR_reuse_appinsights" "$TF_VAR_reuse_service_bus" "$TF_VAR_reuse_sql" "$TF_VAR_reuse_key_vault" "$TF_VAR_reuse_apim" "$TF_VAR_reuse_loganalytics" "$TF_VAR_reuse_identities")

# Always-managed modules
declare -a ALWAYS_MANAGED=("Resource Group" "Networking (VNet)" "App Service (API)" "Functions Host")

destroy_count=0
protect_count=0

# ── Display summary ──────────────────────────────────────────────────────────
echo ""
echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}  AWR Platform - DEPROVISION${NC}"
echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${WHITE}  Env File : $ENV_FILE${NC}"
echo -e "${WHITE}  TF Env   : $TF_ENV${NC}"
if $DRY_RUN; then
    echo -e "${YELLOW}  Mode     : DRY RUN (plan only, no resources will be destroyed)${NC}"
else
    echo -e "${RED}  Mode     : LIVE DESTROY${NC}"
fi
echo ""

# Destruction section
echo -e "${RED}  ┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "${RED}  │  RESOURCES TO BE DESTROYED                             │${NC}"
echo -e "${RED}  └─────────────────────────────────────────────────────────┘${NC}"

for i in "${!RESOURCE_NAMES[@]}"; do
    if [[ "${RESOURCE_TF_VALS[$i]}" != "true" ]]; then
        echo -e "${RED}    [DESTROY]   ${RESOURCE_NAMES[$i]}${NC}"
        ((destroy_count++)) || true
    fi
done

for m in "${ALWAYS_MANAGED[@]}"; do
    echo -e "${RED}    [DESTROY]   $m  (always managed)${NC}"
    ((destroy_count++)) || true
done

echo ""

# Protection section
echo -e "${GREEN}  ┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}  │  PROTECTED RESOURCES (reuse-flagged, will NOT be       │${NC}"
echo -e "${GREEN}  │  touched by destroy)                                   │${NC}"
echo -e "${GREEN}  └─────────────────────────────────────────────────────────┘${NC}"

has_protected=false
for i in "${!RESOURCE_NAMES[@]}"; do
    if [[ "${RESOURCE_TF_VALS[$i]}" == "true" ]]; then
        has_protected=true
        flag_prefix="${RESOURCE_FLAGS[$i]}"
        ext_name="$(get_env "${flag_prefix}_NAME" '')"
        ext_rg="$(get_env "${flag_prefix}_RG" '')"
        detail=""
        if [[ -n "$ext_name" ]]; then
            detail=" -> $ext_name in $ext_rg"
        fi
        echo -e "${GREEN}    [PROTECTED] ${RESOURCE_NAMES[$i]}${detail}${NC}"
        ((protect_count++)) || true
    fi
done

if ! $has_protected; then
    echo -e "${GRAY}    (none — all optionally-reusable resources are managed)${NC}"
fi

echo ""
echo -e "${YELLOW}  Summary: ${destroy_count} resource(s) to DESTROY, ${protect_count} resource(s) PROTECTED${NC}"
echo ""

# ── Safety explanation ────────────────────────────────────────────────────────
if $has_protected; then
    echo -e "${GRAY}  How protection works:${NC}"
    echo -e "${GRAY}    Reuse-flagged modules have count=0 on all managed resources,${NC}"
    echo -e "${GRAY}    so nothing exists in Terraform state to destroy. The data${NC}"
    echo -e "${GRAY}    sources that reference the existing resources are read-only${NC}"
    echo -e "${GRAY}    and are never deleted by terraform destroy.${NC}"
    echo ""
fi

# ── Confirmation gate ─────────────────────────────────────────────────────────
if ! $DRY_RUN && ! $FORCE; then
    echo -e "${RED}  WARNING: This action is IRREVERSIBLE for the resources listed above.${NC}"
    echo ""
    read -rp "  Type the environment name '$TF_ENV' to confirm destruction: " confirmation
    if [[ "$confirmation" != "$TF_ENV" ]]; then
        echo ""
        echo -e "${YELLOW}  Confirmation failed. Aborting.${NC}"
        exit 0
    fi
    echo ""
fi

# ── Run Terraform ─────────────────────────────────────────────────────────────
cd "$TF_DIR"

echo -e "${CYAN}Running terraform init...${NC}"
terraform init -input=false

if $DRY_RUN; then
    TF_ARGS=("plan" "-destroy")
else
    TF_ARGS=("destroy")
fi

if [[ -f "terraform.tfvars" ]]; then
    TF_ARGS+=("-var-file=terraform.tfvars")
fi

if ! $DRY_RUN && $FORCE; then
    TF_ARGS+=("-auto-approve")
fi

echo -e "${CYAN}Running terraform ${TF_ARGS[*]}...${NC}"
terraform "${TF_ARGS[@]}"

echo ""
if $DRY_RUN; then
    echo -e "${YELLOW}Dry run complete. No resources were destroyed.${NC}"
else
    echo -e "${GREEN}Deprovisioning complete.${NC}"
    if $has_protected; then
        echo -e "${GREEN}${protect_count} reuse-flagged resource(s) were protected and remain intact.${NC}"
    fi
fi
