# AWR Platform

> Implements the `/assess/batch` platform contract for the AWR CV-matching
> system. FastAPI front-end + Azure Durable Functions fan-out to the engine.
> ℹ️ **The original `/runs` + `/artifacts` design (spec 001) was never
> deployed and has been replaced.** See
> [`specs/002-platform-mode-shift/`](specs/002-platform-mode-shift/spec.md)
> for the current contract.
> Start here for the current operator workflow:
> [`specs/002-platform-mode-shift/quickstart.md`](specs/002-platform-mode-shift/quickstart.md)
> and [`docs/application-tracing.md`](docs/application-tracing.md).

---

## Documentation Map

- [specs/002-platform-mode-shift/quickstart.md](specs/002-platform-mode-shift/quickstart.md) — current setup and request flow
- [docs/platform-features.md](docs/platform-features.md) — implemented features, runtime settings, and Azure usage
- [docs/application-tracing.md](docs/application-tracing.md) — identifiers, lineage, fallback, and operator tracing
- [docs/testing.md](docs/testing.md) — test suites, commands, and validation workflow

## Architecture Overview

```text
┌─────────────┐    ┌──────────────┐    ┌────────────────┐    ┌───────────────────┐
│   Clients   │───▶│  Azure APIM  │───▶│  FastAPI (API) │───▶│  Functions host   │
└─────────────┘    └──────────────┘    └────────────────┘    │ (Durable + SB I/O)│
                                                              └────────┬──────────┘
                                                                       │
                                             enqueue RunMessage        │ raise run-{id}
                                                              ┌────────▼──────────┐
                                                              │   Service Bus     │
                                                              │ engine-runs/results│
                                                              └────────┬──────────┘
                                                                       │
                                                              ┌────────▼──────────┐
                                                              │   Engine workers  │
                                                              │    (other repo)   │
                                                              └───────────────────┘

Blob storage (MI auth):
- `cv-uploads/` for source documents and engine artifacts
- `batch-results/` for run-index state and `batches/{batchId}/result.json`

Optional live projection:
- Azure SignalR publish via managed identity or local/dev connection string fallback
```

### Components

| Layer | Technology | Purpose |
| ----- | ---------- | ------- |
| **API** | FastAPI + Uvicorn | `POST /assess/batch`, `GET /assess/batch/{id}/status`, `POST /assess/batch/{id}/cancel` |
| **Orchestrator** | Azure Durable Functions | Fan-out, progress state, result intake, aggregation, blob persistence |
| **Dispatch transport** | Azure Service Bus | `engine-runs` dispatch and `engine-results` callbacks |
| **Persistence** | Durable Task Hub + Blob Storage | Durable state, run-index blobs, and terminal result materialization |
| **Storage** | Azure Blob Storage | `cv-uploads/`, `run-index/`, `result-delivery/`, `batches/{batchId}/result.json` |
| **Live progress** | Azure SignalR (optional) | Non-authoritative progress events with polling fallback |
| **Gateway** | Azure API Management | Rate limiting, retry, redaction, correlation-id |
| **Auth** | Microsoft Entra (AAD) JWT | Bearer token validation on submit + cancel |
| **Identity** | Managed Identity | Passwordless access to Storage, Service Bus, Functions, and SignalR REST publish |
| **Observability** | OpenTelemetry + App Insights | Tracing, structured logs, metrics |
| **IaC** | Terraform >= 1.6 | Modules + env compositions (dev/test/prod) |

---

## Feature Summary

- Queue-worker platform contract with idempotent `batchId` / `Idempotency-Key` enforcement.
- Durable fan-out over `(applicationId × runIndex)` with explicit batch, application, and run progress.
- Dual result-intake paths: Service Bus trigger and HTTP `PATCH /runs/{runId}`.
- Blob-backed lineage recovery using `run-index/{runId}.json` and completed handoff blobs.
- Optional Azure SignalR live projection with managed-identity publish in Azure and polling fallback.
- Entra JWT validation for protected API routes.
- Terraform-managed Functions, Service Bus, storage retention, and optional SignalR infrastructure.

## Repository Structure

