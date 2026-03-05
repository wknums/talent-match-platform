"""Transient fault handling – exponential backoff with jitter for SQL and HTTP.

Key design points:
- Re-open the SQL connection before retrying the command (connections may be stale).
- Differentiate transient pyodbc errors from permanent ones.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Any, Callable, TypeVar

import pyodbc

from runtime.config import get_settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# pyodbc SQLState codes considered transient (Azure SQL-specific)
_TRANSIENT_SQL_STATES: set[str] = {
    "08S01",  # Communication link failure
    "08001",  # Unable to connect
    "40613",  # Database not available
    "40197",  # Service error processing request
    "40501",  # Service busy
    "49918",  # Cannot process request – not enough resources
    "49919",  # Cannot process create/update request
    "49920",  # Too many requests
    "40143",  # Connection was terminated by the server  (HA failover)
    "HYT00",  # Timeout expired
}


def _is_transient(exc: pyodbc.Error) -> bool:
    """Determine whether a pyodbc error is transient and worth retrying."""
    if hasattr(exc, "args") and len(exc.args) >= 1:
        sqlstate = str(exc.args[0]) if exc.args[0] else ""
        if sqlstate in _TRANSIENT_SQL_STATES:
            return True
    return False


def with_sql_retry(fn: F) -> F:
    """Decorator that retries a function on transient SQL errors.

    Before each retry the decorator does **not** reuse the old connection –
    the wrapped function should call ``get_connection()`` at the top so it
    acquires a fresh connection on each attempt.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()
        last_exc: Exception | None = None
        for attempt in range(1, settings.sql_max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except pyodbc.Error as exc:
                last_exc = exc
                if not _is_transient(exc) or attempt == settings.sql_max_retries:
                    logger.error(
                        "SQL error (attempt %d/%d, non-transient or max retries): %s",
                        attempt,
                        settings.sql_max_retries,
                        exc,
                    )
                    raise
                delay_s = _backoff_delay(attempt, settings.sql_base_delay_ms, settings.sql_max_delay_ms)
                logger.warning(
                    "Transient SQL error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    settings.sql_max_retries,
                    delay_s,
                    exc,
                )
                time.sleep(delay_s)
        # Should not reach here, but satisfy mypy
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]


def _backoff_delay(attempt: int, base_ms: int, max_ms: int) -> float:
    """Compute exponential backoff with full jitter (in seconds)."""
    exp_delay_ms = min(base_ms * (2 ** (attempt - 1)), max_ms)
    jittered_ms = random.uniform(0, exp_delay_ms)  # noqa: S311
    return jittered_ms / 1000.0
