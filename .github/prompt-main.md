You are scaffolding the “awr-platform” repository (Platform layer) using PYTHON for application code and TERRAFORM ONLY for infrastructure.

========================================
ARCHITECTURE (what to build)
========================================
The Platform repo owns:
- REST API (FastAPI) that exposes:
  - POST /runs (idempotent start)
  - PATCH /runs/{runId} (finish: timings + token usage + status)
  - POST /runs/{runId}/artifacts (batch register)
  - GET /runs (with filters + paging) and GET /runs/{runId}
  - RFC 7807 error model, correlationId middleware, optional AAD JWT enforcement for admin endpoints.
- Orchestration with Azure Functions Durable Functions:
  - Fan-out/fan-in to enqueue N run messages to Service Bus for Engine workers (in a separate repo).
  - DLQ replay utility.
- Persistence in Azure SQL:
  - Minimal, engine-agnostic schema: engine.RunRecord, engine.Artifact, engine.Idempotency (optional).
  - Alembic migrations, transactional DDL.
  - Passwordless connectivity using Microsoft Entra (DefaultAzureCredential) → ODBC Driver 18 access-token (attrs_before[1256]).
  - Transient fault handling with exponential backoff; re-open connection before retrying commands.
- Security & Config:
  - Microsoft Entra JWT for admin APIs (optional).
  - Managed Identity for all Azure calls (SQL, Service Bus, Storage, APIM).
  - Key Vault for configuration secrets (no credentials in code).
- Observability:
  - OpenTelemetry tracing/logging/metrics, correlationId propagation; App Insights/Log Analytics.
- API Management (APIM):
  - Product + APIs + Policies (rate limit/quota, retry/backoff, redaction, correlation pass-through).
- Infrastructure as Code:
  - **Terraform ONLY**: core modules + environment compositions (dev/test/prod).
  - Remote state in Azure Storage (backend), per-env workspaces; OIDC-based GitHub Actions for `plan`/`apply`.

========================================
REPO LAYOUT (generate these folders/files)
========================================
awr-platform/
  api/
    __init__.py
    main.py
    routes_runs.py
    routes_artifacts.py
    models.py            # Pydantic requests/responses + RFC 7807 problem
    auth.py              # optional AAD JWT validation
    deps.py              # correlation-id, pagination, DI helpers
  orchestrator/
    __init__.py
    functions/
      fanout/__init__.py     # Durable orchestrator + activity
      dlq_replay/__init__.py
    sb_contracts.py          # message schemas
  db/
    __init__.py
    connection.py            # pyodbc + DefaultAzureCredential; ODBC 18; attrs_before[1256]
    repository.py            # ensure_idempotency, insert_run_started, update_run_finished, insert_artifacts, get_run(s)
    migrations/              # Alembic: env.py + versions/
  runtime/
    config.py                # pydantic-settings (env only)
    transient.py             # retry policies (SQL + HTTP)
    telemetry.py             # OpenTelemetry init + JSON logs
    errors.py                # problem+json helpers
  apim/
    apis/                    # OpenAPI import or policy-bound definitions
    policies/                # XML policies (rate-limit, retry, redaction, corr-id)
  infra/
    terraform/
      global/
        backend/             # (optional) bootstrap for remote state (RG + SA + container)
      modules/
        core_rg/
        networking/          # vnet, subnets, private endpoints (optional, parameterized)
        key_vault/
        log_analytics/
        application_insights/
        sql/
        service_bus/
        apim/
        app_host/            # choose one via variable:
                            #  - webapp_container (App Service for Containers)
                            #  - container_apps (ACA)
        functions_host/      # Azure Functions (Consumption/Premium/Container)
        identities/          # user-assigned/system-assigned MI and role assignments
        storage/             # blob containers for artifacts, if needed
      envs/
        dev/
          main.tf
          variables.tf
          outputs.tf
          providers.tf
          backend.tf         # remote state config (azurerm)
          terraform.tfvars.example
        test/
          (same structure)
        prod/
          (same structure)
  tests/
    test_api_runs.py
    test_repo_idempotency.py
    test_sql_retry.py
  .github/
    workflows/
      ci.yml                 # lint/type-check/tests/build containers
      codeql.yml
      terraform-plan.yml     # OIDC login + terraform init/validate/plan (per env)
      terraform-apply.yml    # manual/approval gated apply (per env)
      publish-api.yml        # build/push API container & deploy
      publish-functions.yml  # build/push Functions & deploy
      run-migrations.yml     # Alembic upgrade head (post-apply), MI auth
  README.md

========================================
APPLICATION IMPLEMENTATION (Python)
========================================
- Use Python 3.11.
- FastAPI + Uvicorn for API.
- Alembic for migrations; Pydantic v2 for models/settings.
- pyodbc + ODBC 18 → pass Entra token via attrs_before[1256].
- DefaultAzureCredential for MI & local dev (az login).
- Transient errors: implement exponential backoff + jitter; re-open connection before retrying command.
- OpenTelemetry tracing/logging with correlationId.

========================================
TERRAFORM ONLY — INFRA REQUIREMENTS
========================================
Tooling & Structure:
- Use Terraform >= 1.6; providers: `azurerm`, `azuread`, `random`, `time`, `null`.
- Enable azurerm features block; support for OIDC-based auth from GitHub Actions (no secrets).
- Use remote state in Azure Storage:
  - One RG + Storage Account + blob container (e.g., “tfstate”).
  - Separate workspaces or env folders (dev/test/prod). Each env has its own backend config and state key.
