# Feature Specification: AWR Platform Baseline

**Feature Branch**: `001-platform-baseline`  
**Created**: 2026-03-02  
**Status**: SUPERSEDED by [`002-platform-mode-shift`](../002-platform-mode-shift/spec.md)  
**Input**: Platform layer — REST API, durable orchestration, Azure SQL persistence, APIM gateway, and Terraform infrastructure.

> ⚠️ **Superseded.** The `/runs` + `/artifacts` API surface and the
> platform-owned `engine.RunRecord` / `engine.Artifact` / `engine.Idempotency`
> SQL tables described below were never deployed to a live environment and
> have been removed from the codebase. The platform now implements the
> `/assess/batch` contract owned by the `awr-cv-match-client` repo. See
> [spec 002](../002-platform-mode-shift/spec.md).

## User Scenarios & Testing

### User Story 1 — Submit a Run (Priority: P1)

A client application submits a new processing run to the platform via `POST /runs`. The request includes an idempotency key to ensure that retried or duplicate submissions produce exactly one run record. The platform persists the run in Azure SQL, enqueues work to Service Bus, and returns the run ID.

**Why this priority**: Core workflow — without run submission, no other feature functions.

**Independent Test**: Call `POST /runs` with a unique idempotency key, verify 201 response with a `run_id`. Call again with the same key, verify same `run_id` is returned (no duplicate).

**Acceptance Scenarios**:

1. **Given** no existing run with idempotency key `abc-123`, **When** `POST /runs` with key `abc-123`, **Then** 201 Created with new `run_id` and run status `started`.
2. **Given** a run already exists with idempotency key `abc-123`, **When** `POST /runs` with key `abc-123`, **Then** 200 OK returning the existing `run_id` (no new record created).
3. **Given** a valid run submission, **When** SQL is temporarily unavailable (transient fault), **Then** the platform retries with exponential backoff and eventually succeeds or returns 503.

---

### User Story 2 — Complete a Run (Priority: P1)

An engine worker calls `PATCH /runs/{runId}` to record completion of a run, including timings, token usage, final status, and any error details.

**Why this priority**: Closing the run lifecycle is required for any downstream reporting or artifact association.

**Independent Test**: Create a run, then PATCH it with `status=completed`, `duration_ms=1200`, `tokens_used=500`. Verify the run record is updated and GET returns the completed state.

**Acceptance Scenarios**:

1. **Given** a run in `started` status, **When** `PATCH /runs/{runId}` with `status=completed`, **Then** 200 OK with updated run record.
2. **Given** a non-existent `runId`, **When** `PATCH /runs/{runId}`, **Then** 404 Not Found with RFC 7807 problem+json body.
3. **Given** a run already in `completed` status, **When** `PATCH /runs/{runId}` again, **Then** 409 Conflict (idempotent guard).

---

### User Story 3 — Register Artifacts (Priority: P2)

After a run completes, the engine registers output artifacts (files, reports, logs) via `POST /runs/{runId}/artifacts` in a single batch call.

**Why this priority**: Artifacts are the deliverable output of runs — essential but secondary to the run lifecycle.

**Independent Test**: Create and complete a run, then POST a batch of 3 artifacts. Verify all 3 are persisted and returned by `GET /runs/{runId}`.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** `POST /runs/{runId}/artifacts` with 3 items, **Then** 201 Created with all 3 artifact records.
2. **Given** a non-existent `runId`, **When** `POST /runs/{runId}/artifacts`, **Then** 404 Not Found.
3. **Given** an empty artifact list, **When** `POST /runs/{runId}/artifacts` with `[]`, **Then** 400 Bad Request.

---

### User Story 4 — List and Filter Runs (Priority: P2)

Platform operators query runs via `GET /runs` with optional filters (status, date range) and cursor-based pagination. A single run can be retrieved by `GET /runs/{runId}`.

**Why this priority**: Operational visibility is needed for monitoring and debugging but not for core data flow.

**Independent Test**: Create 5 runs with varying statuses, call `GET /runs?status=completed&limit=2`. Verify correct filter, page size, and cursor token.

**Acceptance Scenarios**:

1. **Given** 10 runs exist, **When** `GET /runs?limit=5`, **Then** 200 OK with 5 runs and a `next_cursor` token.
2. **Given** 3 completed and 2 failed runs, **When** `GET /runs?status=failed`, **Then** 200 OK with exactly 2 runs.
3. **Given** a valid `runId`, **When** `GET /runs/{runId}`, **Then** 200 OK with the full run record including artifacts.

---

### User Story 5 — Fan-out Orchestration (Priority: P2)

