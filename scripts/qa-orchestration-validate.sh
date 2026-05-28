#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/qa-orchestration-validate.sh [options]

Options:
  --env-file <path>        Environment file to source (default: .env_qa)
  --base-url <url>         Platform base URL (or use PLATFORM_BASE_URL env)
  --payload-file <path>    Batch submit payload JSON file
  --submission-id <id>     Existing submission id to validate (skip submit)
  --storage-account <name> Storage account to temporarily open for full test run
  --resource-group <name>  Resource group for --storage-account
  --subscription <id>      Subscription id/name used for storage update
  --http-timeout-seconds <n> Max time per HTTP call in seconds (default: 30)
  --timeout-seconds <n>    Poll timeout in seconds (default: 180)
  --poll-seconds <n>       Poll interval in seconds (default: 5)
  --metrics-out <path>     Output file for metrics JSON (default: PATCH_SUMMARY.md.json)
EOF
}

ENV_FILE=".env_qa"
BASE_URL="${PLATFORM_BASE_URL:-}"
PAYLOAD_FILE=""
SUBMISSION_ID=""
STORAGE_ACCOUNT=""
RESOURCE_GROUP=""
SUBSCRIPTION=""
HTTP_TIMEOUT_SECONDS=30
TIMEOUT_SECONDS=180
POLL_SECONDS=5
METRICS_OUT="PATCH_SUMMARY.md.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --payload-file)
      PAYLOAD_FILE="$2"
      shift 2
      ;;
    --submission-id)
      SUBMISSION_ID="$2"
      shift 2
      ;;
    --storage-account)
      STORAGE_ACCOUNT="$2"
      shift 2
      ;;
    --resource-group)
      RESOURCE_GROUP="$2"
      shift 2
      ;;
    --subscription)
      SUBSCRIPTION="$2"
      shift 2
      ;;
    --http-timeout-seconds)
      HTTP_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --poll-seconds)
      POLL_SECONDS="$2"
      shift 2
      ;;
    --metrics-out)
      METRICS_OUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
fi

if [[ -z "$BASE_URL" ]]; then
  BASE_URL="${PLATFORM_BASE:-}"
fi
if [[ -z "$BASE_URL" ]]; then
  echo "BASE URL is required (--base-url or PLATFORM_BASE_URL/PLATFORM_BASE env)." >&2
  exit 1
fi

if [[ -z "$SUBMISSION_ID" && -z "$PAYLOAD_FILE" ]]; then
  echo "Either --submission-id or --payload-file is required." >&2
  exit 1
fi

