# Testing Guide

This guide documents the test suites in this repo, what each validates, and how
to run focused checks during development.

## Prerequisites

Install the development extras so async tests and rewrite rules are available:

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
pip install -e ".[dev]"
```

Recommended invocation:

```bash
python -m pytest tests -v
```

Using `python -m pytest` ensures the editable install and current interpreter
are used together.

## Test Suite Map

| Test module | Coverage |
| --- | --- |
| `tests/test_routes_assess.py` | Submit, idempotent repeat, status normalization, cancel semantics, and blob-result fallback |
| `tests/test_dispatch_run.py` | Service Bus `RunMessage` shape, run-index writes, and dispatch invariants |
| `tests/test_result_intake.py` | Service Bus and HTTP result-intake callbacks, duplicate delivery handling, and traceparent preservation |
| `tests/test_progress_state.py` | Durable custom status updates, batch/application/run counters, and transition timestamps |
| `tests/test_traceability.py` | `applicationId -> runId -> artifact` lineage and recovery after Durable history purge |
| `tests/test_live_events.py` | Live event schema, SignalR projection, managed-identity publish path, and polling fallback behavior |
| `tests/test_aggregate.py` | Aggregation rules for median score, must-have AND semantics, variance, and artifact download parsing |
| `tests/test_auth.py` | Entra JWT/JWKS fetch, issuer/audience validation, and signature checks |
| `tests/test_fake_engine.py` | Fake-engine helper behavior for load and contract testing |

## Common Focused Commands

Run the most common suites while changing the platform contract:

```bash
python -m pytest tests/test_routes_assess.py -v
python -m pytest tests/test_dispatch_run.py -v
python -m pytest tests/test_result_intake.py -v
python -m pytest tests/test_progress_state.py -v
python -m pytest tests/test_traceability.py -v
python -m pytest tests/test_live_events.py -v
python -m pytest tests/test_aggregate.py -v
python -m pytest tests/test_auth.py -v
```

Run the full suite:

```bash
python -m pytest tests -v
```

## Infrastructure Validation

For Terraform changes, run:

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/envs/dev init -backend=false -input=false
terraform -chdir=infra/terraform/envs/dev validate
terraform -chdir=infra/terraform/envs/test init -backend=false -input=false
terraform -chdir=infra/terraform/envs/test validate
terraform -chdir=infra/terraform/envs/prod init -backend=false -input=false
terraform -chdir=infra/terraform/envs/prod validate
```

## What the tests do not cover

- Real Azure resource deployment or RBAC propagation timing
- Real engine execution in the client/engine repo
- APIM policy enforcement end-to-end
- SignalR negotiation flows for browser clients

Those require integration or deployment validation outside this repo.