The Durable Functions orchestrator receives a batch request and fans out N individual run messages to Service Bus, one per engine worker. Each message is delivered at-least-once with the orchestrator tracking completion.

**Why this priority**: Orchestration enables batch processing but is not needed for single-run submission.

**Independent Test**: Trigger the fan-out function with a batch of 5 run IDs. Verify 5 messages appear on the Service Bus queue.

**Acceptance Scenarios**:

1. **Given** a batch of 5 run IDs, **When** fan-out is triggered, **Then** 5 messages are enqueued to Service Bus.
2. **Given** a Service Bus transient error, **When** fan-out is triggered, **Then** Durable Functions retries automatically.

---

### User Story 6 — DLQ Replay (Priority: P3)

Dead-lettered messages (from repeated engine failures) can be replayed back to the main queue via an HTTP-triggered Azure Function.

**Why this priority**: Operational recovery tool — not needed for happy-path processing.

**Independent Test**: Place 3 messages on the DLQ, call `POST /api/dlq-replay?max=2`. Verify 2 messages moved back to the main queue.

**Acceptance Scenarios**:

1. **Given** 5 DLQ messages, **When** `POST /api/dlq-replay?max=3`, **Then** 3 messages replayed, response includes count.
2. **Given** 0 DLQ messages, **When** `POST /api/dlq-replay`, **Then** 200 OK with `replayed: 0`.

---

### Edge Cases

- What happens when the SQL database is completely unreachable after all retries? → 503 Service Unavailable with retry-after header.
- What happens when a PATCH arrives before the run is created (race condition)? → 404 Not Found; client retries.
- What happens when artifact batch exceeds maximum size? → 413 Payload Too Large.
- What happens when correlationId header is missing? → Platform generates one and includes it in the response.

## Requirements

### Functional Requirements

- **FR-001**: System MUST accept `POST /runs` with idempotency key and return a unique `run_id`.
- **FR-002**: System MUST enforce idempotency — duplicate submissions with the same key return the existing record.
- **FR-003**: System MUST accept `PATCH /runs/{runId}` to update run status, timings, and token usage.
- **FR-004**: System MUST accept `POST /runs/{runId}/artifacts` for batch artifact registration.
- **FR-005**: System MUST support `GET /runs` with status filter and cursor-based pagination.
- **FR-006**: System MUST support `GET /runs/{runId}` returning the full run record with artifacts.
- **FR-007**: System MUST return RFC 7807 `application/problem+json` error responses for all error codes.
- **FR-008**: System MUST propagate `correlationId` on every request/response (generate if absent).
- **FR-009**: System MUST retry transient SQL failures with exponential backoff and jitter (configurable via env vars).
- **FR-010**: System MUST re-open the database connection before each retry attempt.
- **FR-011**: System MUST authenticate to Azure SQL using Entra token via ODBC `attrs_before[1256]` — no passwords.
- **FR-012**: System MUST support optional AAD JWT enforcement on admin endpoints via `AUTH_REQUIRED` toggle.
- **FR-013**: System MUST fan out batch runs to Service Bus via Durable Functions orchestrator.
- **FR-014**: System MUST provide DLQ replay via HTTP-triggered Azure Function.
- **FR-015**: System MUST emit OpenTelemetry traces, structured JSON logs, and metrics for all operations.
- **FR-016**: System MUST never store secrets in code — all credentials via Managed Identity or Key Vault.

### Key Entities

- **RunRecord**: Represents a single processing run (id, idempotency_key, status, created_at, completed_at, duration_ms, tokens_used, error_detail).
- **Artifact**: Output of a run (id, run_id, artifact_type, blob_path, size_bytes, created_at).
- **Idempotency**: Optional table tracking idempotency keys to enforce exactly-once semantics.

## Success Criteria

### Measurable Outcomes

- **SC-001**: `POST /runs` returns within 500ms p95 under normal load.
- **SC-002**: Idempotent re-submission returns the same `run_id` — verified by automated tests.
- **SC-003**: Transient SQL faults are retried up to 6 times with backoff; no data loss on recoverable failures.
- **SC-004**: Zero secrets in source code — verified by CodeQL and manual review.
- **SC-005**: All API errors conform to RFC 7807 — verified by contract tests.
- **SC-006**: Terraform `plan` and `apply` succeed for dev/test/prod environments with no manual intervention.
- **SC-007**: Resource reuse (`*_REUSE=TRUE`) works for all 8 supported resource types without changing module interfaces.
- **SC-008**: CI pipeline (lint + type-check + test + Docker build) passes on every PR.
