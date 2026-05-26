# Feature Specification: Platform-Mode Shift

**Feature Branch**: `002-platform-mode-shift`  
**Created**: 2026-03-12  
**Status**: In Progress  
**Supersedes**: [`001-platform-baseline`](../001-platform-baseline/spec.md)  
**Input**: Implement the platform side of the contract authored in the
`awr-cv-match-client` repo at
`specs/008-platform-mode-shift/platform-contract.md`. A copy lives at
[`platform-contract.md`](./platform-contract.md).

## Why this shift

The original platform (spec 001) modelled itself as a generic engine-agnostic
runner with its own `RunRecord` / `Artifact` / `Idempotency` tables. The actual
production design assigns ownership of the `talentmatch` SQL schema to the
client repo: the client persists batches, runs, aggregated results, and the
reconciler. The platform's job is narrower and more orthogonal:

- Accept a batch of CV references + an inline prompt over HTTP.
- Fan out `N × runCount` per-run dispatches to the engine via **Service Bus**
  (queue `engine-runs`), one `RunMessage` per CV × run.
- Receive engine results either from the `engine-results` Service Bus queue
  or via `PATCH /runs/{runId}` (driven by the engine's `REPORT_MODE`).
- Aggregate per-CV results (median, variance, decision rollup) and persist
  them to the platform-owned `batch-results` blob container.
- Expose a status / cancel surface over HTTP.

There is **no platform-owned SQL state**. Durable Functions' task hub is the
in-flight orchestration store; final batch results live as JSON in a blob
container and can be picked up by the client at any time (including after a
period of being offline). The client writes those results into its own
`talentmatch` schema on its own schedule.

### Engine invocation modes

The engine ships two wrapper modes:

| Mode | Volume | Path | Platform involvement |
| ---- | ------ | ---- | -------------------- |
| Sequential (synchronous HTTP) | Low | Client → Engine direct | **None** |
| Queue-worker (KEDA-scaled, Service Bus) | High | Client → Platform → SB → Engine | **Yes** |

The platform exists exclusively for the queue-worker / high-volume path.
Sequential mode bypasses the platform entirely.

## User Scenarios & Testing

### User Story 1 — Submit a Batch (P1)

A client `POST /assess/batch` with an inline prompt and 1–100 CV refs. The
platform responds 202 with `submissionId` and a `pollUrl`. Submitting the same
`batchId` twice (header `Idempotency-Key` mirrors `batchId`) does not create a
second orchestration.

**Acceptance**:

1. First submission of `batchId=B1` → 202, `submissionId=B1`,
   orchestration started.
2. Repeat submission of `batchId=B1` → 202 (or 200), same `submissionId`, no
   second fan-out.
3. `Idempotency-Key != body.batchId` → 400.

### User Story 2 — Poll Status (P1)

`GET /assess/batch/{submissionId}/status` returns one of `queued`, `running`,
`completed`, `failed`, `cancelling`, `cancelled`. While running, response
includes `progress.cvsCompleted / cvsTotal`. On `completed`, response includes
`result.cvs[]` with per-CV runs + aggregated rollup.

### User Story 3 — Cancel (P2)

`POST /assess/batch/{submissionId}/cancel` → 202 (cancelling), 200 (already
cancelled), or 409 (already completed).

### User Story 4 — Observe Progress And Trace Lineage (P1)

An operator or client can determine, for any in-flight or completed batch,
which applications are pending, running, completed, failed, or cancelled; which
per-application runs exist; what artifacts each run produced; and how a given
progress or completion event maps back to the original application.

**Acceptance**:

1. For every `(applicationId × runIndex)` dispatched by the platform, a stable
   `runId` exists and can be mapped back to `submissionId` / `batchId`,
   `jobId`, `applicationId`, and `documentId`.
2. The platform provides a live progress/event channel for subscribed clients;
   Azure SignalR is the default managed implementation in Azure. Polling via
   `GET /assess/batch/{submissionId}/status` remains the mandatory fallback.
3. If the live event channel is unavailable, an operator can reconstruct the
   same batch/application/run lineage from platform state, logs, and persisted
   result documents.
4. For a completed application, the platform can identify the per-run status,
   timings, tokens, artifacts, and aggregated outcome returned to the client.

## Progress, State & Event Tracking Requirements

- **Submission identity**: `submissionId = batchId = Durable instance_id`.
  Every progress surface, event, log, and persisted result must carry or be
  recoverable from that identity.
- **Application lineage**: the platform must maintain a reference from each
  `applicationId` to all of its scoring runs for a submission, including the
  derived `runId`, `runIndex`, and any returned artifacts.
- **Run lineage**: for each `runId`, the platform must be able to recover the
  owning `submissionId` / `batchId`, `jobId`, `applicationId`, `documentId`,
  `runIndex`, dispatch timestamp, completion timestamp, final status, and
  artifact metadata.
- **Progress state model**: the platform must maintain explicit in-flight state
  for submission-level, application-level, and run-level progress. At minimum,
  it must track queued, dispatched, running, completed, failed, cancelling, and
  cancelled states where applicable.
- **Live event projection**: the platform must publish state transitions and
  progress updates to subscribed clients. Azure SignalR is the default Azure
  implementation. These events are non-authoritative projections derived from
  authoritative platform/client state.
- **Event payload contract**: each emitted progress/state event must include
  enough identifiers to correlate it end-to-end: `submissionId`, `batchId`,
  `jobId`, `applicationId`, `runId`, `runIndex`, `correlationId`, W3C
  `traceparent`, `eventType`, `status`, and a timestamp. Artifact-bearing
  events must also include artifact names, URIs, and hashes when available.
- **Status fallback**: `GET /assess/batch/{submissionId}/status` remains the
  canonical pull-based fallback for clients that are disconnected from the live
  event channel.
- **Completed result handoff**: the final batch result document must preserve
  per-application lineage, including the list of runs that contributed to each
  aggregated outcome.

## Documentation & Test Requirements

- **Documentation**: implementation documentation must clearly describe the
  progress/state model, identifier lineage, authoritative state stores,
  SignalR/event payloads, artifact tracing, retention behavior, and the
  operator workflow for tracing a single application from submission through
  final aggregation.
- **Documentation completeness**: the repository must contain enough written
  material for an engineer unfamiliar with the system to answer where a batch,
  application, run, or artifact is tracked and how to reconstruct its history.
- **Tests**: automated tests must cover submission-level progress updates,
  application-level and run-level lineage mapping, live event emission,
  polling fallback behavior, result-document completeness, and the ability to
  trace a returned artifact back to the originating `applicationId` and `runId`.
- **Failure-path tests**: automated tests must cover partial failures,
  cancelled batches, unknown `runId` callbacks, duplicate result delivery, and
  recovery of lineage after Durable history has been purged but result blobs
  remain.

## Non-functional Requirements

- **No SAS tokens**: blob reads use `DefaultAzureCredential` (MI in Azure).
- **SHA-256 verify**: every CV blob is hashed and compared to the client's
  declared `sha256` before being sent to the engine.
- **Trace propagation**: `x-correlation-id` and W3C `traceparent` flow API →
  orchestrator → engine → result intake → live event projection.
- **Progress observability**: every submission/application/run state
  transition produces structured logs, metrics, and trace-linked events.
- **Asset traceability**: every artifact returned from the engine can be traced
  back to the owning `runId`, `applicationId`, and `submissionId`.
- **Idempotency window**: 7+ days, enforced by Durable's persistent
  `instance_id`.

## Out of Scope

- Persisting batches, runs, aggregated results to `talentmatch.*` — owned by
  the client repo. The platform stages final results in blob; the client reads
  and writes its own database.
- Using Azure SignalR as a live projection channel does **not** make SignalR a
  system of record; authoritative business persistence remains with the client
  repo and authoritative in-flight orchestration state remains with Durable.
- Reconciler — owned by the client repo (§6 of the contract).
- Client-side DLQ / `FailureQueueItems` — owned by the client repo.
- Sequential / synchronous engine invocation — that path is client↔engine
  direct and never touches the platform.

## See Also

- [`platform-contract.md`](./platform-contract.md) — frozen wire contract.
- [`plan.md`](./plan.md) — implementation plan.
- [`tasks.md`](./tasks.md) — dependency-ordered tasks.
- [`quickstart.md`](./quickstart.md) — local/dev quickstart for the 002 flow.
- [`../../docs/application-tracing.md`](../../docs/application-tracing.md) —
  operator tracing guide for batch, application, run, and artifact lineage.
