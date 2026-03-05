# AWR Platform

> Platform layer – REST API, durable orchestration, Azure SQL persistence, APIM gateway, and Terraform infrastructure.

---

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│   Clients   │────▶│  Azure APIM  │────▶│  FastAPI (API)  │
└─────────────┘     └──────────────┘     └───────┬────────┘
                                                  │
                         ┌────────────────────────┼───────────────┐
                         │                        │               │
                  ┌──────▼──────┐         ┌──────▼──────┐ ┌──────▼──────┐
                  │  Azure SQL  │         │ Service Bus │ │   Storage   │
                  │ (RunRecord, │         │  (Queues)   │ │ (Artifacts) │
                  │  Artifact)  │         └──────┬──────┘ └─────────────┘
                  └─────────────┘                │
                                          ┌──────▼──────┐
                                          │  Durable    │
                                          │  Functions  │
                                          │ (Fan-out)   │
                                          └──────┬──────┘
                                                 │
                                          ┌──────▼──────┐
                                          │   Engine    │
                                          │  Workers    │
                                          │ (other repo)│
                                          └─────────────┘
```

### Components

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API** | FastAPI + Uvicorn | REST endpoints for runs & artifacts |
| **Orchestrator** | Azure Durable Functions | Fan-out/fan-in, DLQ replay |
| **Persistence** | Azure SQL + pyodbc | RunRecord, Artifact, Idempotency tables |
| **Gateway** | Azure API Management | Rate limiting, retry, redaction, correlation-id |
| **Auth** | Microsoft Entra (AAD) JWT | Optional admin endpoint protection |
| **Identity** | Managed Identity | Passwordless access to SQL, Service Bus, Storage, Key Vault |
| **Observability** | OpenTelemetry + App Insights | Tracing, structured JSON logs, metrics |
| **IaC** | Terraform >= 1.6 | Modules + env compositions (dev/test/prod) |

---

## Repository Structure

```
awr-platform/
├── api/                     # FastAPI application
├── orchestrator/            # Azure Durable Functions
│   └── functions/
│       ├── fanout/          # Fan-out orchestrator + activity
│       └── dlq_replay/      # Dead-letter queue replay
├── db/                      # Database layer
│   ├── connection.py        # pyodbc + Entra token (attrs_before[1256])
│   ├── repository.py        # CRUD operations
│   └── migrations/          # Alembic (env.py + versions/)
├── runtime/                 # Cross-cutting utilities
│   ├── config.py            # pydantic-settings
│   ├── transient.py         # Retry with exponential backoff
│   ├── telemetry.py         # OpenTelemetry setup
│   └── errors.py            # RFC 7807 problem+json
├── apim/                    # APIM policies (XML)
├── infra/terraform/
│   ├── global/backend/      # Bootstrap remote state
│   ├── modules/             # Reusable Terraform modules
│   └── envs/{dev,test,prod} # Environment compositions
├── tests/                   # Pytest test suite
├── .github/workflows/       # CI/CD pipelines
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Local Development

### Prerequisites

- Python 3.11+
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
- Azure CLI (`az login` for DefaultAzureCredential)
- Docker (optional, for containerised runs)
- Terraform >= 1.6

### Setup

```bash
# Clone
git clone <repo-url> && cd awr-platform

# Virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Install (with dev extras)
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env
# Edit .env with your Azure SQL server, Service Bus namespace, etc.
```

### Run the API locally

```bash
uvicorn api.main:app --reload --port 8000
```

### Run with Docker

```bash
docker build -t awr-platform-api .
docker run -p 8000:8000 --env-file .env awr-platform-api
```

### Run tests

```bash
pytest tests/ -v
```

---

## Terraform – Infrastructure as Code

### Bootstrap Remote State (one-time)

```bash
cd infra/terraform/global/backend
terraform init
terraform apply
# Note the outputs: storage_account_name, container_name
# Update backend.tf in each env folder with those values.
```

### Deploy an Environment

