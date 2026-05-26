# Quickstart: 002 Platform-Mode Shift

This quickstart covers the current queue-worker platform mode implemented by
this repo. It assumes the client/backend owns durable business persistence and
the platform owns orchestration, progress tracking, result staging, and live
event projection when enabled.

## What You Will Run

- FastAPI public contract for `POST /assess/batch`, status, and cancel
- Azure Functions host for Durable orchestration, dispatch, and result intake
- Azure Storage for Durable state, run-index state, and completed batch results
- Service Bus queues for `engine-runs` and `engine-results`
- Optional Azure SignalR projection for live progress updates

## Prerequisites

- Python 3.11+
- Azure CLI with `az login`
- Azure Functions Core Tools v4
- Azurite for local `AzureWebJobsStorage` emulation, or a real storage account
- Access to a Service Bus namespace and blob storage account, or a deployed
  dev/test environment
- Git Bash on Windows

## 1. Clone and Install

```bash
git clone <repo-url> && cd awr-platform
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
pip install -e ".[dev]"
pip install -r requirements.txt
```

## 2. Configure Environment

Create a local environment file and set the current 002 platform-mode values.

```bash
cp .env.example .env
```

Minimum settings for local or dev validation:

- `FUNCTIONS_HOST_URL`
- `SB_NAMESPACE`
- `SB_RUNS_QUEUE`
- `SB_RESULTS_QUEUE`
- `ENGINE_REPORT_MODE`
- `BLOB_ACCOUNT`
- `BLOB_CONTAINER`
- `BLOB_RESULTS_CONTAINER`
- `AUTH_REQUIRED`
- `LIVE_PROGRESS_ENABLED`

Optional live projection settings:

- `SIGNALR_SERVICE_ENDPOINT` for managed identity publishing in Azure
- `SIGNALR_CONNECTION_STRING` only for local/dev scenarios without managed identity

Retention behavior:

- Completed handoff blobs in `batch-results` are short-lived staging artifacts.
- Terraform defaults to deleting them after 7 days when this repo provisions
  the storage account.

## 3. Start the Platform Locally

Use two terminals from the repo root.

```bash
# Terminal 1
source .venv/Scripts/activate
func start
```

```bash
# Terminal 2
source .venv/Scripts/activate
uvicorn api.main:app --reload --port 8000
```

## 4. Submit a Batch

The canonical batch identity is:

- `submissionId = batchId = Durable instance_id`

Each CV carries a stable `applicationId`, and each scoring attempt gets a
deterministic `runId` for `(batchId, applicationId, runIndex)`.

Example request:

```bash
curl -X POST http://localhost:8000/assess/batch \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 11111111-1111-1111-1111-111111111111" \
  -H "x-correlation-id: corr-local-001" \
  -H "traceparent: 00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01" \
  -d '{
    "batchId": "11111111-1111-1111-1111-111111111111",
    "jobId": "job-123",
    "promptVersionId": "pv-7",
    "runCount": 2,
    "prompt": {"kind": "inline", "text": "Score this CV."},
    "cvs": [
      {
        "applicationId": "app-001",
        "documentId": "doc-001",
        "fileName": "cv.pdf",
        "mimeType": "application/pdf",
        "blobUri": "https://<account>.blob.core.windows.net/cv-uploads/cv.pdf",
        "sha256": "<64-hex>"
      }
    ]
  }'
```

Expected response:

- `202 Accepted`
- `submissionId`
- `pollUrl`

## 5. Observe Progress

Polling remains the mandatory fallback even when live events are enabled.

```bash
curl http://localhost:8000/assess/batch/11111111-1111-1111-1111-111111111111/status
```

The status model should explain:

- batch status
- submission progress counters
- result summary when complete
- enough lineage context to identify which application and run produced which
  result or artifact

When live projection is enabled, Azure SignalR may push non-authoritative
progress events derived from Durable state and run-index state. Those events do
not replace status polling or persisted result documents.

## 6. Inspect Completed Results

The platform-owned completed handoff document lives at:

```text
batches/{batchId}/result.json
```

This document is the platform's durable completed-result handoff and should
preserve per-application lineage:

- `applicationId`
- per-run payloads
- artifact references
- aggregate rollup
- terminal errors when applicable

## 7. Trace a Single Application

To trace one application from submission through aggregation, use this order:

1. Start with `submissionId` or `batchId`.
2. Inspect the original request payload for `applicationId`, `documentId`, and
   `jobId`.
3. Recover the derived `runId`s for each `runIndex`.
4. Use run-index state to map a returned `runId` back to the owning
   `applicationId`.
5. Inspect `batches/{batchId}/result.json` for the completed per-application
   result block.
6. If live projection is enabled, correlate matching SignalR events using
   `submissionId`, `applicationId`, `runId`, `correlationId`, and
   `traceparent`.

For the full tracing workflow, see [docs/application-tracing.md](../../docs/application-tracing.md).

## 8. Run the Relevant Tests

```bash
python -m pytest tests/test_routes_assess.py -v
python -m pytest tests/test_dispatch_run.py -v
python -m pytest tests/test_result_intake.py -v
python -m pytest tests/test_progress_state.py -v
python -m pytest tests/test_traceability.py -v
python -m pytest tests/test_live_events.py -v
python -m pytest tests/test_aggregate.py -v
python -m pytest tests/test_auth.py -v
```

For the full test matrix and Terraform validation commands, see
[docs/testing.md](../../docs/testing.md).

## 9. Operator Checklist

- Confirm `submissionId = batchId = instance_id` in API, logs, and Durable.
- Confirm every returned `runId` maps back to the expected `applicationId`.
- Confirm result blobs remain readable after Durable history purge.
- Confirm SignalR events, when enabled, mirror platform state rather than
  inventing independent state.
- Confirm traces can be followed via `x-correlation-id` and `traceparent`
  across API, orchestrator, engine, result intake, and live projection.
