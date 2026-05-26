#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Deploy the fake-engine Function App to Azure.
#
# Creates (or reuses) a Linux Consumption Function App that consumes the
# `engine-runs` Service Bus queue with the same contract as the real engine,
# writes synthetic output.json artifacts to the platform's batch-results
# container, and emits RunResultMessage on `engine-results`. Zero LLM cost.
#
# Required environment (export or pass on the command line):
#   AZ_SUBSCRIPTION_ID    Azure subscription id
#   RG_NAME               Resource group to deploy the Function App into
#   LOCATION              e.g. eastus2
#   STORAGE_ACCOUNT       Storage account for FA runtime + artifacts (same
#                          account used by the platform's batch-results)
#   SB_NAMESPACE          Service Bus FQDN, e.g. <namespace>.servicebus.windows.net
#   APPINSIGHTS_CONN      Application Insights connection string (optional)
#
# Optional:
#   FAKE_FA_NAME          Default: fa-fake-engine-<random>
#   FAKE_PLAN_NAME        Default: <FAKE_FA_NAME>-plan
#   ARTIFACT_CONTAINER    Default: batch-results
#   SB_RUNS_QUEUE         Default: engine-runs
#   SB_RESULTS_QUEUE      Default: engine-results
#   FAKE_LATENCY_MS_MIN   Default: 50
#   FAKE_LATENCY_MS_MAX   Default: 250
#   FAKE_FAILURE_RATE     Default: 0.0
#   FAKE_TRANSIENT_RATE   Default: 0.0
#   FAKE_SCORE_MIN        Default: 5.5
#   FAKE_SCORE_MAX        Default: 9.5
#   FAKE_MUST_HAVE_PASS_RATE Default: 0.85
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# MSYS path-conversion mangles ARM resource ids on Git Bash; disable it.
export MSYS_NO_PATHCONV=1

# ── Required ────────────────────────────────────────────────────────────────
: "${AZ_SUBSCRIPTION_ID:?AZ_SUBSCRIPTION_ID is required}"
: "${RG_NAME:?RG_NAME is required}"
: "${LOCATION:?LOCATION is required (e.g. eastus2)}"
: "${STORAGE_ACCOUNT:?STORAGE_ACCOUNT is required}"
: "${SB_NAMESPACE:?SB_NAMESPACE is required (FQDN, e.g. ns.servicebus.windows.net)}"

# ── Defaults ────────────────────────────────────────────────────────────────
FAKE_FA_NAME="${FAKE_FA_NAME:-fa-fake-engine-$RANDOM}"
FAKE_PLAN_NAME="${FAKE_PLAN_NAME:-${FAKE_FA_NAME}-plan}"
ARTIFACT_CONTAINER="${ARTIFACT_CONTAINER:-batch-results}"
SB_RUNS_QUEUE="${SB_RUNS_QUEUE:-engine-runs}"
SB_RESULTS_QUEUE="${SB_RESULTS_QUEUE:-engine-results}"
APPINSIGHTS_CONN="${APPINSIGHTS_CONN:-}"

FAKE_LATENCY_MS_MIN="${FAKE_LATENCY_MS_MIN:-50}"
FAKE_LATENCY_MS_MAX="${FAKE_LATENCY_MS_MAX:-250}"
FAKE_FAILURE_RATE="${FAKE_FAILURE_RATE:-0.0}"
FAKE_TRANSIENT_RATE="${FAKE_TRANSIENT_RATE:-0.0}"
FAKE_SCORE_MIN="${FAKE_SCORE_MIN:-5.5}"
FAKE_SCORE_MAX="${FAKE_SCORE_MAX:-9.5}"
FAKE_MUST_HAVE_PASS_RATE="${FAKE_MUST_HAVE_PASS_RATE:-0.85}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/tools/fake-engine"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Fake-engine deploy"
echo "═══════════════════════════════════════════════════════════"
echo "  Subscription      : $AZ_SUBSCRIPTION_ID"
echo "  Resource group    : $RG_NAME"
echo "  Function App      : $FAKE_FA_NAME"
echo "  Plan              : $FAKE_PLAN_NAME (Consumption)"
echo "  Storage           : $STORAGE_ACCOUNT"
echo "  SB namespace      : $SB_NAMESPACE"
echo "  Runs queue        : $SB_RUNS_QUEUE"
echo "  Results queue     : $SB_RESULTS_QUEUE"
echo "  Artifact container: $ARTIFACT_CONTAINER"
echo ""

az account set --subscription "$AZ_SUBSCRIPTION_ID"

# ── 1) Resource group (idempotent) ──────────────────────────────────────────
if ! az group show -n "$RG_NAME" -o none 2>/dev/null; then
  echo "[1/7] Creating resource group $RG_NAME in $LOCATION..."
  az group create -n "$RG_NAME" -l "$LOCATION" -o none
else
  echo "[1/7] Resource group $RG_NAME exists."
fi

# ── 2) Ensure artifact container exists ─────────────────────────────────────
echo "[2/7] Ensuring blob container '$ARTIFACT_CONTAINER' exists on $STORAGE_ACCOUNT..."
az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$ARTIFACT_CONTAINER" \
  --auth-mode login \
  -o none

# ── 3) Ensure SB queues exist (idempotent) ──────────────────────────────────
SB_NS_SHORT="${SB_NAMESPACE%%.*}"
SB_NS_RG="$(az servicebus namespace list --query "[?name=='${SB_NS_SHORT}'].resourceGroup | [0]" -o tsv | tr -d '\r')"
if [[ -z "$SB_NS_RG" ]]; then
  echo "ERROR: could not locate Service Bus namespace '$SB_NS_SHORT' in subscription." >&2
  exit 1
