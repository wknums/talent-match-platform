# Implementation Plan: Platform-Mode Shift

**Feature**: `002-platform-mode-shift`  
**Supersedes**: `001-platform-baseline`

## Architecture

```text
                              ┌────────── Sequential / low-volume ──────────┐
                              │             (bypasses platform)              │
                              ▼                                              ▼
                            Client ─────────HTTP─────────────────────► Engine (sync wrapper)

                            Client
                              │  HTTP  (/assess/batch · /status · /cancel)
                              ▼
APIM  ──►  FastAPI  ──HTTP──►  Functions host  ─── enqueue RunMessage ──►  SB: engine-runs
                                  │                                                 │
                                  │ Durable Task Hub                                ▼
                                  │ (Azure Storage)                       Engine (KEDA queue-worker)
                                  │                                                 │
                                  │            ┌────────────────────────────────────┤
                                  │            │ REPORT_MODE=servicebus             │ REPORT_MODE=http
                                  │            ▼                                    ▼
                                  │     SB: engine-results              HTTP PATCH /runs/{runId}
                                  │            │                                    │
                                  │            └──────────────┬─────────────────────┘
                                  │                           ▼
                                  │            Result-intake handler raises
                                  │            Durable external event "run-{runId}"
                                  ▼
                       Aggregation writes batches/{batchId}/result.json
                       to blob container `batch-results`
                       (DefaultAzureCredential, no SAS)
```

- **FastAPI** owns the public contract (`/assess/batch`, `/status`, `/cancel`).
  Stateless. Forwards to the Functions host via internal HTTP.
- **Functions host** (Azure Functions v2 Python, Durable Functions extension).
  - Orchestrator `batch_orchestrator` — for each (CV × run) mint a `runId`,
    enqueue a `RunMessage`, then `wait_for_external_event("run-{runId}")`.
  - Activities — `dispatch_run` (SB send + run-index write), aggregation,
    progress-state update, blob result write.
  - SB-trigger function on `engine-results` — validates `RunResultMessage`
    and raises the Durable external event.
  - HTTP route `PATCH /runs/{runId}` — same role for `REPORT_MODE=http`.
  - DLQ-replay function for `engine-runs` and `engine-results` DLQs.
- **Durable Task Hub** persists in-flight orchestrations in the storage
  account (`AzureWebJobsStorage`). `submissionId = batchId = instance_id`.
  Durable custom status is the authoritative in-flight submission progress
  surface.
- **Run index** persists operational routing state mapping
  `runId -> batchId + applicationId + runIndex + documentId` so result-intake,
  artifact tracing, and operator workflows can recover the owning application.
- **Blob `batch-results` container** holds completed batch results until the
  client picks them up. Survives Durable history purges; survives client
  downtime.
- **Azure SignalR** is an optional but recommended live projection channel for
  batch/application/run state changes. SignalR events are derived from Durable
  state, run-index state, and result documents; they are not a source of truth.
- **No platform SQL.** The `talentmatch` schema is read/written exclusively
  by the client repo per the platform contract.

## Configuration

| Var | Purpose |
| --- | --- |
| `FUNCTIONS_HOST_URL` | FastAPI → Functions host base URL |
| `FUNCTIONS_HOST_KEY` | Optional function key |
| `SB_NAMESPACE` | Service Bus namespace (FQNS or short name) |
| `SB_RUNS_QUEUE` | Platform → Engine queue (default `engine-runs`) |
| `SB_RESULTS_QUEUE` | Engine → Platform queue (default `engine-results`) |
| `ENGINE_REPORT_MODE` | `servicebus` or `http` — must match engine config |
| `BLOB_ACCOUNT` | Storage account (used by CV refs + batch results) |
| `BLOB_CONTAINER` | CV uploads container (`cv-uploads`) |
| `BLOB_RESULTS_CONTAINER` | Batch results container (`batch-results`) |
| `SIGNALR_CONNECTION_STRING` or managed identity settings | Live event projection transport |
| `LIVE_PROGRESS_ENABLED` | Toggle for SignalR/event projection |

## File Layout (this repo)

