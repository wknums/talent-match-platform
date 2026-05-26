# Tasks: Platform-Mode Shift

**Feature**: `002-platform-mode-shift`

Legend: `[x]` done, `[ ]` open. `[P]` parallelisable.

## Phase A — Contracts & config (this commit)

- [x] `runtime/config.py` — restore `sb_*`, `engine_report_mode`,
      `blob_results_container`; drop legacy `engine_*` HTTP fields.
- [x] `orchestrator/sb_contracts.py` — `RunMessage`, `RunResultMessage`,
      `FinishRunRequest` mirroring `auto-assessment-assist/contracts/models.py`.
- [x] `pyproject.toml` / `requirements.txt` — restore `azure-servicebus`.
- [x] `.env.example`, `.env_qa`, `.env_local`, `.env_prod` — restore SB block
      and add `BLOB_RESULTS_CONTAINER` + `ENGINE_REPORT_MODE`; drop
      `ENGINE_BASE_URL` / `ENGINE_API_KEY` / `ENGINE_TIMEOUT_S` / `ENGINE_MAX_RETRIES`.
- [x] `specs/002-platform-mode-shift/spec.md` — clarify SB-only platform,
      sequential bypass, blob-results store.
- [x] `specs/002-platform-mode-shift/plan.md` + `tasks.md` — rewrite for the
      SB-only dual-path design.

## Phase B — Queue-worker orchestration baseline

- [x] `orchestrator/functions/fanout/__init__.py` — queue-worker orchestrator
      dispatches `RunMessage`s, waits on `run-{runId}` external events, writes
      run-index entries, and persists final `batches/{batchId}/result.json`.
- [x] `orchestrator/functions/result_intake/__init__.py` — Service Bus and
      HTTP result-intake paths resolve `runId` ownership and raise the correct
      Durable external event.
- [x] `orchestrator/functions/dlq_replay/__init__.py` + `function_app.py` —
      operational blueprints are registered in the Functions host.
- [x] `api/routes_assess.py` — status path falls back to blob results when
      Durable history has been purged.

## Phase C — Durable progress and lineage state

- [x] [P] `tests/test_progress_state.py` (new) — write failing tests first for
      Durable custom status updates, submission/application/run progress,
      `cvsCompleted`, `runsCompleted`, and last-transition timestamps.
- [x] [P] `tests/test_traceability.py` (new) — write failing tests first for
      `applicationId -> runId -> artifact` lineage recovery and purge-fallback
      traceability.
- [x] `orchestrator/functions/fanout/__init__.py` — update Durable custom
      status on every dispatch and every terminal run result, not only at
      orchestration start.
- [x] `orchestrator/functions/fanout/__init__.py` — expose submission-level
      progress fields including `cvsCompleted`, `cvsTotal`, `runsCompleted`,
      `runsTotal`, and last transition timestamp.
- [x] `orchestrator/functions/fanout/__init__.py` +
      `orchestrator/engine_contracts.py` — preserve application-level lineage
      so `applicationId` can be traced to `runId`s, `runIndex`, `documentId`,
      and artifacts without scanning unrelated batch data.
- [x] `api/models.py` + `api/routes_assess.py` — extend status/result models as
      needed for explicit application progress and lineage details.
- [x] `runtime/config.py` — add feature toggles/settings for live progress
      projection and any required event configuration.

## Phase D — Live progress and event projection

- [x] [P] `tests/test_live_events.py` (new) — write failing tests first for
      versioned event payload completeness, ordering, SignalR-disabled fallback,
      and projection behavior.
- [x] [P] Define a versioned event schema for batch/application/run lifecycle
      events, including identifiers, status, timestamps, trace fields, and
      artifact metadata.
- [x] [P] Distinguish terminal live-event taxonomy for `run.failed`,
      `application.completed`, `batch.cancelling`, and `batch.cancelled`
      instead of flattening those states into generic completion events.
- [x] [P] Add `runtime/events.py` (or equivalent) for event payload generation
      and projection helpers.
- [x] [P] Project live progress/state events to Azure SignalR when enabled.
- [x] [P] Document and enforce SignalR fallback semantics so polling remains
      the canonical recovery path.

## Phase E — Documentation and tests

- [x] [P] `tests/test_routes_assess.py` — submit, idempotent repeat, status,
      cancel state matrix, and richer running-progress assertions.
- [x] [P] `tests/test_dispatch_run.py` — `RunMessage` shape match against
      golden JSON from the engine contracts plus run-index integrity.
- [x] [P] `tests/test_result_intake.py` — SB-trigger raises event; HTTP PATCH
      raises event; unknown `runId`, duplicate result delivery, and trace field
      preservation.
- [ ] [P] `tests/test_aggregate.py` — median, variance, mode decision,
      must-have AND, and per-application lineage completeness.
- [x] [P] Add tests for SignalR/event projection behavior when enabled and for
      polling fallback when live projection is unavailable.
- [x] [P] Add tests for lineage recovery after Durable history is purged but
      `batches/{batchId}/result.json` remains.
- [x] Add or update documentation covering canonical identifiers, state stores,
      event taxonomy, retention, artifact traceability, and the operator
      workflow for tracing a single `applicationId` end to end.

## Phase F — Observability, auth, and infra hardening

- [ ] W3C `traceparent` propagation from FastAPI → SB message /
      HTTP result path → engine → result-intake → event projection.
- [ ] Span linking on result-intake and event projection (link result span to
      dispatch span via `correlation_id`).
- [ ] Structured logging and metrics for every submission/application/run state
      transition and emitted artifact reference.
- [ ] `api/auth.py` — JWKS fetch + signature verification.
- [ ] APIM: require `Idempotency-Key` on `POST /assess/batch`.
- [x] Storage module — ensure `batch-results` container exists; lifecycle
      policy (delete after 7 days, configurable).
- [ ] Service Bus module — `engine-runs` and `engine-results` queues with DLQ
      enabled; role assignments for Functions identity
      (`Azure Service Bus Data Sender` on `engine-runs`,
       `Azure Service Bus Data Receiver` on `engine-results`).
- [ ] Storage role — `Storage Blob Data Contributor` for Functions identity on
      `batch-results` container; existing `Reader` on `cv-uploads` retained.
- [ ] APIM — replace legacy `/runs` + `/artifacts` API definitions with
      `/assess/*`; document `Idempotency-Key` requirement.
- [ ] Add Azure SignalR infrastructure, identity/secretless connection wiring,
      and APIM/client negotiation path if live projection is enabled.
