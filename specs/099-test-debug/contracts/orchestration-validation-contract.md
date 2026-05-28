# Orchestration Validation Contract

## Purpose

Define the externally visible behavior used to validate QA orchestration completion, traceability, idempotency, and not-found semantics.

## HTTP Interface

### POST /assess/batch

- Purpose: Submit a batch for orchestration processing.
- Required behaviors:
  - Accept valid payload and return accepted response with submission identifier.
  - Preserve correlation metadata for downstream evidence.
- Contract assertions:
  - Response includes submissionId.
  - Initial state is queued (or equivalent accepted-running transition).

### GET /assess/batch/{submissionId}/status

- Purpose: Query authoritative orchestration progress and terminal outcome.
- Required behaviors:
  - Return current lifecycle status.
  - Return final aggregated candidate results when completed.
- Contract assertions:
  - Completed response includes finalScore, finalDecision, mustHaveResult per candidate.

### GET /api/orchestration/{instanceId}

- Purpose: Inspect orchestration instance status directly (operator path).
- Required behaviors:
  - Known instance IDs return status payload.
  - Unknown instance IDs return not-found semantics.
- Contract assertions:
  - Random/unknown IDs do not return synthetic running states.

### PATCH /runs/{runId}

- Purpose: Accept completion callback in HTTP report mode.
- Required behaviors:
  - Resolve runId to owning batch/application context.
  - Normalize callback payload before reading structured fields.
  - Trigger orchestration external event flow.

## Message Interface

### Service Bus Queue: engine-results

- Purpose: Accept completion callback in servicebus report mode.
- Required behaviors:
  - Parse run completion payload and metadata.
  - Preserve correlationId and traceparent into completion evidence.
  - Handle duplicate delivery idempotently.

## Persistence Interface

### Run Index Mapping

- Mapping contract:
  - runId uniquely maps to submissionId + applicationId + runIndex (+ document context).
- Validation contract:
  - Completion event routing must use this mapping before aggregation.

### Delivery Marker

- Idempotency contract:
  - One authoritative marker per runId terminal completion.
  - Duplicate completions do not create additional authoritative outcomes.

### Final Batch Result Artifact

- Path contract:
  - Final completed result is persisted under batch-scoped location.
- Content contract:
  - Per-candidate aggregation includes final score and decision fields required by spec success criteria.

## Traceability Contract

- submission-time metadata and completion-time metadata must be correlatable via:
  - submissionId/batchId
  - runId
  - applicationId
  - correlationId
  - traceparent

## Error Semantics

- Unknown orchestration IDs: not-found response.
- Malformed/variant callback payloads: processed via normalization path without unhandled orchestrator failure.
- Duplicate completion events: idempotent success path with preserved authoritative result.