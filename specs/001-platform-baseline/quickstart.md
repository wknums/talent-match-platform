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