fi
for q in "$SB_RUNS_QUEUE" "$SB_RESULTS_QUEUE"; do
  if ! az servicebus queue show -g "$SB_NS_RG" --namespace-name "$SB_NS_SHORT" -n "$q" -o none 2>/dev/null; then
    echo "[3/7] Creating SB queue $q ..."
    az servicebus queue create \
      -g "$SB_NS_RG" --namespace-name "$SB_NS_SHORT" -n "$q" \
      --max-delivery-count 10 \
      --enable-dead-lettering-on-message-expiration true \
      -o none
  else
    echo "[3/7] SB queue $q exists."
  fi
done

# ── 4) Function App + plan ──────────────────────────────────────────────────
if ! az functionapp show -g "$RG_NAME" -n "$FAKE_FA_NAME" -o none 2>/dev/null; then
  echo "[4/7] Creating Function App $FAKE_FA_NAME (Linux/Python 3.11, Consumption)..."
  az functionapp create \
    -g "$RG_NAME" \
    -n "$FAKE_FA_NAME" \
    --storage-account "$STORAGE_ACCOUNT" \
    --consumption-plan-location "$LOCATION" \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --os-type Linux \
    --assign-identity '[system]' \
    -o none
else
  echo "[4/7] Function App $FAKE_FA_NAME exists."
fi

# ── 5) App settings ─────────────────────────────────────────────────────────
echo "[5/7] Writing app settings..."
SETTINGS=(
  "FUNCTIONS_WORKER_RUNTIME=python"
  "AzureWebJobsFeatureFlags=EnableWorkerIndexing"
  "SbConnection__fullyQualifiedNamespace=${SB_NAMESPACE}"
  "SB_NAMESPACE=${SB_NAMESPACE}"
  "SB_RUNS_QUEUE=${SB_RUNS_QUEUE}"
  "SB_RESULTS_QUEUE=${SB_RESULTS_QUEUE}"
  "BLOB_ACCOUNT=${STORAGE_ACCOUNT}"
  "FAKE_ARTIFACT_CONTAINER=${ARTIFACT_CONTAINER}"
  "FAKE_LATENCY_MS_MIN=${FAKE_LATENCY_MS_MIN}"
  "FAKE_LATENCY_MS_MAX=${FAKE_LATENCY_MS_MAX}"
  "FAKE_FAILURE_RATE=${FAKE_FAILURE_RATE}"
  "FAKE_TRANSIENT_RATE=${FAKE_TRANSIENT_RATE}"
  "FAKE_SCORE_MIN=${FAKE_SCORE_MIN}"
  "FAKE_SCORE_MAX=${FAKE_SCORE_MAX}"
  "FAKE_MUST_HAVE_PASS_RATE=${FAKE_MUST_HAVE_PASS_RATE}"
)
if [[ -n "$APPINSIGHTS_CONN" ]]; then
  SETTINGS+=("APPLICATIONINSIGHTS_CONNECTION_STRING=${APPINSIGHTS_CONN}")
fi
az functionapp config appsettings set \
  -g "$RG_NAME" -n "$FAKE_FA_NAME" \
  --settings "${SETTINGS[@]}" \
  -o none

# ── 6) Role assignments for the Function App's system MI ────────────────────
echo "[6/7] Assigning roles to system-assigned identity..."
MI_PRINCIPAL="$(az functionapp identity show -g "$RG_NAME" -n "$FAKE_FA_NAME" --query principalId -o tsv | tr -d '\r')"
if [[ -z "$MI_PRINCIPAL" ]]; then
  echo "ERROR: could not read managed identity principalId for $FAKE_FA_NAME" >&2
  exit 1
fi

SB_NS_ID="$(az servicebus namespace show -g "$SB_NS_RG" -n "$SB_NS_SHORT" --query id -o tsv | tr -d '\r')"
STG_ID="$(az storage account show -n "$STORAGE_ACCOUNT" --query id -o tsv | tr -d '\r')"

# Receiver on engine-runs, Sender on engine-results (least privilege).
RUNS_Q_ID="${SB_NS_ID}/queues/${SB_RUNS_QUEUE}"
RESULTS_Q_ID="${SB_NS_ID}/queues/${SB_RESULTS_QUEUE}"

assign_role() {
  local role="$1" scope="$2"
  if ! az role assignment list --assignee "$MI_PRINCIPAL" --scope "$scope" --role "$role" \
       --query "[0].id" -o tsv 2>/dev/null | tr -d '\r' | grep -q .; then
    echo "  + $role on ${scope##*/}"
    az role assignment create --assignee-object-id "$MI_PRINCIPAL" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$scope" -o none
  else
    echo "  = $role on ${scope##*/} (exists)"
  fi
}

assign_role "Azure Service Bus Data Receiver" "$RUNS_Q_ID"
assign_role "Azure Service Bus Data Sender"   "$RESULTS_Q_ID"
assign_role "Storage Blob Data Contributor"   "$STG_ID"

# ── 7) Publish the function code ────────────────────────────────────────────
echo "[7/7] Publishing code from $SRC_DIR ..."
pushd "$SRC_DIR" >/dev/null
func azure functionapp publish "$FAKE_FA_NAME" --python --build remote
popd >/dev/null

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Fake-engine deploy complete."
echo "  Function App : $FAKE_FA_NAME"
echo "  Listens on   : $SB_NAMESPACE / $SB_RUNS_QUEUE"
echo "  Emits to     : $SB_NAMESPACE / $SB_RESULTS_QUEUE"
echo "  Writes to    : $STORAGE_ACCOUNT / $ARTIFACT_CONTAINER"
echo "═══════════════════════════════════════════════════════════"
