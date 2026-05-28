# Tasks: QA Orchestration Validation

**Input**: Design documents from `/specs/099-test-debug/`
**Prerequisites**: `plan.md` (required), `spec.md` (required), `research.md`, `data-model.md`, `contracts/orchestration-validation-contract.md`, `quickstart.md`

**Tests**: Test tasks are required and are sequenced before implementation tasks for each user story to satisfy constitution test-first expectations.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare reusable QA validation tooling and operator documentation hooks.

- [X] T001 Create a reusable QA validation harness script in `scripts/qa-orchestration-validate.sh`
- [X] T002 Add configurable QA validation environment loading guidance to `specs/099-test-debug/quickstart.md`
- [X] T003 [P] Add batch payload fixture template for QA runs in `docs/testing.md`
- [X] T004 [P] Add QA validation metrics output template (terminal window, trace continuity, duplicate replay) to `docs/testing.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish core behavior guards required by all user stories.

**CRITICAL**: No user story implementation starts before this phase is complete.

- [X] T005 Add failing malformed completion payload normalization test in `tests/test_result_intake.py`
- [X] T006 Add failing unknown orchestration status not-found mapping test in `tests/test_routes_assess.py`
- [X] T007 Implement canonical completion payload normalization helper in `orchestrator/engine_contracts.py`
- [X] T008 Implement shared trace metadata extraction helper in `runtime/events.py`
- [X] T009 Update callback parsing to use normalization helper in `orchestrator/functions/result_intake/__init__.py`
- [X] T010 Enforce unknown orchestration instance detection utility in `orchestrator/functions/fanout/__init__.py`
- [X] T011 Add status contract mapping for not-found orchestration responses in `api/durable_client.py`

**Checkpoint**: Foundation ready for story implementation.

---

## Phase 3: User Story 1 - Validate End-to-End Completion (Priority: P1) 🎯 MVP

**Goal**: Ensure valid submissions complete and return required aggregate fields.

**Independent Test**: Submit a representative assessment batch (3 to 10 candidate artifacts) and verify terminal `completed` status with `finalScore`, `finalDecision`, and `mustHaveResult` in result payload for each evaluated candidate.

- [X] T012 [US1] Add failing status progression and terminal-window assertion test in `tests/test_progress_state.py`
- [X] T013 [US1] Add failing aggregate field completeness test for completed batches in `tests/test_routes_assess.py`
- [X] T014 [US1] Implement robust orchestration start/status existence handling in `orchestrator/functions/fanout/__init__.py`
- [X] T015 [US1] Ensure aggregation produces required terminal fields for each candidate in `orchestrator/functions/fanout/__init__.py`
- [X] T016 [US1] Update batch status endpoint projection for completed aggregate payloads in `api/routes_assess.py`
- [X] T017 [US1] Align response model fields with required aggregate output in `api/models.py`
- [X] T018 [US1] Add blob-result fallback handling for completed status retrieval in `api/routes_assess.py`
- [X] T019 [US1] Add terminal-window metrics capture and threshold assertion to validation harness in `scripts/qa-orchestration-validate.sh`
- [X] T020 [US1] Document end-to-end completion verification procedure and metric interpretation in `specs/099-test-debug/quickstart.md`

**Checkpoint**: User Story 1 is independently functional and validates MVP behavior.

---

## Phase 4: User Story 2 - Verify Message Traceability (Priority: P2)

**Goal**: Preserve and expose correlation metadata through dispatch, completion, and final evidence.

**Independent Test**: Submit a batch with known `correlationId` and `traceparent`, then confirm those values in delivery evidence and final retrieval path.

- [X] T021 [US2] Add failing trace continuity test for callback-to-final-evidence path in `tests/test_traceability.py`
- [X] T022 [P] [US2] Ensure Service Bus callback metadata mapping includes trace fields in `orchestrator/sb_contracts.py`
- [X] T023 [US2] Persist normalized trace metadata into completion handling path in `orchestrator/functions/result_intake/__init__.py`
- [X] T024 [US2] Persist trace metadata in final delivery markers and aggregate lineage in `orchestrator/functions/fanout/__init__.py`
- [X] T025 [P] [US2] Emit structured trace-aware lifecycle logs in `runtime/telemetry.py`
- [X] T026 [US2] Surface traceability evidence fields in status response mapping in `api/routes_assess.py`
- [X] T027 [US2] Add traceability sample metrics capture and strict 100% assertion in `scripts/qa-orchestration-validate.sh`
- [X] T028 [US2] Add operator trace verification steps in `docs/application-tracing.md`

**Checkpoint**: User Story 2 is independently functional with end-to-end traceability evidence.

---

## Phase 5: User Story 3 - Confirm Duplicate Delivery Safety (Priority: P3)

**Goal**: Guarantee duplicate completion callbacks do not produce duplicate authoritative outcomes.

**Independent Test**: Replay duplicate completion notifications for one run and verify one authoritative delivery marker and stable final result.

- [X] T029 [US3] Add failing duplicate callback idempotency test for authoritative marker behavior in `tests/test_result_intake.py`
- [X] T030 [US3] Enforce authoritative marker-first idempotency checks in `orchestrator/functions/result_intake/__init__.py`
- [X] T031 [US3] Prevent duplicate callback re-aggregation for terminal runs in `orchestrator/functions/fanout/__init__.py`
- [X] T032 [P] [US3] Harden malformed callback recovery and poison handling in `orchestrator/functions/dlq_replay/__init__.py`
- [X] T033 [US3] Add duplicate replay metrics capture ensuring one authoritative final record per run in `scripts/qa-orchestration-validate.sh`
- [X] T034 [US3] Add duplicate replay operator workflow documentation in `QA_DEPLOYMENT_GUIDE.md`

**Checkpoint**: User Story 3 is independently functional with idempotent duplicate handling.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final consistency checks and execution guidance across stories.

- [X] T035 [P] Reconcile and align validation docs across `specs/099-test-debug/quickstart.md` and `docs/testing.md`
- [X] T036 Run full QA validation walkthrough and capture SC-001 through SC-005 pass/fail evidence in `PATCH_SUMMARY.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1): Can start immediately.
- Foundational (Phase 2): Depends on Setup and blocks all stories.
- User Stories (Phases 3-5): Depend on Foundational completion.
- Polish (Phase 6): Depends on completion of all selected stories.