```text
awr-platform/
├── api/                     # FastAPI application
│   ├── main.py
│   ├── routes_assess.py     # /assess/batch + /status + /cancel
│   ├── durable_client.py    # httpx wrapper for Functions host
│   ├── models.py            # Pydantic wire models
│   ├── auth.py              # AAD JWT dep
│   └── deps.py              # correlation-id, pagination
├── orchestrator/            # Azure Durable Functions
│   ├── engine_contracts.py
│   ├── sb_contracts.py      # Service Bus wire contracts
│   └── functions/
│       ├── fanout/          # batch orchestrator + aggregation + projection
│       ├── result_intake/   # SB trigger + PATCH /runs/{runId}
│       └── dlq_replay/      # operational replay handlers
├── runtime/                 # Cross-cutting utilities
│   ├── config.py            # pydantic-settings
│   ├── telemetry.py         # OpenTelemetry setup
│   ├── events.py            # live progress event payloads + SignalR publish
│   ├── aggregation/         # shared aggregation profiles and reducers
│   └── errors.py            # RFC 7807 problem+json
├── apim/                    # APIM policies (XML)
├── docs/                    # operator + usage + testing docs
├── infra/terraform/
│   ├── global/backend/      # Bootstrap remote state
│   ├── modules/             # Reusable Terraform modules
│   └── envs/{dev,test,prod} # Environment compositions
├── tests/                   # Pytest test suite
├── .github/workflows/       # workflow definitions (currently empty)
├── Dockerfile
├── function_app.py          # Functions host entry
├── host.json
├── pyproject.toml
└── README.md
```

---

## Local Development

### Prerequisites

- Python 3.11+
- Azure CLI (`az login` for DefaultAzureCredential)
- Azure Functions Core Tools v4 (for the Functions host)
- Docker (optional, for containerised API runs)
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
# Edit .env with FUNCTIONS_HOST_URL, SB_NAMESPACE, BLOB_ACCOUNT, and optional SignalR settings.
```

### Run locally (two processes)

```bash
# Terminal 1 – Functions host (Durable orchestrator + activities)
func start

