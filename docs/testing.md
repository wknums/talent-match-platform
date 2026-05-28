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

## Live Real-Engine Aggregation E2E

Use this opt-in pytest to verify that live engine scoring output reaches terminal
batch status with populated aggregation fields.

Required environment variables:

- `RUN_REAL_ENGINE_E2E=true`
- `REAL_ENGINE_E2E_BASE_URL` (for example, `https://<apim-host>/awr`)
- `REAL_ENGINE_E2E_CV_BLOB_URI`
- `REAL_ENGINE_E2E_CV_SHA256`

Optional environment variables:

- `REAL_ENGINE_E2E_APIM_KEY`
- `REAL_ENGINE_E2E_BEARER`
- `REAL_ENGINE_E2E_RUN_COUNT` (default `1`)
- `REAL_ENGINE_E2E_TIMEOUT_SECONDS` (default `300`)
- `REAL_ENGINE_E2E_POLL_SECONDS` (default `5`)

Run command:

```bash
python -m pytest tests/test_e2e_real_engine_aggregation.py -v
```

## QA Validation Fixture Template

Use this payload template for repeatable QA orchestration validation runs.

```json
{
	"batchId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
	"jobId": "job-qa-001",
	"promptVersionId": "pv-qa-001",
	"runCount": 1,
	"prompt": {
		"kind": "inline",
		"text": "Score this CV against the role criteria and return structured JSON output."
	},
	"cvs": [
		{
			"applicationId": "app-qa-001",
			"documentId": "doc-qa-001",
			"fileName": "cv-qa.pdf",
			"mimeType": "application/pdf",
			"blobUri": "https://<storage-account>.blob.core.windows.net/cv-uploads/<path>/cv-qa.pdf",
			"sha256": "<64-char-hex>"
		}
	]
}
```

## QA Metrics Output Template

`scripts/qa-orchestration-validate.sh` emits this structure:

```json
{
	"submissionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
	"finalStatus": "completed",
	"elapsedSeconds": 83,
	"successCriteria": {
		"SC001_terminal_within_120s": true,
		"SC002_completed_fields_present": true,
		"SC003_single_authoritative_run_record": true,
		"SC004_trace_metadata_continuity": true,
		"SC005_unknown_submission_not_found": true
	},
	"overallPass": true
}
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