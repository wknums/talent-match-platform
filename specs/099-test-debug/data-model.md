# Data Model: QA Orchestration Validation

## Entity: Batch Submission

- Description: Top-level request to evaluate one or more candidate artifacts.
- Key fields:
  - submissionId (string, UUID-formatted)
  - batchId (string, UUID-formatted, same value as submissionId)
  - jobId (string)
  - correlationId (string)
  - traceparent (string, W3C trace context)
  - status (enum: queued, running, completed, failed, cancelled)
  - createdAt (datetime)
  - completedAt (datetime, optional)
- Relationships:
  - One Batch Submission has many Run Records.
  - One Batch Submission has many Aggregated Results (one per candidate/application).
- Validation rules:
  - submissionId and batchId must be consistent for the same orchestration instance.
  - status transitions must follow lifecycle order constraints.

## Entity: Run Record

- Description: A single orchestrated execution attempt for a candidate/run index.
- Key fields:
  - runId (string)
  - submissionId (string)
  - applicationId (string)
  - runIndex (integer)
  - documentId (string)
  - dispatchStatus (enum: queued, dispatched, running, terminal)
  - terminalStatus (enum: succeeded, failed, partial, cancelled, optional until terminal)
  - artifactRefs (list)
  - updatedAt (datetime)
- Relationships:
  - Belongs to one Batch Submission.
  - Is addressed by one or more Completion Events (duplicates possible).
- Validation rules:
  - runId must map back to exactly one submissionId + applicationId + runIndex tuple.
  - terminalStatus can be set once per authoritative completion.

## Entity: Completion Event

- Description: Result callback message indicating a run terminal outcome.
- Key fields:
  - runId (string)
  - status (string)
  - resultPayload (object, normalized from wire format)
  - correlationId (string)
  - traceparent (string)
  - receivedAt (datetime)
  - messageId (string, optional)
- Relationships:
  - Targets one Run Record.
  - May correspond to one existing Delivery Marker.
- Validation rules:
  - runId must resolve to known run-index mapping before final aggregation.
  - payload must be normalized prior to field-level access.

## Entity: Aggregated Result

- Description: Final per-application outcome exposed through batch status.
- Key fields:
  - submissionId (string)
  - applicationId (string)
  - finalScore (number)
  - finalDecision (string)
  - mustHaveResult (boolean)
  - sourceArtifacts (list)
  - computedAt (datetime)
- Relationships:
  - Belongs to one Batch Submission and one applicationId.
- Validation rules:
  - For successful batch completion, finalScore/finalDecision/mustHaveResult must be present.

## Entity: Delivery Marker

- Description: Idempotency evidence indicating completion was already processed for runId.
- Key fields:
  - runId (string)
  - submissionId (string)
  - applicationId (string)
  - terminalStatus (string)
  - correlationId (string)
  - traceparent (string)
  - persistedAt (datetime)
- Relationships:
  - One Delivery Marker corresponds to one authoritative Run Record completion.
- Validation rules:
  - Only one authoritative marker per runId.
  - Duplicate completion events must not create conflicting markers.

## State Transitions

### Batch Submission state machine

- queued -> running
- running -> completed
- running -> failed
- running -> cancelled

### Run Record state machine

- queued -> dispatched
- dispatched -> running
- running -> terminal (succeeded | failed | partial | cancelled)
- terminal -> terminal (duplicate callbacks do not change authoritative outcome)