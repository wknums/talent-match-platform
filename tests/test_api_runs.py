"""Tests for the /runs API endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models import RunResponse, RunStatus


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


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


# ── POST /runs ────────────────────────────────────────────────────────────────


class TestCreateRun:
    @patch("api.routes_runs._get_repo")
    def test_create_run_returns_201(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        run = _make_run_response()
        repo = MagicMock()
        repo.get_by_idempotency_key.return_value = None
        repo.insert_run_started.return_value = run
        mock_repo_factory.return_value = repo

        resp = client.post("/runs", json={"idempotency_key": "key-1", "engine": "gpt-4"})
        assert resp.status_code == 201
        assert resp.json()["idempotency_key"] == "key-1"

    @patch("api.routes_runs._get_repo")
    def test_idempotent_duplicate_returns_existing(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        run = _make_run_response()
        repo = MagicMock()
        repo.get_by_idempotency_key.return_value = run
        mock_repo_factory.return_value = repo

        resp = client.post("/runs", json={"idempotency_key": "key-1", "engine": "gpt-4"})
        assert resp.status_code == 201
        assert resp.json()["id"] == str(run.id)


# ── PATCH /runs/{runId} ──────────────────────────────────────────────────────


class TestFinishRun:
    @patch("api.routes_runs._get_repo")
    def test_finish_run_updates_status(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        run_id = uuid.uuid4()
        run = _make_run_response(id=run_id)
        updated = _make_run_response(id=run_id, status=RunStatus.SUCCEEDED, duration_ms=1234)
        repo = MagicMock()
        repo.get_run.return_value = run
        repo.update_run_finished.return_value = updated
        mock_repo_factory.return_value = repo

        resp = client.patch(f"/runs/{run_id}", json={"status": "succeeded", "duration_ms": 1234})
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    @patch("api.routes_runs._get_repo")
    def test_finish_nonexistent_returns_404(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        repo = MagicMock()
        repo.get_run.return_value = None
        mock_repo_factory.return_value = repo

        resp = client.patch(f"/runs/{uuid.uuid4()}", json={"status": "failed"})
        assert resp.status_code == 404


# ── GET /runs ─────────────────────────────────────────────────────────────────


class TestListRuns:
    @patch("api.routes_runs._get_repo")
    def test_list_runs_paginated(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        runs = [_make_run_response() for _ in range(3)]
        repo = MagicMock()
        repo.get_runs.return_value = (runs, 3)
        mock_repo_factory.return_value = repo

        resp = client.get("/runs?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3


# ── GET /runs/{runId} ────────────────────────────────────────────────────────


class TestGetRun:
    @patch("api.routes_runs._get_repo")
    def test_get_run_found(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        run_id = uuid.uuid4()
        run = _make_run_response(id=run_id)
        repo = MagicMock()
        repo.get_run.return_value = run
        mock_repo_factory.return_value = repo

        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(run_id)

    @patch("api.routes_runs._get_repo")
    def test_get_run_not_found(self, mock_repo_factory: MagicMock, client: TestClient) -> None:
        repo = MagicMock()
        repo.get_run.return_value = None
        mock_repo_factory.return_value = repo

        resp = client.get(f"/runs/{uuid.uuid4()}")
        assert resp.status_code == 404