```bash
cd infra/terraform/envs/dev

# Copy and fill in variables
cp terraform.tfvars.example terraform.tfvars

terraform init
terraform validate
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

### Destroy

```bash
terraform destroy -var-file=terraform.tfvars
```

### Key Toggles

| Variable | Values | Description |
|----------|--------|-------------|
| `host_choice` | `webapp_container` / `container_apps` | API hosting model |
| `use_private_endpoints` | `true` / `false` | Enable VNet + private endpoints |
| `enable_artifact_storage` | `true` / `false` | Provision blob storage for artifacts |
| `sql_sku` | e.g. `S0`, `GP_S_Gen5_2` | SQL Database SKU |
| `apim_sku` | e.g. `Developer_1`, `Standard_1` | APIM tier |

---

## CI/CD – GitHub Actions with OIDC

All workflows use **OIDC-based federation** to Azure — no client secrets stored in GitHub.

### Setup OIDC Federation

1. Create an Azure AD App Registration for GitHub Actions.
2. Add a Federated Credential for your repo (`repo:<org>/<repo>:ref:refs/heads/main` and `pull_request`).
3. Set GitHub repository secrets:
   - `AZURE_CLIENT_ID` — App registration client ID
   - `AZURE_TENANT_ID` — Azure AD tenant ID
   - `AZURE_SUBSCRIPTION_ID` — Target subscription
4. Create GitHub Environments (`dev`, `test`, `prod`) with required reviewers for `prod`.

### Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push/PR to main | Lint, type-check, test, Docker build |
| `codeql.yml` | Push/PR + weekly | CodeQL security analysis |
| `terraform-plan.yml` | PR/push (infra changes) | Plan for dev/test matrix |
| `terraform-apply.yml` | Manual dispatch | Apply with environment approvals |
| `publish-api.yml` | Push (api changes) / manual | Build & deploy API container |
| `publish-functions.yml` | Push (orchestrator changes) / manual | Deploy Azure Functions |
| `run-migrations.yml` | After terraform-apply / manual | Alembic upgrade head |

---

## Alembic Migrations

### Create a new migration

```bash
alembic revision -m "add_some_column"
# Edit the generated file in db/migrations/versions/
```

### Apply migrations

```bash
# Locally (uses DefaultAzureCredential via az login)
alembic upgrade head

# In CI: the run-migrations.yml workflow handles this automatically
# after terraform-apply, using OIDC → federated token → pyodbc attrs_before[1256].
```

### How token-based auth works

The Alembic `env.py` and `db/connection.py` both:
1. Call `DefaultAzureCredential().get_token("https://database.windows.net/.default")`
2. Encode the token as UTF-16-LE with a length prefix
3. Pass it via `pyodbc.connect(..., attrs_before={1256: token_struct})`

No username or password is ever stored or transmitted.

---

## Operational Runbook

### DLQ Replay

Dead-lettered messages accumulate when engine workers fail repeatedly. To replay:

```bash
# Via the DLQ replay Azure Function (HTTP trigger):
curl -X POST "https://func-awr-dev.azurewebsites.net/api/dlq-replay?max=50"

# Or manually via Azure CLI:
az servicebus queue show --namespace-name sb-awr-dev --name engine-runs \
  --query "countDetails.deadLetterMessageCount"
```

### Scaling Knobs

| Resource | Setting | Where |
|----------|---------|-------|
| API throughput | App Service Plan SKU / ACA CPU+memory | `app_service_sku` or ACA template |
| SQL compute | DTU or vCore SKU | `sql_sku` variable |
| Service Bus | Standard → Premium (partitioning, larger messages) | `service_bus_sku` |
| Functions | Consumption → Premium (VNet, always-ready) | `functions_sku` |
| APIM | Developer → Standard/Premium | `apim_sku` |

### Transient Retry Policy

SQL operations use exponential backoff with full jitter:
- Base delay: 500 ms (doubles each attempt)
- Max delay: 60 s
- Max retries: 6
- **Connection is re-opened before each retry** (stale connections are discarded)
- Only transient SQLState codes trigger retries (e.g., `40613`, `40197`, `08S01`)

Configure via environment variables: `SQL_MAX_RETRIES`, `SQL_BASE_DELAY_MS`, `SQL_MAX_DELAY_MS`.

---

## Security

- **No credentials in code** — all Azure access uses Managed Identity (or `az login` locally).
- **Key Vault** stores any configuration secrets; accessed via MI.
- **AAD JWT** enforcement is optional (`AUTH_REQUIRED=true`).
- **APIM** provides rate limiting, subscription keys, and header redaction.
- **Private endpoints** can be toggled for SQL and APIM in production.

---

## License

Internal / proprietary. See your organization's licensing policy.
