"""Traceability tests for completed result lineage and purge fallback.

These tests lock down two recovery paths:
- the finalized batch result keeps application -> run -> artifact lineage intact,
- the API preserves that lineage when Durable history is gone and it falls back
  to the persisted result blob.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import orchestrator.functions.fanout as fanout
from api.main import app


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOB_ACCOUNT", "acct")
    monkeypatch.setenv("BLOB_RESULTS_CONTAINER", "batch-results")
    from runtime.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    from api.auth import require_auth

    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_finalize_batch_preserves_application_run_artifact_lineage(settings) -> None:
    payload = {
        "batch_id": "batch-1",
        "cvs": [
            {
                "applicationId": "app-1",
                "documentId": "doc-1",
                "fileName": "cv.pdf",
                "mimeType": "application/pdf",
                "blobUri": "https://acct.blob.core.windows.net/cv/cv.pdf",
                "sha256": "a" * 64,
            }
        ],
        "run_results": [
            {
                "run_id": "run-1",
                "_application_id": "app-1",
                "_run_index": 0,
                "status": "Succeeded",
                "duration_ms": 123,
                "tokens_prompt": 10,
                "tokens_completion": 20,
                "error_message": None,
                "artifacts": [
                    {
                        "name": "output.json",
                        "blob_uri": "https://acct.blob.core.windows.net/results/output.json",
                        "mime": "application/json",
                    }
                ],
            }
        ],
    }

    with patch.object(fanout, "_upload_blob", return_value="https://acct/blob/result.json"):
        result = fanout.finalize_batch(payload)

    cv = result["cvs"][0]
    assert cv["applicationId"] == "app-1"
    assert cv["documentId"] == "doc-1"
    run = cv["runs"][0]
    assert run["runId"] == "run-1"
    assert run["runIndex"] == 0
    assert run["documentId"] == "doc-1"
    assert run["status"] == "Succeeded"
    assert run["artifacts"][0]["name"] == "output.json"
    assert run["artifacts"][0]["blob_uri"].endswith("/output.json")


def test_status_blob_fallback_preserves_traceability_after_durable_purge(client: TestClient) -> None:
    from api import durable_client

    blob_result = {
        "cvs": [
            {
                "applicationId": "app-1",
                "documentId": "doc-1",
                "runs": [
                    {
                        "runId": "run-1",
                        "runIndex": 0,
                        "documentId": "doc-1",
                        "status": "Succeeded",
                        "artifacts": [
                            {
                                "name": "output.json",
                                "blob_uri": "https://acct.blob.core.windows.net/results/output.json",
                            }
                        ],
                    }
                ],
                "aggregated": {
                    "finalScore": 7.0,
                    "finalDecision": "Approve",
                    "mustHaveResult": True,
                },
                "error": None,
            }
        ]
    }

    with patch("api.routes_assess.durable_client.get_batch_status") as gs, \
         patch("api.routes_assess.durable_client.read_batch_result_from_blob") as rb:
        gs.side_effect = durable_client.DurableClientError(404, "not found")
        rb.return_value = blob_result
        response = client.get("/assess/batch/batch-1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    cv = body["result"]["cvs"][0]
    assert cv["applicationId"] == "app-1"
    assert cv["documentId"] == "doc-1"
    run = cv["runs"][0]
    assert run["runId"] == "run-1"
    assert run["documentId"] == "doc-1"
    assert run["artifacts"][0]["blob_uri"].endswith("/output.json")