# Terminal 2 – FastAPI
uvicorn api.main:app --reload --port 8000
```

For the end-to-end local/dev flow, request examples, and live-progress notes,
use [specs/002-platform-mode-shift/quickstart.md](specs/002-platform-mode-shift/quickstart.md).

### Run with Docker

```bash
docker build -t awr-platform-api .
docker run -p 8000:8000 --env-file .env awr-platform-api
```

### Run tests

```bash
python -m pytest tests -v
```

Use the editable install from `pip install -e ".[dev]"` so the repo packages,
`pytest-asyncio`, and the async test configuration are all available. For the
test matrix and focused commands, see [docs/testing.md](docs/testing.md).

### Integration and E2E tests

The repo includes opt-in live integration tests against a deployed environment:

- [tests/test_e2e_real_engine_aggregation.py](tests/test_e2e_real_engine_aggregation.py) — single-CV live real-engine aggregation validation
- [tests/test_e2e_real_engine_3cv_prompt4.py](tests/test_e2e_real_engine_3cv_prompt4.py) — stages three PDFs from [tests/realdata](tests/realdata) and validates terminal aggregation

Shared aggregation logic is also validated with:

- [tests/test_shared_aggregation.py](tests/test_shared_aggregation.py) — profile-based aggregation behavior for CV and generic payloads

Run the core E2E test:

```bash
RUN_REAL_ENGINE_E2E=true \
REAL_ENGINE_E2E_BASE_URL=https://<apim-host>/awr \
REAL_ENGINE_E2E_CV_BLOB_URI=https://<storage-account>.blob.core.windows.net/cv-uploads/<path>/cv.pdf \
REAL_ENGINE_E2E_CV_SHA256=<64-char-hex> \
python -m pytest tests/test_e2e_real_engine_aggregation.py -v
```

Run the 3-CV prompt4 E2E test:

```bash
RUN_REAL_ENGINE_E2E=true \
REAL_ENGINE_E2E_BASE_URL=https://<apim-host>/awr \
REAL_ENGINE_E2E_STORAGE_ACCOUNT=<storage-account> \
python -m pytest tests/test_e2e_real_engine_3cv_prompt4.py -v
```

---

## Scalability / Load Testing (no LLM tokens)

The real engine is replaced with a **fake engine** Function App that obeys the
same Service Bus contract (`engine-runs` → `engine-results`) and writes a
synthetic `output.json` artifact for `_aggregate` to parse. This lets you
exercise the platform's throughput, fan-out, Durable orchestration, SB lock
behaviour, DLQ, and APIM headroom **without consuming model tokens**.

See:

- [tools/fake-engine/function_app.py](tools/fake-engine/function_app.py) — SB-triggered fake engine
- [tests/load/assess.js](tests/load/assess.js) — k6 ramping-VU load script
- [scripts/deploy-fake-engine.sh](scripts/deploy-fake-engine.sh) — one-shot deploy
- [scripts/stage-cv.sh](scripts/stage-cv.sh) — pre-stage a CV blob

### Load Test Prerequisites

- `az login` to a context with permission to create role assignments on the
  storage account, Service Bus namespace queues, and resource group
  (Owner or User Access Administrator).
- Azure Functions Core Tools v4 (`func`).
- [k6](https://k6.io/docs/get-started/installation/) (`choco install k6` /
  `brew install k6`).
- The platform deployed (API + Durable Functions host) and the
  **real engine stopped or scaled to zero** so the fake engine has exclusive
  consumption of `engine-runs`.

### 1. Stage a sample CV

```bash
./scripts/stage-cv.sh <storage-account>
```

If no file argument is provided the script generates a tiny synthetic PDF.
It prints two values you'll need for the load run:

```text
CV_BLOB_URI=https://<storage-account>.blob.core.windows.net/cv-uploads/loadtest/cv-<sha8>.pdf
CV_SHA256=<64-hex>
```

### 2. Deploy the fake engine

```bash
export AZ_SUBSCRIPTION_ID=<sub-id>
export RG_NAME=rg-awr-loadtest
export LOCATION=eastus2
export STORAGE_ACCOUNT=<storage-account>
export SB_NAMESPACE=<service-bus-namespace>.servicebus.windows.net
# Optional Application Insights wiring:
export APPINSIGHTS_CONN="InstrumentationKey=...;IngestionEndpoint=..."

./scripts/deploy-fake-engine.sh
```

The script is idempotent. It will:

1. Ensure the resource group exists.
2. Ensure the `batch-results` blob container exists.
3. Ensure `engine-runs` + `engine-results` SB queues exist (DLQ enabled,
   `maxDeliveryCount=10`).
4. Create a Linux Python 3.11 Consumption Function App with a
   system-assigned managed identity.
5. Write all app settings (SB FQDN, blob account, knobs).
6. Grant the FA's MI least-privilege RBAC:
   - `Azure Service Bus Data Receiver` on `engine-runs`
   - `Azure Service Bus Data Sender` on `engine-results`
   - `Storage Blob Data Contributor` on the storage account
7. `func azure functionapp publish ... --build remote`.

### 3. Run the load test

```bash
k6 run \
  -e BASE_URL=https://<apim-host>/awr \
  -e API_KEY=<apim-subscription-key> \
  -e CV_BLOB_URI=<from step 1> \
  -e CV_SHA256=<from step 1> \
  -e RUN_COUNT=3 \
  -e CV_COUNT=2 \
  -e POLL=true \
  tests/load/assess.js
