# Research: AWR Platform Baseline

**Date**: 2026-03-02  
**Spec**: [spec.md](spec.md)

## Technology Decisions

### 1. Passwordless SQL Connectivity

**Decision**: Use `DefaultAzureCredential` + ODBC Driver 18 `attrs_before[1256]` token injection.

**Research**:
- Azure SQL supports AAD token-based authentication via the ODBC driver's `SQL_COPT_SS_ACCESS_TOKEN` attribute (code 1256).
- The token must be encoded as UTF-16-LE with a 4-byte length prefix.
- `DefaultAzureCredential` provides a unified credential chain: Managed Identity in Azure, `az login` locally, workload identity in CI/CD.
- No connection string secrets are needed — only server FQDN, database name, and driver name.

**References**:
- [Microsoft: Azure SQL token-based auth with pyodbc](https://learn.microsoft.com/en-us/azure/azure-sql/database/azure-sql-python-quickstart)
- [pyodbc attrs_before documentation](https://github.com/mkleehammer/pyodbc/wiki/Connecting-to-SQL-Server-from-Linux#aad-access-token)

### 2. Transient Fault Handling Strategy

**Decision**: Exponential backoff with full jitter, connection re-open before each retry.

**Research**:
- Azure SQL can return transient errors during failovers, throttling, or network issues.
- Transient SQLState codes: `40613` (database unavailable), `40197` (service error), `08S01` (communication link failure), `40501` (service busy), `49918`/`49919`/`49920` (throttling).
- Full jitter (`random(0, min(cap, base * 2^attempt))`) provides better spread than equal jitter.
- Re-opening the connection before retry is critical because stale connections from a pool may point to a failed endpoint.

**Configuration**: Base delay 500ms, max delay 60s, max retries 6, all configurable via env vars.

### 3. Idempotency Implementation

**Decision**: Application-level idempotency via `idempotency_key` in the database.

**Research**:
- The `engine.Idempotency` table stores `(idempotency_key, run_id, created_at)`.
- On `POST /runs`, the repository checks for an existing key within a database transaction.
- If found, the existing run_id is returned (200 OK). If not, a new run is inserted (201 Created).
- This is simpler and more reliable than HTTP-level idempotency caches (no TTL concerns).

### 4. API Error Model

**Decision**: RFC 7807 `application/problem+json` for all error responses.

**Research**:
- RFC 7807 provides a standardized error format with `type`, `title`, `status`, `detail`, and `instance` fields.
- FastAPI's default error model is non-standard. Custom exception handlers map to RFC 7807.
- The `instance` field carries the `correlationId` for traceability.

### 5. Durable Functions for Orchestration

**Decision**: Azure Durable Functions with fan-out/fan-in pattern.

**Research**:
- Fan-out/fan-in is a first-class pattern in Durable Functions.
- The orchestrator creates N activity invocations, each sending a message to Service Bus.
- Durable Functions handle retries, state persistence, and checkpointing automatically.
- DLQ replay is a separate HTTP-triggered function that reads from `$deadletterqueue` and re-enqueues.

### 6. Infrastructure as Code — Terraform with Resource Reuse

**Decision**: Terraform modules with conditional `count` for create-or-reuse pattern.

**Research**:
- Enterprise environments often have shared resources (Log Analytics, APIM, SQL) managed by a central team.
- The `reuse` boolean + `data` source pattern allows modules to reference existing resources without provisioning.
- Module outputs are unified regardless of create vs. reuse, so downstream modules need no changes.
- 8 resource types support reuse: storage, app insights, service bus, SQL, key vault, APIM, log analytics, identities.

### 7. Hosting Model

**Decision**: App Service for Containers (default) with Azure Container Apps as switchable alternative.

**Research**:
- Both support Linux containers with Managed Identity and App Insights integration.
- App Service is simpler for single-container workloads and has built-in deployment slots.
- Container Apps (ACA) offers Dapr integration and KEDA-based scaling for more complex scenarios.
- The `host_choice` variable in the `app_host` module controls which is provisioned.
