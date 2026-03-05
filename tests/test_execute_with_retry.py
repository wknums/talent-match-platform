"""Tests for db.connection.execute_with_retry().

Covers:
- First call fails with a transient error, second call succeeds (connection is re-opened).
- Permanent errors propagate immediately without retry.
- All retries exhausted raises the last transient error.
- Transient *connection* failure is retried.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pyodbc
import pytest

from db.connection import execute_with_retry


# ── helpers ───────────────────────────────────────────────────────────────────


def _transient_error(sqlstate: str = "40613") -> pyodbc.Error:
    """Create a pyodbc.Error that looks transient."""
    return pyodbc.Error(sqlstate, f"Transient error ({sqlstate})")


def _permanent_error(sqlstate: str = "42S02") -> pyodbc.Error:
    """Create a pyodbc.Error that is NOT transient."""
    return pyodbc.Error(sqlstate, f"Permanent error ({sqlstate})")


# ── first-failure-then-success ────────────────────────────────────────────────


class TestExecuteWithRetryTransient:
    """The operation fails once with a transient error then succeeds on a fresh connection."""

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_retries_on_transient_then_succeeds(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        # First connection → operation raises transient error
        bad_conn = MagicMock(spec=pyodbc.Connection)
        # Second connection → operation succeeds
        good_conn = MagicMock(spec=pyodbc.Connection)
        mock_get_conn.side_effect = [bad_conn, good_conn]

        call_count = 0

        def operation(conn: pyodbc.Connection) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _transient_error("40613")
            return "ok"

        result = execute_with_retry(operation, max_retries=3, base_delay_ms=100, max_delay_ms=1000)

        assert result == "ok"
        assert call_count == 2
        # get_connection called twice (once per attempt)
        assert mock_get_conn.call_count == 2
        # sleep called once between attempt 1 and 2
        assert mock_sleep.call_count == 1
        # Both connections were closed
        bad_conn.close.assert_called_once()
        good_conn.close.assert_called_once()

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_connection_is_different_on_retry(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Verify the operation receives a *different* connection object on retry."""
        conn_a = MagicMock(spec=pyodbc.Connection)
        conn_b = MagicMock(spec=pyodbc.Connection)
        mock_get_conn.side_effect = [conn_a, conn_b]

        seen_connections: list[pyodbc.Connection] = []

        def operation(conn: pyodbc.Connection) -> str:
            seen_connections.append(conn)
            if len(seen_connections) == 1:
                raise _transient_error("08S01")
            return "done"

        execute_with_retry(operation, max_retries=3, base_delay_ms=10, max_delay_ms=100)

        assert len(seen_connections) == 2
        assert seen_connections[0] is conn_a
        assert seen_connections[1] is conn_b

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_multiple_transient_failures_then_success(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Three transient failures followed by success on attempt 4."""
        conns = [MagicMock(spec=pyodbc.Connection) for _ in range(4)]
        mock_get_conn.side_effect = conns

        attempt = 0

        def operation(conn: pyodbc.Connection) -> int:
            nonlocal attempt
            attempt += 1
            if attempt <= 3:
                raise _transient_error("40501")
            return 42

        result = execute_with_retry(operation, max_retries=5, base_delay_ms=10, max_delay_ms=100)

        assert result == 42
        assert attempt == 4
        assert mock_sleep.call_count == 3
        for c in conns:
            c.close.assert_called_once()


# ── permanent errors ──────────────────────────────────────────────────────────


class TestExecuteWithRetryPermanent:
    """Permanent errors propagate immediately — no retry, no sleep."""

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_permanent_error_raises_immediately(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        conn = MagicMock(spec=pyodbc.Connection)
        mock_get_conn.return_value = conn

        def operation(c: pyodbc.Connection) -> None:
            raise _permanent_error("42S02")

        with pytest.raises(pyodbc.Error, match="Permanent error"):
            execute_with_retry(operation, max_retries=5, base_delay_ms=10, max_delay_ms=100)

        # Only one attempt — no retries, no sleep
        assert mock_get_conn.call_count == 1
        mock_sleep.assert_not_called()
        conn.close.assert_called_once()


# ── exhausted retries ─────────────────────────────────────────────────────────


class TestExecuteWithRetryExhausted:
    """When max retries are exhausted the last transient error is raised."""

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_raises_after_max_retries(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_get_conn.return_value = MagicMock(spec=pyodbc.Connection)

        def operation(c: pyodbc.Connection) -> None:
            raise _transient_error("40613")

        with pytest.raises(pyodbc.Error, match="Transient error"):
            execute_with_retry(operation, max_retries=3, base_delay_ms=10, max_delay_ms=100)

        # Attempted exactly max_retries times
        assert mock_get_conn.call_count == 3
        # Sleeps happen between attempts (max_retries - 1), but on the last
        # attempt the error is raised without sleeping beforehand. The loop
        # sleeps after attempts 1 and 2, so sleep count = 2.
        assert mock_sleep.call_count == 2


# ── transient *connect* failure ───────────────────────────────────────────────


class TestExecuteWithRetryConnectFailure:
    """Transient errors during get_connection() itself are retried."""

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_transient_connect_error_retried(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        good_conn = MagicMock(spec=pyodbc.Connection)
        mock_get_conn.side_effect = [_transient_error("08001"), good_conn]

        result = execute_with_retry(lambda c: "connected", max_retries=3, base_delay_ms=10, max_delay_ms=100)

        assert result == "connected"
        assert mock_get_conn.call_count == 2
        assert mock_sleep.call_count == 1
        good_conn.close.assert_called_once()

    @patch("db.connection.time.sleep", return_value=None)
    @patch("db.connection.get_connection")
    def test_permanent_connect_error_not_retried(
        self,
        mock_get_conn: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_get_conn.side_effect = _permanent_error("28000")

        with pytest.raises(pyodbc.Error, match="Permanent error"):
            execute_with_retry(lambda c: None, max_retries=3, base_delay_ms=10, max_delay_ms=100)

        assert mock_get_conn.call_count == 1
        mock_sleep.assert_not_called()