```

Default scenario ramps `0 → 5 → 20 → 50` VUs over ~5 min with thresholds on
submit p95/p99, status p95, batch completion rate, and end-to-end seconds.
Override `--vus` / `--duration` to switch to a constant arrival rate.

### 4. Knobs for chaos / contract validation

Tune the fake engine via app settings (then `az functionapp restart`):

| Setting | Default | Effect |
| ------- | ------- | ------ |
| `FAKE_LATENCY_MS_MIN` / `MAX` | 50 / 250 | Per-run synthetic latency |
| `FAKE_FAILURE_RATE` | 0.0 | Probability of emitting `status=Failed` (no artifact) |
| `FAKE_TRANSIENT_RATE` | 0.0 | Probability of raising → SB redelivery, eventually DLQ |
| `FAKE_SCORE_MIN` / `MAX` | 5.5 / 9.5 | Synthetic score range |
| `FAKE_MUST_HAVE_PASS_RATE` | 0.85 | Per-must-have pass probability (drives Approve/Reject mix) |

Useful runs:

- **DLQ exercise** — `FAKE_TRANSIENT_RATE=0.10` (~10% redelivery, then dead-letter after 10 attempts).
- **Aggregator skip path** — `FAKE_FAILURE_RATE=0.10` with `RUN_COUNT=3` (validates AND/median over partial succeeds).
- **Lock-renewal stress** — bump `FAKE_LATENCY_MS_MAX` to 120000 against the `maxAutoRenewDuration=00:05:00` in [tools/fake-engine/host.json](tools/fake-engine/host.json).

### 5. What to watch in Azure Monitor

| Concern | Signal |
| ------- | ------ |
| SB throughput / hot partition | `IncomingMessages`, `ActiveMessages`, `DeadletteredMessages` on `engine-runs`/`engine-results` |
| Fan-out limits | Functions host metrics; Durable storage account `Transactions` / throttling |
| Blob hotspots | Storage `Transactions`, `SuccessE2ELatency`, server timeouts on `batch-results` |
| API tier | APIM `Capacity` %, 429s; FastAPI p95/p99 |
| End-to-end latency | App Insights distributed trace via `traceparent` (submit → dispatch → result → finalize) |

### 6. Cleanup

```bash
az group delete -n "$RG_NAME" --yes --no-wait
```

If the fake engine was deployed into a shared RG, delete just the Function App
and its plan:

```bash
az functionapp delete -g "$RG_NAME" -n "$FAKE_FA_NAME"
az functionapp plan delete -g "$RG_NAME" -n "${FAKE_FA_NAME}-plan" --yes
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
| -------- | ------ | ----------- |
| `host_choice` | `webapp_container` / `container_apps` | API hosting model |
| `use_private_endpoints` | `true` / `false` | Enable VNet + private endpoints |
| `enable_artifact_storage` | `true` / `false` | Provision blob storage for artifacts |
| `apim_sku` | e.g. `Developer_1`, `Standard_1` | APIM tier |

---

## CI/CD – GitHub Actions with OIDC

This repository currently does not ship active workflow YAML files under `.github/workflows`.

When enabling CI/CD for this repo, prefer OIDC-based federation to Azure (no static client secrets), and split pipeline stages into:

1. test and lint validation
2. Terraform plan/apply with environment approvals
3. API and Functions deployment

---

## Operational Runbook

### DLQ Replay

Dead-lettered messages accumulate when engine workers fail repeatedly. To replay:

```bash
# Via the DLQ replay Azure Function (HTTP trigger):
curl -X POST "https://<functions-app>.azurewebsites.net/api/dlq-replay?max=50"

# Or manually via Azure CLI:
az servicebus queue show --namespace-name <service-bus-namespace> --name engine-runs \
  --query "countDetails.deadLetterMessageCount"
```

### Scaling Knobs

| Resource | Setting | Where |
| -------- | ------- | ----- |
| API throughput | App Service Plan SKU / ACA CPU+memory | `app_service_sku` or ACA template |
| Service Bus | Standard → Premium (partitioning, larger messages) | `service_bus_sku` |
| Functions | Consumption → Premium (VNet, always-ready) | `functions_sku` |
| APIM | Developer → Standard/Premium | `apim_sku` |

### Transient Retry Policy

Platform retries rely on Service Bus delivery semantics, Durable Functions replay, and HTTP client retry/backoff behavior where configured.

General retry expectations:

- Base delay: 500 ms (doubles each attempt)
- Max delay: 60 s
- Max retries: 6
- Retry only transient transport or dependency failures

---

## Security

- **No credentials in code** — all Azure access uses Managed Identity (or `az login` locally).
- **Key Vault** stores any configuration secrets; accessed via MI.
- **AAD JWT** enforcement is optional (`AUTH_REQUIRED=true`).
- **APIM** provides rate limiting, subscription keys, and header redaction.
- **Private endpoints** can be toggled for storage, Service Bus, and APIM in production.

---

## License

Internal / proprietary. See your organization's licensing policy.
