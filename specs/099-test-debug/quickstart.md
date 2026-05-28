# Quickstart: QA Orchestration Validation

## Goal

Run a production-like QA validation proving:

- End-to-end batch completion
- Final aggregation fields are populated
- Trace metadata continuity is preserved
- Duplicate completion replay is idempotent
- Unknown orchestration identifiers return not-found

## Prerequisites

- Access to QA API endpoint and Functions host
- Access to QA Service Bus and blob storage resources
- Operator permissions to inspect status and evidence artifacts
- Repository configured with QA environment settings

## Environment Loading

Use the repository QA environment file so endpoints and resource names are consistent:

```bash
cd /c/code/awr-platform
set -a
source .env_qa
set +a
```

Required variables for validation runs:

- `PLATFORM_BASE` or `PLATFORM_BASE_URL`
- `SB_NAMESPACE`, `SB_RESULTS_QUEUE`, `SB_QUEUE`
- `BLOB_ACCOUNT` and `BLOB_RESULTS_CONTAINER`

Optional override:

- `AUTH_REQUIRED=false` for non-AAD local validation paths

## Step 1: Prepare test input

- Stage a representative assessment batch with 3 to 10 valid candidate artifacts for submission.
- Prepare a deterministic batch payload containing:
  - batchId/submissionId
  - correlation metadata
  - candidate entries with required IDs and artifact metadata for each candidate

## Step 2: Submit batch

- Submit through the public batch endpoint.
- Capture submissionId and correlation metadata for later checks.

Expected result:

- Accepted submission response with submissionId.

## Step 3: Track status to terminal state

- Poll batch status until terminal state.

Expected result:

- Lifecycle transitions from queued to running to completed for successful flow.

## Step 4: Verify final aggregation output

- Read completed batch status payload and inspect per-candidate aggregation block.

Expected result:

- finalScore present
- finalDecision present
- mustHaveResult present

## Step 5: Verify traceability evidence

- Compare submission-time correlation metadata with persisted completion/delivery evidence.
- Confirm continuity for run and batch identifiers.

Expected result:

- correlation metadata preserved in final operational evidence.

## Step 6: Verify duplicate completion safety

- Replay a duplicate completion callback for an already completed run.
- Recheck status and delivery evidence.

Expected result:

- No duplicate authoritative final outcome.
- Existing final result remains stable.

## Step 7: Verify unknown orchestration behavior

- Query orchestration status with a random unknown instance identifier.

Expected result:

- Not-found response (not synthetic running).

## Step 8: Run Validation Harness With Metrics

```bash
./scripts/qa-orchestration-validate.sh \
  --env-file .env_qa \
  --base-url "$PLATFORM_BASE" \
  --payload-file ./tmp/qa-batch-payload.json \
  --metrics-out ./tmp/qa-validation-metrics.json
```

The harness emits pass/fail for SC-001 through SC-005 and writes a machine-readable metrics JSON document.

## Metrics Interpretation

- `SC001_terminal_within_120s=true`: at least one valid batch reached terminal state in <=120s.
- `SC002_completed_fields_present=true`: completed response includes `finalScore`, `finalDecision`, and `mustHaveResult` for each candidate.
- `SC003_single_authoritative_run_record=true`: no duplicate `runId` entries in final run evidence.
- `SC004_trace_metadata_continuity=true`: each sampled run in final evidence contains non-empty `correlationId` and `traceparent`.
- `SC005_unknown_submission_not_found=true`: unknown submission status endpoint returns HTTP 404.

## Exit Criteria

- All five success criteria in [spec.md](spec.md) are satisfied.
- No unhandled payload-shape errors observed during callback processing.