# Application Tracing Guide

This guide explains how to trace a single job application through the 002
platform-mode architecture from submission to final result.

## Canonical Identifiers

- `submissionId = batchId = Durable instance_id`
- `jobId` identifies the target job or requisition
- `applicationId` identifies the submitted application/CV within the batch
- `documentId` identifies the referenced source document
- `runId` identifies one scoring attempt for `(applicationId, runIndex)`
- `runIndex` distinguishes repeated scoring attempts for the same application
- `x-correlation-id` and `traceparent` carry distributed tracing context

## Authoritative State Stores

Use the right store for the question you are trying to answer.

### In-Flight Progress

Authoritative store:

- Durable instance state and custom status

Use it for:

- current batch status
- progress counters
- queued/running/cancelling/completed state transitions

### Run Routing and Lineage Recovery

Authoritative store:

- run-index state written by the platform

Use it for:

- recovering `batchId` and `applicationId` from `runId`
- proving which application owns a returned engine result
- correlating artifacts to the originating run

### Completed Platform Handoff

Authoritative store:

- `batches/{batchId}/result.json` in the `batch-results` container

Use it for:

- per-application final result blocks
- per-run payloads and artifacts
- final aggregate outcome returned by the platform
- recovery after Durable history purge

Retention note:

- `batch-results` is intended to be short-lived staging storage.
- Terraform applies a delete policy after 7 days by default when this repo
   provisions the storage account, and that window is configurable per env.

### Durable Business Persistence

Authoritative store:

- client/backend SQL in the client repo's `talentmatch` schema

Use it for:

- long-term business history
- reporting and reconciliation
- client-owned operational workflows outside the platform repo

## Trace an Application End to End

### Start From Submission

If you know the batch:

1. Find `submissionId` / `batchId` from the API response or client record.
2. Query `GET /assess/batch/{submissionId}/status` for current progress.
3. If complete, inspect `batches/{batchId}/result.json`.

### Start From Application

If you know `applicationId`:

1. Find the parent `batchId` or `submissionId` from the client/backend record.
2. Inspect platform state for the runs attached to that application.
3. Recover each derived `runId` and `runIndex`.
4. Correlate any returned artifacts to those `runId`s.
5. Confirm the matching `applicationId` block in the completed result document.

### Start From Run Result Or Artifact

If you know `runId` or an artifact blob:

1. Use run-index state to recover `batchId`, `applicationId`, and `runIndex`.
2. Use `batchId` to inspect the platform status or completed result blob.
3. Use `applicationId` to identify the owning application block and aggregate.
4. Use `correlationId` and `traceparent` to connect the transport-level trace.

## SignalR and Polling

Azure SignalR is a live projection channel, not the system of record.

Use SignalR for:

- operator dashboards
- client-facing progress updates
- live notifications that a run, application, or batch has transitioned state

Do not use SignalR as the only place to answer:

- which application owns a run
- which artifacts belong to a run
- whether a completed result is durable

For those questions, fall back to Durable state, run-index state, result blobs,
and the client/backend record.

If live projection is disabled, not configured, or SignalR publish/auth fails,
the platform falls back to polling without changing the authoritative state
model. Clients and operators should treat `GET /assess/batch/{submissionId}/status`
and `batches/{batchId}/result.json` as the canonical recovery path.

Managed-identity note:

- In Azure, the preferred publish path uses `SIGNALR_SERVICE_ENDPOINT` with the
   Functions managed identity.
- `SIGNALR_CONNECTION_STRING` is retained as a local/dev fallback only.

## Suggested Event Fields

Every live event should be traceable without guessing. Event payloads should
include:

- `submissionId`
- `batchId`
- `jobId`
- `applicationId` when applicable
- `runId` when applicable
- `runIndex` when applicable
- `eventType`
- `status`
- `timestamp`
- `correlationId`
- `traceparent`
- artifact names, URIs, and hashes when artifacts are involved

## Operator Trace Verification Workflow

Use this checklist during QA validation to prove end-to-end trace continuity:

1. Capture `submissionId`, `x-correlation-id`, and `traceparent` at submit time.
2. Retrieve `GET /assess/batch/{submissionId}/status` until terminal.
3. For each `result.cvs[].runs[]` entry verify:
   - `runId` is present
   - `correlationId` matches submit-time value (or known deterministic transformation)
   - `traceparent` is present and W3C formatted (`00-<trace-id>-<span-id>-<flags>`)
4. Confirm each run artifact in final evidence maps to the same `applicationId` and `documentId` lineage.
5. If mismatch occurs, inspect run-index and result-delivery blob markers for the run to identify routing/source breakage.

## Failure and Recovery Workflow

### Durable History Purged

If the Durable instance no longer has history:

1. Query the completed result blob at `batches/{batchId}/result.json`.
2. Use run-index state to recover the `runId -> applicationId` mapping if
   you are starting from a returned run or artifact.
3. Use the client/backend record for long-lived business context.

### Duplicate Result Delivery

If the engine delivers the same result twice:

1. Confirm both deliveries reference the same `runId`.
2. Confirm the platform deduplicates or idempotently handles the repeated
   result.
3. Verify that the final result document and progress state reflect only one
   logical completion for that run.

### Partial Failures

If only some runs fail:

1. Use `applicationId` to isolate the affected application block.
2. Compare expected `runIndex` values to returned run payloads.
3. Inspect artifacts and error metadata for failed or partial runs.
4. Confirm the aggregate result explains the terminal outcome.

## Operator Questions This Guide Should Answer

- Which batch owns this application?
- Which runs were created for this application?
- Which returned result belongs to which application?
- Which artifacts belong to which run?
- Can I still reconstruct lineage if Durable history is gone?
- If SignalR said a run completed, where is the authoritative durable record?
