"""Tests for transient SQL retry logic.

Simulates a transient error on the first call, then success on the second.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

from api.models import RunResponse, RunStatus
from db.repository import RunRepository


def _make_transient_error() -> pyodbc.Error:
    """Create a pyodbc.Error that looks transient (SQLState 40613 = DB not available)."""
    err = pyodbc.Error("40613", "Database is not currently available")
    return err


def _make_permanent_error() -> pyodbc.Error:
    err = pyodbc.Error("42S02", "Invalid object name")
    return err


class TestSqlRetry:
    @patch("db.repository.get_connection")
    @patch("runtime.transient.time.sleep", return_value=None)  # skip actual sleep
    def test_retries_on_transient_then_succeeds(self, mock_sleep: MagicMock, mock_conn: MagicMock) -> None:
        """First call raises transient error, second call succeeds."""
        run_id = uuid.uuid4()

        # Build a mock row for the success case
        row_mock = MagicMock()
        row_mock.id = str(run_id)
        row_mock.idempotency_key = "key-retry"
        row_mock.engine = "gpt-4"
        row_mock.status = "pending"
        row_mock.parameters = "{}"
        row_mock.duration_ms = None
        row_mock.tokens_prompt = None
        row_mock.tokens_completion = None
        row_mock.error_message = None
        row_mock.created_at = "2025-01-01T00:00:00"
        row_mock.updated_at = None

        # First conn.cursor().execute raises transient error
        bad_cursor = MagicMock()
        bad_cursor.execute.side_effect = _make_transient_error()
        bad_conn = MagicMock()
        bad_conn.cursor.return_value = bad_cursor

        # Second conn.cursor().execute succeeds
        good_cursor = MagicMock()
        good_cursor.fetchone.return_value = row_mock
        good_conn = MagicMock()
        good_conn.cursor.return_value = good_cursor

        mock_conn.side_effect = [bad_conn, good_conn]

        repo = RunRepository()
        result = repo.get_run(run_id)

        assert result is not None
        assert result.id == run_id
        assert mock_sleep.called  # verify that backoff sleep was invoked

    @patch("db.repository.get_connection")
    @patch("runtime.transient.time.sleep", return_value=None)
    def test_does_not_retry_permanent_error(self, mock_sleep: MagicMock, mock_conn: MagicMock) -> None:
        """Permanent errors should raise immediately, no retry."""
        bad_cursor = MagicMock()
        bad_cursor.execute.side_effect = _make_permanent_error()
        bad_conn = MagicMock()
        bad_conn.cursor.return_value = bad_cursor
        mock_conn.return_value = bad_conn

        repo = RunRepository()
        with pytest.raises(pyodbc.Error):
            repo.get_run(uuid.uuid4())

        mock_sleep.assert_not_called()