- Provide `variables.tf` with sensible defaults and typed inputs; supply `terraform.tfvars.example` per env.

Core Modules (infra/terraform/modules):
1) core_rg: resource groups naming convention.
2) identities: create system-assigned and/or user-assigned Managed Identities; output principal IDs.
3) networking (optional): vnet, subnets, private DNS zones, private endpoints for SQL/APIM if needed; toggled via variables.
4) key_vault: KV + access policies/role assignments for Platform identities.
5) log_analytics + application_insights: workspace + Insights; wire to API/Functions.
6) sql: Azure SQL Server + Database + optional private endpoint/firewall; outputs:
   - server fqdn, database name
   - AAD admin object id (parameterized)
7) service_bus: namespace + queues (main + DLQ) + role assignments for the orchestrator/engine identities.
8) apim: API Management (Developer or higher) + product + API import (OpenAPI) + policy attachments; outputs base URL.
9) app_host:
   - Option A (default): App Service for Containers (Linux Plan) for the FastAPI app.
   - Option B (switchable): Azure Container Apps environment + ACA app for API (ingress managed).
   - Expose env vars, identity, and App Insights.
10) functions_host: Azure Functions (Consumption or Premium or Container) for Durable Functions app; connect to Service Bus & Insights; MI enabled.
11) storage (optional): blob account/containers for artifacts; role assignments for the engine/platform MIs.

Environment Compositions (infra/terraform/envs/{dev|test|prod}):
- Bring modules together with consistent naming & tags.
- Variables to toggle:
  - host_choice = "webapp_container" | "container_apps"
  - use_private_endpoints = true/false
  - sku sizes per env (APIM, Plan/ACA, SQL compute/storage)
  - service bus scaling parameters, queues, DLQ names
- Outputs:
  - apim_base_url, api_host_url, functions_name, sql_server_fqdn, sql_db_name, service_bus_namespace, identities, insights connection strings.

Remote State:
- `backend.tf` in each env folder using azurerm backend (resource_group_name, storage_account_name, container_name, key).
- Document bootstrap of the backend once (global/backend), or assume it exists.

Role Assignments:
- Grant the Platform API/Functions MIs:
  - SQL DB access via AAD (document how to add as users; or script with post-deploy).
  - Service Bus Data Sender/Receiver roles as appropriate.
  - Key Vault reader/secret user where needed.
  - Storage Blob Data Contributor for artifact containers (if used).

========================================
CI/CD (GitHub Actions with OIDC)
========================================
Workflows to create:
1) ci.yml
   - Setup Python 3.11
   - Install deps; ruff + mypy; pytest; build API image (no push) to ensure Dockerfile works.

2) codeql.yml
   - Enable CodeQL for Python.

3) terraform-plan.yml
   - On PR and push to main (changes under infra/terraform/**)
   - For matrix envs (dev/test):
     - azure/login with OIDC
     - hashicorp/setup-terraform
     - terraform init (backend from backend.tf)
     - terraform validate & fmt -check
     - terraform plan -var-file=terraform.tfvars (store plan as artifact)
   - Post comment with plan summary.

4) terraform-apply.yml
   - On manual dispatch or on tag, requires environment approvals.
   - Same steps as plan but run `terraform apply` with saved plan.
   - Use GitHub Environments to protect dev/test/prod.

5) publish-api.yml
   - Build & push API container (GHCR/ACR).
   - If using App Service for Containers: deploy via az CLI or Terraform outputs (slot optional).
   - If using ACA: update container image on the Container App resource.

6) publish-functions.yml
   - Build and deploy Azure Functions package/container (Consumption/Premium/Container based on module).
   - Ensure env vars and MI are set.

7) run-migrations.yml
   - After terraform-apply in an environment:
     - Acquire token with DefaultAzureCredential on runner (azure/login OIDC → federated workload identity).
     - Run Alembic `upgrade head` using pyodbc + token; connection string without username/password; attrs_before[1256].
     - Idempotent and safe to re-run.

========================================
CONFIGURATION (env)
========================================
- AUTH_REQUIRED=false
- AAD_ISSUER, AAD_AUDIENCE (optional for admin endpoints)
- SQL_*: SQL_SERVER, SQL_DATABASE, SQL_ODBC_DRIVER="ODBC Driver 18 for SQL Server"
- Timeouts/retries: SQL_CONNECTION_TIMEOUT=30, SQL_COMMAND_TIMEOUT=60, SQL_MAX_RETRIES=6, SQL_BASE_DELAY_MS=500, SQL_MAX_DELAY_MS=60000
- SB_NAMESPACE, SB_QUEUE, SB_DLQ
- OTEL_EXPORTER_OTLP_ENDPOINT
- APIM config env vars for API import/policies (module inputs)

========================================
TESTS
========================================
- test_api_runs: POST/GET/patch flows; idempotency semantics.
- test_repo_idempotency: double insert with same idempotencyKey returns the same runId.
- test_sql_retry: simulate transient SQL error on first call then succeed (mock).

========================================
README
========================================
Document:
- Architecture overview.
- Local dev (API/Functions), Docker workflows.
- How to bootstrap remote state and run Terraform per environment (init/plan/apply/destroy).
- How OIDC-based federation to Azure is used for CI/CD (no secrets).
- Alembic usage and `run-migrations` workflow.
- Operational runbook: DLQ replay, scaling knobs, transient retry policy.

Generate all files now with clean, typed Python and Terraform code, docstrings, and TODOs where domain rules are required. Avoid hardcoding secrets. Use Managed Identity and environment variables only.