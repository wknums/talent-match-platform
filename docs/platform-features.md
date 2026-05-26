# Platform Features and Usage

This guide documents the features implemented by the current 002 platform-mode
architecture and how to use them locally and in Azure.

## Core Features

| Capability | What it does | Primary implementation |
| --- | --- | --- |
| Batch submission | Accepts `POST /assess/batch` and starts or reuses a Durable orchestration keyed by `batchId` | `api/routes_assess.py`, `api/durable_client.py` |
| Idempotent submit | Enforces `Idempotency-Key == batchId` and reuses the same orchestration for repeats | `api/routes_assess.py` |
| Queue-worker dispatch | Sends one `RunMessage` per `(applicationId, runIndex)` to `engine-runs` | `orchestrator/functions/fanout/__init__.py` |
| Result intake | Accepts results from Service Bus or HTTP `PATCH /runs/{runId}` and raises `run-{runId}` Durable events | `orchestrator/functions/result_intake/__init__.py` |
| Progress state | Maintains batch, application, and run progress in Durable custom status | `orchestrator/functions/fanout/__init__.py` |
| Final result staging | Writes `batches/{batchId}/result.json` to blob storage for client pickup | `orchestrator/functions/fanout/__init__.py` |
| Lineage recovery | Resolves `runId -> batchId/applicationId/runIndex` using `run-index/{runId}.json` | `orchestrator/functions/fanout/__init__.py`, `orchestrator/functions/result_intake/__init__.py` |
| Duplicate result protection | Uses `result-delivery/{runId}.json` marker blobs to suppress duplicate completion | `orchestrator/functions/result_intake/__init__.py` |
| Live progress projection | Emits versioned progress events to Azure SignalR when enabled | `runtime/events.py` |
| Polling fallback | Treats `GET /assess/batch/{submissionId}/status` and result blobs as canonical recovery surfaces | `api/routes_assess.py`, `docs/application-tracing.md` |
| Entra JWT validation | Validates JWTs against issuer/audience and JWKS when auth is required | `api/auth.py` |
| Terraform IaC | Provisions Functions, Service Bus, storage retention, and optional SignalR | `infra/terraform/**` |

## Public Usage Surface

### Submit a batch

- Endpoint: `POST /assess/batch`
- Required header: `Idempotency-Key`
- Required body fields: `batchId`, `jobId`, `promptVersionId`, `runCount`, `prompt`, `cvs[]`
- Optional tracing headers: `x-correlation-id`, `traceparent`

Outcome:

- `202 Accepted` with `submissionId` and `pollUrl`
- Repeated submit with the same `batchId` reuses the same orchestration
- Mismatched `Idempotency-Key` returns `400`

### Poll status

- Endpoint: `GET /assess/batch/{submissionId}/status`

Use this endpoint for:

- current batch status
- progress counters
- application and run lineage in status payloads
- canonical recovery when live projection is unavailable

### Cancel a batch

- Endpoint: `POST /assess/batch/{submissionId}/cancel`

Expected outcomes:

- `202` when cancellation is requested
- `200` when already cancelled
- `409` when already completed

## Runtime Configuration

### Required for platform execution

- `FUNCTIONS_HOST_URL`
- `SB_NAMESPACE`
- `SB_RUNS_QUEUE`
- `SB_RESULTS_QUEUE`
- `ENGINE_REPORT_MODE`
- `BLOB_ACCOUNT`
- `BLOB_CONTAINER`
- `BLOB_RESULTS_CONTAINER`

### Authentication and tracing

- `AUTH_REQUIRED`
- `AAD_ISSUER`
- `AAD_AUDIENCE`
- `APPLICATIONINSIGHTS_CONNECTION_STRING`
- `OTEL_EXPORTER_OTLP_ENDPOINT`

### Live progress projection

- `LIVE_PROGRESS_ENABLED`
- `SIGNALR_SERVICE_ENDPOINT`
- `SIGNALR_CONNECTION_STRING`
- `SIGNALR_HUB_NAME`
- `LIVE_PROGRESS_TARGET`
- `LIVE_PROGRESS_GROUP_PREFIX`

SignalR usage rules:

- In Azure, prefer `SIGNALR_SERVICE_ENDPOINT` and managed identity.
- For local/dev without managed identity, use `SIGNALR_CONNECTION_STRING`.
- If neither is configured, or publish fails, the platform does not block the
  workflow; clients fall back to polling.

## Azure Usage

### Terraform toggles

The environment compositions in `infra/terraform/envs/{dev,test,prod}` expose:

- `enable_artifact_storage`
- `batch_results_retention_days`
- `enable_live_progress`
- `signalr_sku`
- `signalr_capacity`
- `signalr_hub_name`
- `reuse_signalr`

### Managed identity expectations

- Functions storage backend uses identity-based `AzureWebJobsStorage__*` settings.
- Service Bus trigger/sender uses identity-based `SbConnection__*` settings.
- SignalR publish uses the Functions managed identity with `SignalR REST API Owner`.
- Blob access uses `DefaultAzureCredential`; no SAS tokens are required.

### Retention behavior

- The `batch-results` container is created by the storage module.
- When the storage account is created by this repo, a management policy deletes
  `batch-results` blobs after 7 days by default.
- Adjust `batch_results_retention_days` per environment if a longer handoff
  window is required.

## Operational Notes

- Live SignalR events are projections, not authoritative state.
- `batches/{batchId}/result.json` is the durable platform handoff.
- `run-index/{runId}.json` is the primary reverse-lookup source for a run.
- Duplicate result deliveries are expected and intentionally deduplicated.
- Sequential engine mode bypasses the platform entirely; this repo documents
  and implements only the queue-worker path.