if ! [[ "$HTTP_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( HTTP_TIMEOUT_SECONDS <= 0 )); then
  echo "--http-timeout-seconds must be a positive integer." >&2
  exit 1
fi

if [[ -n "$STORAGE_ACCOUNT" && -z "$RESOURCE_GROUP" ]]; then
  echo "--resource-group is required when --storage-account is provided." >&2
  exit 1
fi

if [[ -z "$STORAGE_ACCOUNT" && -n "$RESOURCE_GROUP" ]]; then
  echo "--storage-account is required when --resource-group is provided." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 1
fi

status_file="$(mktemp)"
last_status_resp='{}'
ORIGINAL_PNA=""
ORIGINAL_DEFAULT_ACTION=""
STORAGE_TOGGLED="false"

cleanup() {
  set +e

  if [[ "$STORAGE_TOGGLED" == "true" && -n "$ORIGINAL_PNA" && -n "$ORIGINAL_DEFAULT_ACTION" ]]; then
    echo "Restoring storage network settings: publicNetworkAccess=$ORIGINAL_PNA, defaultAction=$ORIGINAL_DEFAULT_ACTION"
    az storage account update \
      --name "$STORAGE_ACCOUNT" \
      --resource-group "$RESOURCE_GROUP" \
      --public-network-access "$ORIGINAL_PNA" \
      --default-action "$ORIGINAL_DEFAULT_ACTION" \
      >/dev/null
  fi

  rm -f "$status_file"
}
trap cleanup EXIT

if [[ -n "$STORAGE_ACCOUNT" ]]; then
  if ! command -v az >/dev/null 2>&1; then
    echo "az is required when --storage-account is used." >&2
    exit 1
  fi

  if [[ -n "$SUBSCRIPTION" ]]; then
    az account set --subscription "$SUBSCRIPTION" >/dev/null
  fi

  ORIGINAL_PNA="$(az storage account show \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query publicNetworkAccess -o tsv | tr -d '\r')"

  ORIGINAL_DEFAULT_ACTION="$(az storage account show \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query networkRuleSet.defaultAction -o tsv | tr -d '\r')"

  if [[ -z "$ORIGINAL_PNA" || -z "$ORIGINAL_DEFAULT_ACTION" ]]; then
    echo "Could not read original storage network settings." >&2
    exit 1
  fi

  if [[ "$ORIGINAL_PNA" != "Enabled" || "$ORIGINAL_DEFAULT_ACTION" != "Allow" ]]; then
    echo "Temporarily enabling storage network access for full QA run: publicNetworkAccess=Enabled, defaultAction=Allow"
    az storage account update \
      --name "$STORAGE_ACCOUNT" \
      --resource-group "$RESOURCE_GROUP" \
      --public-network-access Enabled \
      --default-action Allow \
      >/dev/null
    STORAGE_TOGGLED="true"
  else
    echo "Storage network access already open for this QA run."
  fi
fi

if [[ -z "$SUBMISSION_ID" ]]; then
  batch_id="$(jq -r '.batchId' "$PAYLOAD_FILE")"
  if [[ -z "$batch_id" || "$batch_id" == "null" ]]; then
    echo "payload missing batchId" >&2
    exit 1
  fi

  submit_resp="$(curl -sS -X POST "$BASE_URL/assess/batch" \
    --connect-timeout 10 \
    --max-time "$HTTP_TIMEOUT_SECONDS" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $batch_id" \
    -H "x-correlation-id: qa-validate-$batch_id" \
    -H "traceparent: 00-$(printf '%032x' 1)-$(printf '%016x' 2)-01" \
    --data-binary "@$PAYLOAD_FILE")"

  SUBMISSION_ID="$(jq -r '.submissionId' <<<"$submit_resp")"
  if [[ -z "$SUBMISSION_ID" || "$SUBMISSION_ID" == "null" ]]; then
    echo "submit failed: $submit_resp" >&2
    exit 1
  fi

  echo "Submitted batch. submissionId=$SUBMISSION_ID"
fi

start_epoch="$(date +%s)"
final_status=""
terminal_found=0

while true; do
  now_epoch="$(date +%s)"
  elapsed=$((now_epoch - start_epoch))
  if (( elapsed > TIMEOUT_SECONDS )); then
    final_status="timeout"
    break
  fi

  status_resp="$(curl -sS \
    --connect-timeout 10 \
    --max-time "$HTTP_TIMEOUT_SECONDS" \
    "$BASE_URL/assess/batch/$SUBMISSION_ID/status")"
  last_status_resp="$status_resp"
  echo "$status_resp" > "$status_file"
  status_value="$(jq -r '.status // empty' <<<"$status_resp")"
  echo "poll elapsed=${elapsed}s status=${status_value:-unknown}"

  if [[ "$status_value" == "completed" || "$status_value" == "failed" || "$status_value" == "cancelled" ]]; then
    final_status="$status_value"
    terminal_found=1
    break
  fi

  sleep "$POLL_SECONDS"
done

elapsed_total=$(( $(date +%s) - start_epoch ))

if [[ ! -f "$status_file" ]]; then
  echo "$last_status_resp" > "$status_file"
fi

sc1_pass=false
if (( terminal_found == 1 )) && (( elapsed_total <= 120 )); then
  sc1_pass=true
fi

sc2_pass="$(jq -r '
  if .status != "completed" then false
  else
    ((.result.cvs // []) | length > 0)
    and ((.result.cvs // []) | all(
      .aggregated != null
      and .aggregated.finalScore != null
      and .aggregated.finalDecision != null
      and .aggregated.mustHaveResult != null
    ))
  end
' "$status_file")"

sc3_pass="$(jq -r '
  [(.result.cvs // [])[]?.runs[]?.runId] as $run_ids
  | if ($run_ids | length) == 0 then false
    else (($run_ids | unique | length) == ($run_ids | length))
    end
' "$status_file")"

sc4_pass="$(jq -r '
  [(.result.cvs // [])[]?.runs[]? | {correlationId, traceparent}] as $samples
  | if ($samples | length) == 0 then false
    else ($samples | all((.correlationId // "") != "" and (.traceparent // "") != ""))
    end
' "$status_file")"

unknown_id="unknown-$(date +%s)-$RANDOM"
unknown_http="$(curl -sS \
  --connect-timeout 10 \
  --max-time "$HTTP_TIMEOUT_SECONDS" \
  -o /dev/null -w '%{http_code}' "$BASE_URL/assess/batch/$unknown_id/status")"
sc5_pass=false
if [[ "$unknown_http" == "404" ]]; then
  sc5_pass=true
fi

overall=false
if [[ "$sc1_pass" == "true" && "$sc2_pass" == "true" && "$sc3_pass" == "true" && "$sc4_pass" == "true" && "$sc5_pass" == "true" ]]; then
  overall=true
fi

jq -n \
  --arg submissionId "$SUBMISSION_ID" \
  --arg finalStatus "$final_status" \
  --argjson elapsedSeconds "$elapsed_total" \
  --argjson sc1 "$sc1_pass" \
  --argjson sc2 "$sc2_pass" \
  --argjson sc3 "$sc3_pass" \
  --argjson sc4 "$sc4_pass" \
  --argjson sc5 "$sc5_pass" \
  --argjson overall "$overall" \
  '{
    submissionId: $submissionId,
    finalStatus: $finalStatus,
    elapsedSeconds: $elapsedSeconds,
    successCriteria: {
      SC001_terminal_within_120s: $sc1,
      SC002_completed_fields_present: $sc2,
      SC003_single_authoritative_run_record: $sc3,
      SC004_trace_metadata_continuity: $sc4,
      SC005_unknown_submission_not_found: $sc5
    },
    overallPass: $overall
  }' | tee "$METRICS_OUT"
