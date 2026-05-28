# Implementation Plan: QA Orchestration Validation

**Branch**: `099-test-debug` | **Date**: 2026-05-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from [specs/099-test-debug/spec.md](spec.md)

## Summary

Validate and harden the existing QA orchestration path so real Azure end-to-end runs consistently complete with correct final aggregation, trace metadata continuity, idempotent duplicate completion handling, and deterministic not-found behavior for unknown orchestration identifiers.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: FastAPI, Azure Functions (Durable), azure-servicebus, azure-storage-blob, azure-identity, pydantic v2, httpx, OpenTelemetry  
**Storage**: Azure Blob Storage for batch artifacts/results, AzureWebJobsStorage for Durable/task hub and run-index state  
**Testing**: pytest (+ existing route/orchestrator integration-style tests and QA harness scripts)  
**Target Platform**: Azure App Service + Azure Functions (Flex/consumption style) + Service Bus + Blob Storage
**Project Type**: Cloud web-service + serverless orchestration  
**Performance Goals**: At least 95% of valid QA test batches reach terminal state within 2 minutes (SC-001)  
**Constraints**: Managed Identity only, no platform SQL, no secrets in code, idempotent processing, traceability across correlationId and traceparent  
**Scale/Scope**: QA validation scope for batch submission/status, callback intake, aggregation, and duplicate replay behavior

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Zero-Trust Identity: PASS. Validation and design preserve MI + RBAC-only access paths.
- No Secrets in Code: PASS. Artifacts and quickstart rely on environment-driven values only.
- Infrastructure as Terraform: PASS. No imperative production infra changes introduced by this feature plan.
- Test-First Development: PASS. Each story includes explicit red-green test tasks before implementation tasks.
- Resilient by Default: PASS. Explicit duplicate replay idempotency and malformed payload handling included.
- Observability Everywhere: PASS. Trace continuity and evidence capture are first-class outcomes.
- Simplicity and YAGNI: PASS. Scope is validation hardening of existing flow, not architecture expansion.

Post-Design Re-check: PASS. Phase 1 artifacts remain compliant with all constitution gates.

## Project Structure

### Documentation (this feature)

```text
specs/099-test-debug/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── orchestration-validation-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
api/
├── durable_client.py
├── routes_assess.py
└── models.py

orchestrator/
├── functions/
│   ├── fanout/
│   │   └── __init__.py
│   ├── result_intake/
│   │   └── __init__.py
│   └── dlq_replay/
│       └── __init__.py
├── sb_contracts.py
└── engine_contracts.py

runtime/
├── config.py
├── telemetry.py
└── events.py

tests/
├── test_routes_assess.py
├── test_result_intake.py
├── test_aggregate.py
├── test_dispatch_run.py
├── test_progress_state.py
└── test_traceability.py
```

**Structure Decision**: Existing single backend/orchestrator codebase. No new top-level projects are introduced; this feature focuses on behavior validation and hardening in current API/orchestrator/runtime/test boundaries.

## Phase 0: Research Outcomes

Research completed in [research.md](research.md), resolving validation strategy, event normalization approach, idempotency evidence source, and observability evidence model.

## Phase 1: Design Outcomes

Design artifacts completed:

- Data model: [data-model.md](data-model.md)
- Contracts: [contracts/orchestration-validation-contract.md](contracts/orchestration-validation-contract.md)
- Quickstart: [quickstart.md](quickstart.md)

Agent context update executed via update-agent-context script.

## Complexity Tracking

No constitution violations requiring justification after tasks include story-level test-first sequencing.