### User Story Dependencies

- US1 (P1): Starts after Foundational, no dependency on US2/US3.
- US2 (P2): Starts after Foundational and can run after US1 MVP checkpoint.
- US3 (P3): Starts after Foundational and should run after US1 completion behavior is stable.

### Story Completion Order

- Recommended completion order: **US1 -> US2 -> US3**.

---

## Parallel Execution Examples

### User Story 1

```bash
# Parallelizable work after T014 begins:
Task: T017 in api/models.py
Task: T020 in specs/099-test-debug/quickstart.md
```

### User Story 2

```bash
# Parallelizable work after T023 baseline is in place:
Task: T022 in orchestrator/sb_contracts.py
Task: T025 in runtime/telemetry.py
```

### User Story 3

```bash
# Parallelizable work during duplicate safety hardening:
Task: T032 in orchestrator/functions/dlq_replay/__init__.py
Task: T034 in QA_DEPLOYMENT_GUIDE.md
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 and Phase 2.
2. Complete all US1 tasks (T012-T020).
3. Validate independent US1 acceptance behavior before continuing.

### Incremental Delivery

1. Deliver US1 as operational MVP for completion correctness.
2. Add US2 to complete traceability and operator diagnosis value.
3. Add US3 to finalize duplicate replay safety and resilience.

### Team Parallel Strategy

1. One engineer completes foundational tasks.
2. After foundation, one engineer drives US1 core behavior while another prepares US2 telemetry/docs tasks marked `[P]`.
3. US3 parallel tasks (`T032`, `T034`) start once US1 terminal behavior is stable.
