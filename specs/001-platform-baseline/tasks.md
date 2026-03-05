# Tasks: AWR Platform Baseline

**Input**: Design documents from `specs/001-platform-baseline/`  
**Prerequisites**: plan.md (required), spec.md (required for user stories), data-model.md, contracts/

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, configuration, and cross-cutting utilities

- [x] T001 Create project structure with `api/`, `orchestrator/`, `db/`, `runtime/`, `tests/` directories
- [x] T002 Initialize Python 3.11 project with `pyproject.toml` (FastAPI, Pydantic v2, pyodbc, azure-identity, OpenTelemetry)
- [x] T003 [P] Configure ruff linting (`target-version = "py311"`, line-length 120) and mypy strict mode
- [x] T004 [P] Create `Dockerfile` for containerized API deployment
- [x] T005 [P] Create `alembic.ini` configuration pointing to `db/migrations/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

- [x] T006 Implement `runtime/config.py` — pydantic-settings with SQL, Service Bus, auth, and OTEL env vars
- [x] T007 Implement `runtime/errors.py` — RFC 7807 `application/problem+json` error model and helpers
- [x] T008 [P] Implement `runtime/telemetry.py` — OpenTelemetry tracing/logging/metrics init with App Insights exporter
- [x] T009 [P] Implement `runtime/transient.py` — exponential backoff + full jitter retry for SQL (re-open connection before retry)
- [x] T010 Implement `db/connection.py` — pyodbc + DefaultAzureCredential → Entra token → `attrs_before[1256]`, ODBC Driver 18
- [x] T011 Implement `db/migrations/env.py` — Alembic environment with token-based auth (no password)
- [x] T012 Create `db/migrations/versions/001_initial_schema.py` — `engine.RunRecord`, `engine.Artifact`, `engine.Idempotency` tables
- [x] T013 Implement `api/main.py` — FastAPI app factory with correlationId middleware, lifespan, error handlers, optional JWT enforcement
- [x] T014 [P] Implement `api/deps.py` — correlationId extraction/generation, pagination params, DI helpers
- [x] T015 [P] Implement `api/models.py` — Pydantic request/response models for runs, artifacts, pagination, RFC 7807 problem
- [x] T016 [P] Implement `api/auth.py` — optional AAD JWT validation middleware (controlled by `AUTH_REQUIRED`)

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 — Submit a Run (Priority: P1) MVP

**Goal**: Idempotent `POST /runs` endpoint that creates a run record in Azure SQL

**Independent Test**: `POST /runs` with idempotency key → 201 Created; duplicate key → 200 OK with same `run_id`

### Tests for User Story 1

- [x] T017 [P] [US1] Test idempotent run creation in `tests/test_repo_idempotency.py`
- [x] T018 [P] [US1] Test SQL transient retry in `tests/test_sql_retry.py`
- [x] T019 [P] [US1] Test POST/GET/PATCH flows in `tests/test_api_runs.py`

### Implementation for User Story 1

- [x] T020 [US1] Implement `db/repository.py` — `ensure_idempotency()`, `insert_run_started()` with transient retry wrapper
- [x] T021 [US1] Implement `api/routes_runs.py` — `POST /runs` endpoint with idempotency key handling
- [x] T022 [US1] Add correlationId propagation and structured logging for run creation

**Checkpoint**: `POST /runs` is fully functional and idempotent

---

## Phase 4: User Story 2 — Complete a Run (Priority: P1)

**Goal**: `PATCH /runs/{runId}` to update status, timings, token usage

**Independent Test**: Create a run, PATCH with completion data, verify via GET

### Implementation for User Story 2

- [x] T023 [US2] Implement `update_run_finished()` in `db/repository.py` with status guard (409 on re-complete)
- [x] T024 [US2] Implement `PATCH /runs/{runId}` in `api/routes_runs.py`
- [x] T025 [US2] Add RFC 7807 responses for 404 Not Found and 409 Conflict

**Checkpoint**: Run lifecycle (create → complete) is fully functional

---

## Phase 5: User Story 3 — Register Artifacts (Priority: P2)

**Goal**: `POST /runs/{runId}/artifacts` for batch artifact registration

**Independent Test**: Create and complete a run, POST 3 artifacts, verify persisted

### Implementation for User Story 3

- [x] T026 [US3] Implement `insert_artifacts()` in `db/repository.py`
- [x] T027 [US3] Implement `api/routes_artifacts.py` — `POST /runs/{runId}/artifacts` batch endpoint
- [x] T028 [US3] Add validation for empty artifact list (400) and non-existent run (404)

**Checkpoint**: Artifact registration works for completed runs

---

## Phase 6: User Story 4 — List and Filter Runs (Priority: P2)

**Goal**: `GET /runs` with filters + cursor-based pagination, `GET /runs/{runId}`

**Independent Test**: Create 5 runs with varying statuses, filter by status, verify pagination cursor

### Implementation for User Story 4

- [x] T029 [US4] Implement `get_runs()` and `get_run()` in `db/repository.py` with filter and pagination support
- [x] T030 [US4] Implement `GET /runs` and `GET /runs/{runId}` in `api/routes_runs.py`
- [x] T031 [US4] Include artifacts in single-run GET response

**Checkpoint**: Full CRUD API for runs is operational

---

## Phase 7: User Story 5 — Fan-out Orchestration (Priority: P2)

**Goal**: Durable Functions orchestrator fans out N run messages to Service Bus

**Independent Test**: Trigger fan-out with 5 run IDs, verify 5 messages on Service Bus queue

### Implementation for User Story 5

- [x] T032 [US5] Define Service Bus message schemas in `orchestrator/sb_contracts.py`
- [x] T033 [US5] Implement fan-out orchestrator + activity in `orchestrator/functions/fanout/__init__.py`
- [x] T034 [US5] Add retry policy for Service Bus send failures

**Checkpoint**: Batch processing via orchestration is functional

---

## Phase 8: User Story 6 — DLQ Replay (Priority: P3)

**Goal**: HTTP-triggered function to replay dead-lettered messages

### Implementation for User Story 6

- [x] T035 [US6] Implement DLQ replay in `orchestrator/functions/dlq_replay/__init__.py`
- [x] T036 [US6] Add `max` parameter to limit replay count

**Checkpoint**: Operational recovery tool for dead-lettered messages is available

---

## Phase 9: APIM Gateway Policies

**Purpose**: API Management policies for rate limiting, retry, redaction, and correlation

- [x] T037 [P] Create `apim/policies/rate-limit-quota.xml` — rate limit and quota enforcement
- [x] T038 [P] Create `apim/policies/retry-backoff.xml` — retry with backoff for backend faults
- [x] T039 [P] Create `apim/policies/redaction.xml` — sensitive header redaction
- [x] T040 [P] Create `apim/policies/correlation-id.xml` — correlationId pass-through / generation

---

## Phase 10: Terraform Infrastructure

**Purpose**: IaC modules and environment compositions

### Modules (can be built in parallel)

- [x] T041 [P] Implement `infra/terraform/modules/core_rg/main.tf` — resource group with naming convention
- [x] T042 [P] Implement `infra/terraform/modules/identities/main.tf` — MI for API + Functions, reuse support
- [x] T043 [P] Implement `infra/terraform/modules/networking/main.tf` — VNet, subnets, private endpoints (toggleable)
- [x] T044 [P] Implement `infra/terraform/modules/key_vault/main.tf` — Key Vault + role assignments, reuse support
- [x] T045 [P] Implement `infra/terraform/modules/log_analytics/main.tf` — workspace, reuse support
- [x] T046 [P] Implement `infra/terraform/modules/application_insights/main.tf` — App Insights, reuse support
- [x] T047 [P] Implement `infra/terraform/modules/sql/main.tf` — Azure SQL Server + DB, AAD admin, reuse support
- [x] T048 [P] Implement `infra/terraform/modules/service_bus/main.tf` — namespace + queues + DLQ, reuse support
- [x] T049 [P] Implement `infra/terraform/modules/apim/main.tf` — APIM + product + API import, reuse support
- [x] T050 [P] Implement `infra/terraform/modules/app_host/main.tf` — App Service / Container Apps (switchable via `host_choice`)
- [x] T051 [P] Implement `infra/terraform/modules/functions_host/main.tf` — Azure Functions for Durable Functions
- [x] T052 [P] Implement `infra/terraform/modules/storage/main.tf` — blob storage for artifacts, reuse support

### Environment Compositions

- [x] T053 [P] Create `infra/terraform/envs/dev/` — main.tf, variables.tf, outputs.tf, providers.tf, backend.tf, terraform.tfvars.example
- [x] T054 [P] Create `infra/terraform/envs/test/` — same structure as dev
- [x] T055 [P] Create `infra/terraform/envs/prod/` — same structure as dev

### Remote State Bootstrap

- [x] T056 Create `infra/terraform/global/backend/main.tf` — bootstrap storage account for remote state

### Deploy & Deprovision Scripts

- [x] T057 [P] Create `infra/scripts/deploy.ps1` — PowerShell wrapper: .env → TF_VAR → terraform plan/apply
- [x] T058 [P] Create `infra/scripts/deploy.sh` — Bash wrapper: .env → TF_VAR → terraform plan/apply
- [x] T059 [P] Create `infra/scripts/deprovision.ps1` — safe destroy with reuse protection
- [x] T060 [P] Create `infra/scripts/deprovision.sh` — safe destroy with reuse protection

---

## Phase 11: CI/CD Workflows

**Purpose**: GitHub Actions with OIDC-based Azure authentication

- [x] T061 [P] Create `.github/workflows/ci.yml` — lint (ruff) + type-check (mypy) + test (pytest) + Docker build
- [x] T062 [P] Create `.github/workflows/codeql.yml` — CodeQL security analysis for Python
- [x] T063 [P] Create `.github/workflows/terraform-plan.yml` — OIDC login + init/validate/plan for dev/test matrix
- [x] T064 [P] Create `.github/workflows/terraform-apply.yml` — manual dispatch with environment approvals
- [x] T065 [P] Create `.github/workflows/publish-api.yml` — build/push API container, deploy to App Service or ACA
- [x] T066 [P] Create `.github/workflows/publish-functions.yml` — build/deploy Azure Functions
- [x] T067 [P] Create `.github/workflows/run-migrations.yml` — Alembic upgrade head with OIDC token auth

---

## Phase 12: Environment Configuration

- [x] T068 [P] Create `.env.example` — template with all config variables (no secrets)
- [x] T069 [P] Create `.env_local` — local dev reuse config
- [x] T070 [P] Create `.env_qa` — QA/staging reuse config
- [x] T071 [P] Create `.env_prod` — production reuse config

---

## Phase 13: Documentation

- [x] T072 Create `README.md` — architecture overview, local dev setup, Terraform usage, CI/CD, operational runbook
- [x] T073 Create `PRD.md` — Product Requirements Document for resource reuse feature
