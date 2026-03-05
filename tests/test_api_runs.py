"""Tests for the /runs API endpoints.

Uses FastAPI dependency_overrides so the mock repository is actually injected
(``unittest.mock.patch`` cannot intercept references captured by ``Depends``).
"""

from __future__ import annotations

import uuid
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models import RunResponse, RunStatus
from api.routes_runs import _get_repo


def _make_run_response(**overrides) -> RunResponse:  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "idempotency_key": "key-1",
        "engine": "gpt-4",
        "status": RunStatus.PENDING,
        "parameters": {},
        "created_at": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return RunResponse(**defaults)


@pytest.fixture()
def mock_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_repo: MagicMock) -> Generator[TestClient, None, None]:
    app.dependency_overrides[_get_repo] = lambda: mock_repo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── POST /runs ────────────────────────────────────────────────────────────────


class TestCreateRun:
    def test_create_run_returns_201(self, mock_repo: MagicMock, client: TestClient) -> None:
        run = _make_run_response()
        mock_repo.get_by_idempotency_key.return_value = None
        mock_repo.insert_run_started.return_value = run

        resp = client.post("/runs", json={"idempotency_key": "key-1", "engine": "gpt-4"})
        assert resp.status_code == 201
        assert resp.json()["idempotency_key"] == "key-1"

    def test_idempotent_duplicate_returns_existing(self, mock_repo: MagicMock, client: TestClient) -> None:
        run = _make_run_response()
        mock_repo.get_by_idempotency_key.return_value = run

        resp = client.post("/runs", json={"idempotency_key": "key-1", "engine": "gpt-4"})
        assert resp.status_code == 201
        assert resp.json()["id"] == str(run.id)


# ── PATCH /runs/{runId} ──────────────────────────────────────────────────────


class TestFinishRun:
    def test_finish_run_updates_status(self, mock_repo: MagicMock, client: TestClient) -> None:
        run_id = uuid.uuid4()
        run = _make_run_response(id=run_id)
        updated = _make_run_response(id=run_id, status=RunStatus.SUCCEEDED, duration_ms=1234)
        mock_repo.get_run.return_value = run
        mock_repo.update_run_finished.return_value = updated

        resp = client.patch(f"/runs/{run_id}", json={"status": "succeeded", "duration_ms": 1234})
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_finish_nonexistent_returns_404(self, mock_repo: MagicMock, client: TestClient) -> None:
        mock_repo.get_run.return_value = None

        resp = client.patch(f"/runs/{uuid.uuid4()}", json={"status": "failed"})
        assert resp.status_code == 404


# ── GET /runs ─────────────────────────────────────────────────────────────────


class TestListRuns:
    def test_list_runs_paginated(self, mock_repo: MagicMock, client: TestClient) -> None:
        runs = [_make_run_response() for _ in range(3)]
        mock_repo.get_runs.return_value = (runs, 3)

        resp = client.get("/runs?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3


# ── GET /runs/{runId} ────────────────────────────────────────────────────────


class TestGetRun:
    def test_get_run_found(self, mock_repo: MagicMock, client: TestClient) -> None:
        run_id = uuid.uuid4()
        run = _make_run_response(id=run_id)
        mock_repo.get_run.return_value = run

        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(run_id)

    def test_get_run_not_found(self, mock_repo: MagicMock, client: TestClient) -> None:
        mock_repo.get_run.return_value = None

        resp = client.get(f"/runs/{uuid.uuid4()}")
        assert resp.status_code == 404
