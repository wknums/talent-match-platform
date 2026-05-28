# QA Smoke Test Deployment Guide

**Environment:** QA (test)  
**Config:** `.env_qa` (provided)  
**Objective:** Validate contract alignment patches end-to-end with real queue-worker

---

## Prerequisites

✅ Azure CLI logged in (subscription: `00000000-0000-0000-0000-000000000000`)  
✅ Terraform state initialized for `infra/terraform/envs/test`  
✅ Both repos cloned locally:
  - `c:/code/awr-platform`
  - `c:/code/auto-assessment-assist`

---

## Phase 1: Deploy Platform (awr-platform)

### 1a. Copy QA config and generate Terraform vars

```bash
cd /c/code/awr-platform
cp .env_qa .env.current
./infra/scripts/generate-tfvars.sh .env.current test
```

Verify `infra/terraform/envs/test/terraform.tfvars` is populated.

### 1b. Deploy Functions + App Service

```bash
cd infra/terraform/envs/test
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan
```

**Outputs to note:**
- `func_app_name` — Functions host (orchestrator)
- `api_app_name` — FastAPI service
- Both will be deployed with managed identities

### 1c. Verify Functions deployment

```bash
az functionapp list -g rg-example-platform --query "[?contains(name,'awr-platform')].{name:name,state:state}" -o table
```

Expected: Functions app in `Running` state.

---

## Phase 2: Deploy Real Queue-Worker (auto-assessment-assist)

### 2a. Build and push Docker image to ACR

```bash
cd /c/code/auto-assessment-assist
az acr build --registry acrexample123 --image awr-queue-worker:qa-latest .
```

### 2b. Deploy to Container Apps or ACI

Option A: **Container Apps** (KEDA autoscaling on SB queue depth)
```bash
az containerapp create \
  --resource-group rg-example-platform \
  --name awr-queue-worker-qa \
  --image acrexample123.azurecr.io/awr-queue-worker:qa-latest \
  --environment ca-env-example \
  --cpu 0.5 --memory 1Gi \
  --env-vars \
    SB_NAMESPACE='sb-example.servicebus.windows.net' \
    SB_QUEUE='engine-runs' \
    SB_RESULTS_QUEUE='engine-results' \
    REPORT_MODE='servicebus' \
    BLOB_ACCOUNT_URL='https://stexampleqa.blob.core.windows.net' \
    BLOB_RESULTS_CONTAINER='batch-results' \
    BLOB_RESULTS_PREFIX='runs' \
    PER_REPLICA_CONCURRENCY='2' \
  --user-assigned id-example-http-service
```

Option B: **Local for faster iteration**
```bash
cd /c/code/auto-assessment-assist
export SB_NAMESPACE='sb-example.servicebus.windows.net'
export SB_QUEUE='engine-runs'
export SB_RESULTS_QUEUE='engine-results'
export REPORT_MODE='servicebus'
export BLOB_ACCOUNT_URL='https://stexampleqa.blob.core.windows.net'
export BLOB_RESULTS_CONTAINER='batch-results'
export BLOB_RESULTS_PREFIX='runs'
python -m wrappers.queue-worker.main
```

---

## Phase 3: Submit Smoke Batch

### Subscription Policy Note: Temporary Blob Public Network Access

This subscription enforces policy controls that can block public network access to the storage account used for CV staging.

For short-lived QA validation only, temporarily enable storage public network access, run the test, and then disable it again immediately.

Use Azure CLI:

```bash
az account set --subscription 00000000-0000-0000-0000-000000000000

# Verify current setting
az storage account show \
  --name stexampleqa \
  --resource-group rg-example-platform \
  --query publicNetworkAccess -o tsv

# Enable for short test window
az storage account update \
  --name stexampleqa \
  --resource-group rg-example-platform \
  --public-network-access Enabled

# Run staging + smoke validation steps

# Disable again after tests complete
az storage account update \
  --name stexampleqa \
  --resource-group rg-example-platform \
  --public-network-access Disabled

# Confirm disabled
az storage account show \
  --name stexampleqa \
  --resource-group rg-example-platform \
  --query publicNetworkAccess -o tsv
```

If policy denies the update operation, request a temporary policy exemption for the QA test window.

Important: for this environment, keeping storage public network access open only during blob upload can still cause orchestration start failures later in the run. Keep temporary access enabled for the full submit + poll QA window, then restore it.

### 3a. Stage a CV blob

```bash
cd /c/code/awr-platform
./scripts/stage-cv-with-temp-access.sh \
  --storage-account stexampleqa \
  --resource-group rg-example-platform \
  --subscription 00000000-0000-0000-0000-000000000000 \
  --container cv-uploads \
  --file ./tmp-smoke-cv.pdf
# Output: CV_BLOB_URI and CV_SHA256
```

### 3b. Submit batch to platform

