# Quickstart: AWR Platform

## Prerequisites

- Python 3.11+
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
- Azure CLI (`az login` for local credential chain)
- Docker (optional, for containerized runs)
- Terraform >= 1.6 (for infrastructure)
- Git

## 1. Clone and Setup

```bash
git clone <repo-url> && cd awr-platform
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -e ".[dev]"
```

## 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Azure SQL server, Service Bus namespace, etc.
```

Key variables:
- `SQL_SERVER` — Azure SQL server FQDN
- `SQL_DATABASE` — Database name
- `SB_NAMESPACE` — Service Bus namespace
- `AUTH_REQUIRED` — Set to `true` to enforce AAD JWT

## 3. Run the API Locally

```bash
# Ensure you're logged in to Azure for credential chain
az login

# Start the API
uvicorn api.main:app --reload --port 8000
```

## 4. Test It

```bash
# Create a run
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key": "test-001"}'

# List runs
curl http://localhost:8000/runs

# Run tests
pytest tests/ -v
```

## 5. Run with Docker

```bash
docker build -t awr-platform-api .
docker run -p 8000:8000 --env-file .env awr-platform-api
```

## 5b. Run the Durable Functions locally

The orchestrator (`fanout`) and DLQ replay live in the same repo as a Functions v2
app. The host files at the repo root (`function_app.py`, `host.json`,
`requirements.txt`, `local.settings.json`) make it deployable.

Prereqs:
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) running for `AzureWebJobsStorage=UseDevelopmentStorage=true`

```bash
# Install runtime deps into the same venv
pip install -r requirements.txt

# Start the Functions host
func start

# Trigger the fan-out orchestrator
curl -X POST http://localhost:7071/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"runs":[{"run_id":"<uuid>","engine":"demo"}]}'

# Replay up to 5 dead-lettered messages
curl -X POST "http://localhost:7071/api/dlq-replay?max=5"
```

Deploy to the Function App provisioned by `infra/terraform/modules/functions_host`:

```bash
func azure functionapp publish <function_app_name>
```

## 6. Deploy Infrastructure

```bash
cd infra/terraform/envs/dev
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars

terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## 7. Run Migrations

```bash
# Locally (uses az login credentials)
alembic upgrade head
```
