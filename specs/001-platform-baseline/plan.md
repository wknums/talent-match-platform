# Implementation Plan: AWR Platform Baseline

**Branch**: `001-platform-baseline` | **Date**: 2026-03-02 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/001-platform-baseline/spec.md`

## Summary

Build the complete AWR Platform layer: a FastAPI REST API with idempotent run lifecycle management, Durable Functions orchestration for fan-out/fan-in, Azure SQL persistence with Entra-based passwordless auth, APIM gateway policies, and Terraform IaC for all infrastructure across dev/test/prod environments.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: FastAPI, Uvicorn, Pydantic v2, pydantic-settings, pyodbc, azure-identity, azure-servicebus, azure-functions-durable, OpenTelemetry, Alembic, python-jose  
**Storage**: Azure SQL (pyodbc + ODBC Driver 18), Azure Blob Storage (artifacts), Azure Service Bus (queues)  
**Testing**: pytest, pytest-asyncio, pytest-cov, respx (HTTP mocking)  
**Target Platform**: Azure (App Service for Containers or Azure Container Apps)  
**Project Type**: Web service (REST API) + serverless functions (orchestration)  
**Performance Goals**: 500ms p95 for `POST /runs`, 6 retries max for transient SQL faults  
**Constraints**: Zero secrets in code, Entra-only auth, no SAS tokens, Terraform-only IaC  
**Scale/Scope**: Multi-environment (dev/test/prod), multi-region capable, enterprise resource reuse support

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Zero-Trust Identity | PASS | All Azure access via DefaultAzureCredential + Managed Identity |
| II. No Secrets in Code | PASS | Key Vault for secrets, env vars for config, variables in Terraform |
| III. Infrastructure as Terraform | PASS | 12 modules + 3 env compositions, remote state in Azure Storage |
| IV. Test-First Development | PASS | pytest suite with API, idempotency, retry, and orchestration tests |
| V. Resilient by Default | PASS | Exponential backoff + jitter, connection re-open, DLQ replay |
| VI. Observability Everywhere | PASS | OpenTelemetry + App Insights, correlationId middleware |
| VII. Simplicity & YAGNI | PASS | Minimal schema, no over-abstraction, feature-driven scope |

## Project Structure

### Documentation (this feature)

```text
specs/001-platform-baseline/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Technology research and decisions
├── data-model.md        # Entity definitions and schema
├── contracts/           # API contracts (OpenAPI snippets)
└── tasks.md             # Task breakdown
```

### Source Code (repository root)

```text
awr-platform/
├── api/                          # FastAPI application
│   ├── __init__.py
│   ├── main.py                   # App factory, middleware, lifespan
│   ├── routes_runs.py            # POST/GET/PATCH /runs endpoints
│   ├── routes_artifacts.py       # POST /runs/{runId}/artifacts
│   ├── models.py                 # Pydantic request/response models + RFC 7807
│   ├── auth.py                   # AAD JWT validation (optional)
│   └── deps.py                   # correlationId, pagination, DI helpers
├── orchestrator/                 # Azure Durable Functions (Blueprints)
│   ├── __init__.py
│   ├── sb_contracts.py           # Service Bus message schemas
│   └── functions/
│       ├── fanout/__init__.py    # Fan-out orchestrator + activity (Blueprint)
│       └── dlq_replay/__init__.py # DLQ replay HTTP trigger (Blueprint)
├── function_app.py               # Functions v2 host entry — registers Blueprints
├── host.json                     # Functions host config (extension bundle, Durable hub)
├── requirements.txt              # Functions-host runtime dependencies
├── local.settings.json           # Local Functions runtime settings
├── .funcignore                   # Excludes from `func` deployment package
├── db/                           # Database layer
│   ├── __init__.py
│   ├── connection.py             # pyodbc + Entra token (attrs_before[1256])
│   ├── repository.py             # CRUD: insert/update/get runs, artifacts, idempotency
│   └── migrations/
│       ├── env.py                # Alembic environment with token auth
│       ├── script.py.mako
│       └── versions/
│           └── 001_initial_schema.py
├── runtime/                      # Cross-cutting utilities
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings (env vars only)
│   ├── transient.py              # Retry with exponential backoff + jitter
│   ├── telemetry.py              # OpenTelemetry init + JSON logs
│   └── errors.py                 # RFC 7807 problem+json helpers
├── apim/                         # APIM gateway policies
│   ├── apis/                     # OpenAPI import definitions
│   └── policies/                 # XML policies
│       ├── correlation-id.xml
│       ├── rate-limit-quota.xml
│       ├── redaction.xml
│       └── retry-backoff.xml
├── infra/terraform/              # Infrastructure as Code
│   ├── global/backend/           # Bootstrap remote state
│   ├── modules/                  # 12 reusable modules
│   │   ├── core_rg/
│   │   ├── networking/
│   │   ├── identities/
│   │   ├── key_vault/
│   │   ├── log_analytics/
│   │   ├── application_insights/
│   │   ├── sql/
│   │   ├── service_bus/
│   │   ├── apim/
│   │   ├── app_host/
│   │   ├── functions_host/
│   │   └── storage/
│   └── envs/{dev,test,prod}/     # Environment compositions
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── providers.tf
│       ├── backend.tf
│       └── terraform.tfvars.example
├── tests/                        # Pytest test suite
│   ├── test_api_runs.py
│   ├── test_execute_with_retry.py
│   ├── test_repo_idempotency.py
│   └── test_sql_retry.py
├── .github/workflows/            # CI/CD (OIDC-based)
│   ├── ci.yml
│   ├── codeql.yml
│   ├── terraform-plan.yml
│   ├── terraform-apply.yml
│   ├── publish-api.yml
│   ├── publish-functions.yml
│   └── run-migrations.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
└── README.md
```

**Structure Decision**: Single-repo monolith with clear layer boundaries (api/, orchestrator/, db/, runtime/). Infrastructure lives alongside application code for atomic commits across code + infra changes.

## Architecture Decisions

### AD-1: Passwordless SQL Connectivity
Use `DefaultAzureCredential.get_token("https://database.windows.net/.default")` → encode as UTF-16-LE with length prefix → pass via `pyodbc.connect(..., attrs_before={1256: token_struct})`. No connection string secrets.

### AD-2: Transient Fault Handling
Exponential backoff with full jitter: base delay 500ms, doubles each attempt, max 60s, max 6 retries. Connection is explicitly closed and re-opened before each retry to discard stale pooled connections. Only specific transient SQLState codes (`40613`, `40197`, `08S01`, etc.) trigger retries.

### AD-3: Idempotency Strategy
`POST /runs` accepts an `idempotency_key` header/body field. The repository layer does a check-then-insert within a transaction. If the key exists, the existing record is returned. This ensures at-most-once semantics for run creation.

### AD-4: Resource Reuse Pattern
Each Terraform module supports a `reuse` boolean, `existing_name`, and `existing_resource_group` variables. When `reuse=true`, a `data` source looks up the existing resource; when `false`, a `resource` block creates it. Outputs are unified regardless.

### AD-5: API Hosting Flexibility
The `app_host` Terraform module supports two hosting models via `host_choice` variable: `webapp_container` (App Service for Containers) and `container_apps` (Azure Container Apps). Both configurations expose the FastAPI app with Managed Identity and App Insights.

## Implementation Phases

### Phase 0: Foundation & Research
- Validate technology choices (pyodbc token auth, Durable Functions SDK, OpenTelemetry instrumentation)
- Confirm ODBC Driver 18 token injection works with Azure SQL
- Verify Terraform module patterns for resource reuse

### Phase 1: Core Application
- FastAPI app factory with middleware (correlationId, error handling)
- Pydantic models for all request/response types
- Database connection with Entra token auth
- Repository layer with CRUD operations
- Alembic migrations for initial schema
- Transient retry with exponential backoff

### Phase 2: API Endpoints & Orchestration
- Run lifecycle endpoints (POST/PATCH/GET)
- Artifact batch registration endpoint
- Durable Functions fan-out orchestrator
- DLQ replay function
- Service Bus message contracts

### Phase 3: Infrastructure
- Terraform modules for all 12 resource types
- Environment compositions for dev/test/prod
- Resource reuse support across all modules
- Deploy and deprovision scripts
- APIM gateway policies

### Phase 4: CI/CD & Observability
- GitHub Actions workflows (7 workflows)
- OIDC federation setup
- OpenTelemetry instrumentation
- Application Insights integration
- Alembic migration workflow

## Complexity Tracking

No constitution violations detected. All design decisions align with core principles.
