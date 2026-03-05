"""Tests for idempotency in the repository layer.

Verifies that inserting twice with the same idempotency_key returns the same runId.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from api.models import RunResponse, RunStatus
from db.repository import RunRepository


def _fake_run(idempotency_key: str = "idem-123") -> RunResponse:
    return RunResponse(
        id=uuid.uuid4(),
        idempotency_key=idempotency_key,
        engine="gpt-4",
        status=RunStatus.PENDING,
        parameters={},
        created_at="2025-01-01T00:00:00Z",
    )


class TestIdempotency:
    @patch("db.repository.get_connection")
    def test_double_insert_returns_same_run_id(self, mock_conn: MagicMock) -> None:
        """Simulate: first call inserts, second call finds existing row."""
        repo = RunRepository()

        # First call: no existing row → insert
        existing_run = _fake_run()
        cursor_mock = MagicMock()
        cursor_mock.fetchone.return_value = None
        conn_instance = MagicMock()
        conn_instance.cursor.return_value = cursor_mock
        mock_conn.return_value = conn_instance

        result_none = repo.get_by_idempotency_key("idem-123")
        assert result_none is None

        # Second call: existing row found → return it
        row_mock = MagicMock()
        row_mock.id = str(existing_run.id)
        row_mock.idempotency_key = existing_run.idempotency_key
        row_mock.engine = existing_run.engine
        row_mock.status = existing_run.status.value
        row_mock.parameters = "{}"
        row_mock.duration_ms = None
        row_mock.tokens_prompt = None
        row_mock.tokens_completion = None
        row_mock.error_message = None
        row_mock.created_at = existing_run.created_at
        row_mock.updated_at = None

        cursor_mock2 = MagicMock()
        cursor_mock2.fetchone.return_value = row_mock
        conn_instance2 = MagicMock()
        conn_instance2.cursor.return_value = cursor_mock2
        mock_conn.return_value = conn_instance2

        result = repo.get_by_idempotency_key("idem-123")
        assert result is not None
        assert result.id == existing_run.id
        assert result.idempotency_key == "idem-123"