```text
api/
  main.py                    # FastAPI app, mounts assess_router only
  routes_assess.py           # /assess/batch + /status + /cancel
  durable_client.py          # httpx wrapper for Functions host
  models.py                  # Pydantic v2 wire models
  auth.py                    # AAD JWT dep
  deps.py                    # correlation-id, pagination

orchestrator/
  sb_contracts.py            # RunMessage / RunResultMessage / FinishRunRequest
  engine_contracts.py        # Internal aggregation payloads
  functions/
    fanout/__init__.py       # batch_orchestrator + dispatch_run activity +
                             # internal HTTP routes
    result_intake/__init__.py
                             # SB-trigger on engine-results +
                             # PATCH /runs/{runId} HTTP route
    dlq_replay/__init__.py   # operational DLQ drain / requeue

runtime/
  config.py                  # Settings: functions/SB/blob (no SQL)
  errors.py                  # ProblemDetail (RFC 7807)
  telemetry.py               # OTel + App Insights setup
  events.py                  # event payloads + SignalR projection helpers

function_app.py              # registers fanout + result_intake + dlq_replay
host.json                    # Durable task hub: AwrPlatformTaskHub
```

## State Model

- **Batch identity**: `submissionId = batchId = Durable instance_id`.
- **Application identity**: `applicationId` remains the stable business key
  for a CV within a submission.
- **Run identity**: `runId` is deterministic for `(batchId, applicationId,
  runIndex)` and is the key used by the engine and result-intake paths.
- **Authoritative stores**:
  - Durable instance state + custom status for in-flight submission state.
  - Run-index storage for reverse lookup from `runId` to the owning batch and
    application.
  - `batches/{batchId}/result.json` for the completed platform handoff.
  - Client SQL for durable business persistence after ingestion.
- **Progress granularity**:
  - Submission-level: queued, running, cancelling, cancelled, failed,
    completed.
  - Application-level: pending, running, partial, failed, completed.
  - Run-level: queued, dispatched, running, succeeded, failed, partial,
    cancelled.
- **Event projection**:
  - SignalR emits versioned events for batch accepted, run dispatched,
    run completed/failed, application completed, batch completed, and batch
    cancelled.
  - Every event carries `submissionId`, `batchId`, `jobId`, `applicationId`
    when applicable, `runId` when applicable, `runIndex` when applicable,
    `correlationId`, `traceparent`, `eventType`, `status`, and a timestamp.

## Phasing

1. **Phase A — Contracts & config (this commit)**:
   - `runtime/config.py` — SB + blob results + report-mode.
   - `orchestrator/sb_contracts.py` — engine-aligned wire models.
   - `pyproject.toml` / `requirements.txt` — `azure-servicebus` restored.
   - All `.env_*` files — SB and blob-results restored.
   - Specs (this file + spec.md + tasks.md) updated.
2. **Phase B — Queue-worker orchestration baseline (implemented)**:
   - Drop inline engine HTTP call from scoring activities.
   - Dispatch one `RunMessage` per `(CV × run)` via Service Bus.
   - Receive results from Service Bus or `PATCH /runs/{runId}`.
   - Maintain run-index storage for result routing.
   - Write `batches/{batchId}/result.json` on completion.
3. **Phase C — Durable progress and lineage state**:
   - Expand Durable custom status so progress updates on every dispatch and
     every terminal run result.
   - Persist enough reverse-lookup metadata to trace `runId -> batchId ->
     applicationId -> artifacts` without ad-hoc log correlation.
   - Surface batch-level and application-level progress through
     `GET /assess/batch/{submissionId}/status`.
4. **Phase D — Live progress/event projection**:
   - Introduce a versioned event schema for batch/application/run lifecycle
     events.
   - Project those events to Azure SignalR when live progress is enabled.
   - Preserve polling as the mandatory fallback when SignalR is unavailable.
5. **Phase E — Observability, docs, and tests**:
   - W3C trace propagation FastAPI → SB message / HTTP result path → engine →
     result-intake → SignalR projection.
   - Span linking on result-intake and event projection.
   - Add clear documentation for identifiers, state stores, event taxonomy,
     operator tracing workflow, and artifact lineage.
   - Add test coverage for progress state, lineage recovery, event emission,
     result completeness, and purge fallback behavior.
6. **Phase F — Auth and infra hardening**:
   - JWKS-validated AAD JWT in `api/auth.py`, APIM `Idempotency-Key`
     requirement.
   - Storage container `batch-results` + lifecycle policy.
   - SB queues + DLQs in Terraform, role assignments for Functions identity.
   - Add Azure SignalR infrastructure and identity/connection wiring if live
     projection is enabled.

## Open Questions

- Engine `RunResultMessage.status` mapping to client-facing `BatchResult`
  decision aggregation (`mode` vs. majority? threshold-driven?).
- TTL on `batch-results` blobs — default 7 days; configurable per env?
- SignalR channel partitioning and authorization model — per submission,
  per tenant, or operator/admin fan-out?
- Whether application-level progress should be returned inline from the status
  endpoint or via a dedicated detail route for large batches.
- Should the platform expose `DELETE /assess/batch/{batchId}` for explicit
  client-side cleanup, or rely purely on lifecycle policy?