```bash
BATCH_ID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PLATFORM_BASE="https://app-example-platform-test.azurewebsites.net"

curl -X POST "${PLATFORM_BASE}/assess/batch" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: ${BATCH_ID}" \
  -H "x-correlation-id: corr-qa-001" \
  -H "traceparent: 00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01" \
  -d '{
    "batchId": "'${BATCH_ID}'",
    "jobId": "job-qa-001",
    "promptVersionId": "pv-qa-001",
    "runCount": 1,
    "prompt": {
      "kind": "inline",
      "text": "Score this CV against the role criteria and return structured JSON output."
    },
    "cvs": [
      {
        "applicationId": "app-qa-001",
        "documentId": "doc-qa-001",
        "fileName": "cv-qa.pdf",
        "mimeType": "application/pdf",
        "blobUri": "https://stexampleqa.blob.core.windows.net/cv-uploads/loadtest/cv-xxxxxxxx.pdf",
        "sha256": "xxxxxxxx..."
      }
    ]
  }' | jq .
```

Expected response (202 Accepted):
```json
{
  "submissionId": "...",
  "status": "queued",
  "pollUrl": "/assess/batch/.../status",
  "estimatedCompletionSeconds": 60
}
```

### 3c. Poll status

```bash
SUBMISSION_ID="<from 3b response>"
while true; do
  curl -s "${PLATFORM_BASE}/assess/batch/${SUBMISSION_ID}/status" | jq .
  sleep 5
done
```

Expected progression:
- `status: queued` → `running` → `completed`
- Final response includes `result.cvs[].aggregated.finalScore`

### 3d. Preferred: run full QA harness with temporary storage access lifecycle

Use the orchestration validator with storage toggling so access remains open for the full test run and is automatically restored on exit:

```bash
./scripts/qa-orchestration-validate.sh \
  --env-file /dev/null \
  --base-url https://app-example-platform-test.azurewebsites.net \
  --payload-file tmp/qa-batch-payload.json \
  --timeout-seconds 240 \
  --poll-seconds 5 \
  --metrics-out tmp/qa-validation-metrics.json \
  --storage-account stexampleqa \
  --resource-group rg-example-platform \
  --subscription 00000000-0000-0000-0000-000000000000
```

---

## Phase 4: Validate Patches

### Check 1: Traceparent propagation ✓
```bash
# In queue-worker logs, look for:
# "Processing run_id=... correlation_id=... traceparent=00-..."
# In Functions result-intake logs, look for:
# "Traceparent captured: 00-...; linking span to dispatch"
```

### Check 2: Artifact naming ✓
```bash
# In queue-worker logs, look for:
# "Artifacts uploaded: [{name: 'output.json', blob_uri: '...'}]"
# In Functions aggregation logs, look for:
# "Downloaded artifact output.json; parsed score=X.X"
```

### Check 3: Status preservation ✓
```bash
# Submit same batch (same batchId) twice:
BATCH_ID="same-id-as-before"
# First: runs engine, returns Succeeded, uploads marker
# Second: detects duplicate, loads marker, replays original status
# Both returns should have identical status/duration
```

### Duplicate Replay Operator Workflow (Authoritative Marker Validation)

1. Capture the original `runId` from terminal status payload:

```bash
curl -s "${PLATFORM_BASE}/assess/batch/${SUBMISSION_ID}/status" | jq -r '.result.cvs[].runs[].runId'
```

2. Replay one duplicate completion callback for that `runId` using the same correlation metadata.
3. Poll status again and verify:
  - no additional run entry appears for the same `runId`
  - aggregate result values stay unchanged
  - handler response is idempotent (accepted/no-op)
4. Inspect blob marker `result-delivery/{runId}.json` and verify a single authoritative marker is present.

### Check 4: Result completeness ✓
```bash
# Poll status until completed, then:
curl -s "${PLATFORM_BASE}/assess/batch/${SUBMISSION_ID}/status" | jq '.result.cvs[0]'
```

Expected:
```json
{
  "applicationId": "app-qa-001",
  "runs": [{"runIndex": 0, "status": "Succeeded", "artifacts": [...], "durationMs": ...}],
  "aggregated": {
    "finalScore": 6.5,
    "variance": 0.0,
    "finalDecision": "Approve|Reject",
    "mustHaveResult": true
  }
}
```

---

## Cleanup

```bash
# Stop queue-worker (if local)
# Ctrl+C in queue-worker terminal

# Delete Container Apps instance (if deployed)
az containerapp delete -g rg-example-platform -n awr-queue-worker-qa --yes

# Tear down platform (if needed)
cd infra/terraform/envs/test
terraform destroy
```

---

## Troubleshooting

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Batch stuck in `queued` | Queue-worker not consuming `engine-runs` | Check worker logs; verify Service Bus queue exists |
| `Failed to read output artifact` | Artifact named `cv-analysis.json` instead of `output.json` | Engine not patched; use fallback logic in aggregation |
| No `traceparent` in result-intake logs | Queue-worker not propagating | Verify `servicebus_io.py` sets `application_properties.traceparent` |
| Duplicate submit returns different status | Marker not stored or load failed | Check blob write permissions; verify `idempotency.py` marker path |
| `AzureWebJobsStorage` connection errors | Functions host trying to use Azurite | Set `AzureWebJobsStorage` to cloud storage account in app settings |

---

## Success Criteria

✅ Batch submitted and accepted (202 Accepted with submissionId)  
✅ Batch progresses to `running` within 10 seconds  
✅ Batch completes within 2 minutes (includes engine run time)  
✅ Final result includes per-application `aggregated.finalScore`  
✅ Traceparent captured in logs across all components  
✅ Duplicate submit replays original status without re-running engine  
✅ No errors in Functions or queue-worker logs related to artifacts/status
