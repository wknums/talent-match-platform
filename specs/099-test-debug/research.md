# Phase 0 Research: QA Orchestration Validation

## Decision 1: Validate against real QA Azure resources and message paths

- Decision: Use real QA endpoints, real Service Bus queues, and real blob artifacts for acceptance validation.
- Rationale: The target failures involve distributed orchestration timing, RBAC, callback payload formats, and queue retry/idempotency semantics that are not reliably reproducible in fully mocked local flows.
- Alternatives considered:
  - Pure local emulator validation: Rejected because it misses cloud RBAC/network/runtime behavior.
  - Unit-test-only validation: Rejected because it cannot prove end-to-end traceability and delivery marker behavior.

## Decision 2: Normalize completion payload shape before orchestration access

- Decision: Treat completion event payload as potentially variant-encoded and normalize into a canonical dictionary-like structure before field access.
- Rationale: Observed QA failures include callback payloads arriving as encoded strings; normalization prevents unhandled attribute access errors and keeps orchestrations progressing.
- Alternatives considered:
  - Strict payload type enforcement only: Rejected because it would fail valid-but-encoded callback events.
  - Silent drop on malformed payload: Rejected because it obscures failures and harms diagnosability.

## Decision 3: Use delivery marker as idempotency source of truth for duplicates

- Decision: Preserve a single authoritative completion marker per run and make duplicate callback handling idempotent against that marker.
- Rationale: Duplicate delivery is expected in at-least-once messaging and must not produce duplicate final outcomes.
- Alternatives considered:
  - Ignore duplicates based only on transient in-memory checks: Rejected because it is not resilient across restarts.
  - Recompute aggregation for every duplicate callback: Rejected because it risks result churn and unnecessary cost.

## Decision 4: Verify trace continuity through persisted operational evidence

- Decision: Validate correlation and trace continuity using persisted run-index/delivery evidence and final result artifacts.
- Rationale: Persisted evidence supports deterministic operator verification after transient logs roll over.
- Alternatives considered:
  - Rely only on live log streaming: Rejected because stream retention and availability are inconsistent.
  - Rely only on API response payloads: Rejected because API payloads alone do not provide full callback lineage evidence.

## Decision 5: Preserve no-platform-SQL boundary while validating orchestration outcomes

- Decision: Keep platform validation scope strictly in API, Durable orchestration, Service Bus, and blob layers.
- Rationale: Constitution and mode-shift architecture place business persistence in the client tier; platform must remain orchestration-centric.
- Alternatives considered:
  - Add platform SQL reconciliation logic: Rejected due to constitutional and architectural boundary violation.