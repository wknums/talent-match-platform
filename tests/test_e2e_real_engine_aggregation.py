"""Live E2E verification for real-engine scoring and aggregation.

This test is intentionally opt-in and only runs when
``RUN_REAL_ENGINE_E2E=true`` is set.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
import pytest


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for real-engine E2E test")
    return value


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def test_real_engine_scoring_outputs_are_aggregated() -> None:
    if os.getenv("RUN_REAL_ENGINE_E2E", "false").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set RUN_REAL_ENGINE_E2E=true to run live real-engine aggregation validation")

    base_url = _env("REAL_ENGINE_E2E_BASE_URL").rstrip("/")
    cv_blob_uri = _env("REAL_ENGINE_E2E_CV_BLOB_URI")
    cv_sha256 = _env("REAL_ENGINE_E2E_CV_SHA256")
    run_count = int(os.getenv("REAL_ENGINE_E2E_RUN_COUNT", "1"))
    timeout_seconds = int(os.getenv("REAL_ENGINE_E2E_TIMEOUT_SECONDS", "300"))
    poll_seconds = int(os.getenv("REAL_ENGINE_E2E_POLL_SECONDS", "5"))

    batch_id = str(uuid.uuid4())
    payload = {
        "batchId": batch_id,
        "jobId": f"job-{batch_id[:8]}",
        "promptVersionId": "pv-e2e-real-engine",
        "runCount": run_count,
        "prompt": {
            "kind": "inline",
            "text": "Score this CV and return structured scoring output.",
        },
        "cvs": [
            {
                "applicationId": f"app-{batch_id[:8]}",
                "documentId": f"doc-{batch_id[:8]}",
                "fileName": "candidate.pdf",
                "mimeType": "application/pdf",
                "blobUri": cv_blob_uri,
                "sha256": cv_sha256,
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": batch_id,
        "x-correlation-id": f"e2e-{batch_id}",
    }

    api_key = os.getenv("REAL_ENGINE_E2E_APIM_KEY", "").strip()
    bearer = os.getenv("REAL_ENGINE_E2E_BEARER", "").strip()
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    with httpx.Client(timeout=30.0) as client:
        submit = client.post(f"{base_url}/assess/batch", json=payload, headers=headers)
        assert submit.status_code == 202, submit.text
        submit_json = submit.json()
        assert submit_json.get("submissionId") == batch_id

        deadline = time.time() + timeout_seconds
        last_response: dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(poll_seconds)
            status_resp = client.get(f"{base_url}/assess/batch/{batch_id}/status", headers=headers)
            assert status_resp.status_code == 200, status_resp.text
            last_response = status_resp.json()
            if last_response.get("status") in {"completed", "failed", "cancelled"}:
                break

    assert last_response, "No status response captured"
    assert last_response.get("status") == "completed", last_response

    result = last_response.get("result")
    assert isinstance(result, dict), last_response
    cvs = result.get("cvs")
    assert isinstance(cvs, list) and cvs, result

    for cv in cvs:
        aggregated = cv.get("aggregated")
        assert isinstance(aggregated, dict), cv

        score = _coerce_float(aggregated.get("finalScore"))
        assert score is not None, aggregated
        assert 0.0 <= score <= 10.0, aggregated

        decision = aggregated.get("finalDecision")
        assert isinstance(decision, str) and decision.strip(), aggregated

        must_have = aggregated.get("mustHaveResult")
        assert isinstance(must_have, bool), aggregated

        runs = cv.get("runs")
        assert isinstance(runs, list) and runs, cv
        assert any(run.get("status") == "Succeeded" for run in runs), cv