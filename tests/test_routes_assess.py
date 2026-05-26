"""Tests for the /assess/batch FastAPI routes (submit, status, cancel).

The Functions host is mocked at the ``api.durable_client`` boundary so these
tests run without Azure dependencies.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Disable auth requirement for tests.
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    # Bypass auth dependency entirely.
    from api.auth import require_auth

    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _sample_body(batch_id: str | None = None) -> dict:
    bid = batch_id or str(uuid.uuid4())
    return {
        "batchId": bid,
        "jobId": "job-1",
        "promptVersionId": "pv-1",
        "runCount": 2,
        "prompt": {"kind": "inline", "text": "Score this CV."},
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
    }


# ── POST /assess/batch ───────────────────────────────────────────────────────
def test_submit_batch_accepts_and_returns_202(client: TestClient) -> None:
    body = _sample_body()
    bid = body["batchId"]
    with patch("api.routes_assess.durable_client.start_batch") as m:
        m.return_value = None
        r = client.post(
            "/assess/batch",
            json=body,
            headers={"Idempotency-Key": bid, "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"},
        )
    assert r.status_code == 202, r.text
    js = r.json()
    assert js["submissionId"] == bid
    assert js["status"] == "queued"
    # traceparent was forwarded to durable_client.
    _, kwargs = m.call_args
    assert kwargs["traceparent"].startswith("00-")


def test_submit_batch_rejects_mismatched_idempotency_key(client: TestClient) -> None:
    body = _sample_body()
    r = client.post(
        "/assess/batch",
        json=body,
        headers={"Idempotency-Key": "not-the-batch-id"},
    )
    assert r.status_code == 400


def test_submit_batch_conflict_maps_to_409(client: TestClient) -> None:
    from api import durable_client

    body = _sample_body()
    bid = body["batchId"]
    with patch("api.routes_assess.durable_client.start_batch") as m:
        m.side_effect = durable_client.OrchestrationConflictError(409, "exists")
        r = client.post("/assess/batch", json=body, headers={"Idempotency-Key": bid})
    assert r.status_code == 409


# ── GET /assess/batch/{id}/status ────────────────────────────────────────────
def test_status_running_passthrough(client: TestClient) -> None:
    bid = str(uuid.uuid4())
    with patch("api.routes_assess.durable_client.get_batch_status") as m:
        m.return_value = {
            "status": "running",
            "progress": {
                "cvsCompleted": 1,
                "cvsTotal": 3,
                "runsCompleted": 2,
                "runsTotal": 6,
                "runsDispatched": 4,
                "lastUpdatedAt": "2026-05-22T12:03:00Z",
                "applications": [
                    {
                        "applicationId": "app-1",
                        "documentId": "doc-1",
                        "status": "running",
                        "runsCompleted": 1,
                        "runsTotal": 2,
                        "runs": [
                            {
                                "runId": "r-1",
                                "runIndex": 0,
                                "status": "succeeded",
                            },
                            {
                                "runId": "r-2",
                                "runIndex": 1,
                                "status": "dispatched",
                            },
                        ],
                    }
                ],
            },
            "result": None,
            "error": None,
            "retryAfterSeconds": 10,
        }
        r = client.get(f"/assess/batch/{bid}/status")
    assert r.status_code == 200
    js = r.json()
    assert js["status"] == "running"
    assert js["progress"]["cvsCompleted"] == 1
    assert js["progress"]["runsCompleted"] == 2
    assert js["progress"]["runsTotal"] == 6
    assert js["progress"]["lastUpdatedAt"] == "2026-05-22T12:03:00Z"
    assert js["progress"]["applications"][0]["applicationId"] == "app-1"
    assert js["progress"]["applications"][0]["runs"][0]["runId"] == "r-1"


def test_status_404_falls_back_to_blob(client: TestClient) -> None:
    bid = str(uuid.uuid4())
    from api import durable_client

    blob_result = {"cvs": [{"applicationId": "a", "runs": [], "aggregated": None, "error": None}]}
    with patch("api.routes_assess.durable_client.get_batch_status") as gs, \
         patch("api.routes_assess.durable_client.read_batch_result_from_blob") as rb:
        gs.side_effect = durable_client.DurableClientError(404, "not found")
        rb.return_value = blob_result
        r = client.get(f"/assess/batch/{bid}/status")
    assert r.status_code == 200
    js = r.json()
    assert js["status"] == "completed"
    assert js["result"]["cvs"][0]["applicationId"] == "a"


def test_status_404_without_blob_returns_404(client: TestClient) -> None:
    bid = str(uuid.uuid4())
    from api import durable_client

    with patch("api.routes_assess.durable_client.get_batch_status") as gs, \
         patch("api.routes_assess.durable_client.read_batch_result_from_blob") as rb:
        gs.side_effect = durable_client.DurableClientError(404, "not found")
        rb.return_value = None
        r = client.get(f"/assess/batch/{bid}/status")
    assert r.status_code == 404


# ── POST /assess/batch/{id}/cancel ───────────────────────────────────────────
@pytest.mark.parametrize(
    "http_status,expected_status,expected_body_status",
    [(202, 202, "cancelling"), (200, 200, "cancelled"), (409, 409, "completed")],
)
def test_cancel_state_matrix(
    client: TestClient, http_status: int, expected_status: int, expected_body_status: str
) -> None:
    bid = str(uuid.uuid4())
    with patch("api.routes_assess.durable_client.cancel_batch") as m:
        m.return_value = {"_http_status": http_status, "status": expected_body_status}
        r = client.post(f"/assess/batch/{bid}/cancel")
    assert r.status_code == expected_status
    assert r.json()["status"] == expected_body_status
