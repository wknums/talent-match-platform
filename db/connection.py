"""Azure SQL connection helper – passwordless via Microsoft Entra (DefaultAzureCredential).

Uses pyodbc with ODBC Driver 18 for SQL Server.
The access token is injected via the ``attrs_before`` parameter (token struct at key 1256).

``execute_with_retry`` is the recommended entry-point for running SQL
operations: it acquires a connection, executes the caller's function, and
automatically re-opens the connection before each retry on transient errors.
"""

from __future__ import annotations

import logging
import random
import struct
import time
from typing import Any, Callable, TypeVar

import pyodbc
from azure.identity import DefaultAzureCredential

from runtime.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Azure SQL token audience
_SQL_TOKEN_URL = "https://database.windows.net/.default"

# SQL_COPT_SS_ACCESS_TOKEN constant used by ODBC Driver 18
_SQL_COPT_SS_ACCESS_TOKEN = 1256

# pyodbc SQLState codes considered transient (Azure SQL-specific)
_TRANSIENT_SQL_STATES: frozenset[str] = frozenset(
    {
        "08S01",  # Communication link failure
        "08001",  # Unable to connect
        "40613",  # Database not available
        "40197",  # Service error processing request
        "40501",  # Service busy
        "49918",  # Cannot process request – not enough resources
        "49919",  # Cannot process create/update request
        "49920",  # Too many requests
        "40143",  # Connection terminated by server (HA failover)
        "HYT00",  # Timeout expired
    }
)


# ── Token helpers ─────────────────────────────────────────────────────────────


def _get_access_token() -> str:
    """Acquire an access token for Azure SQL using DefaultAzureCredential."""
    credential = DefaultAzureCredential()
    token = credential.get_token(_SQL_TOKEN_URL)
    return token.token


def _build_token_struct(access_token: str) -> bytes:
    """Encode token into the C struct expected by ODBC Driver 18 attrs_before[1256].

    The ODBC driver expects the token as a UTF-16-LE encoded byte string,
    preceded by its length as a 4-byte little-endian unsigned int.
    """
    token_bytes = access_token.encode("UTF-16-LE")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


# ── Connection factory ────────────────────────────────────────────────────────


def get_connection() -> pyodbc.Connection:
    """Create a new pyodbc connection to Azure SQL using Entra token auth.

    The connection string deliberately omits UID/PWD – authentication is
    handled entirely via the ODBC ``attrs_before`` mechanism
    (SQL_COPT_SS_ACCESS_TOKEN = 1256).
    """
    settings = get_settings()
    conn_str = (
        f"DRIVER={{{settings.sql_odbc_driver}}};"
        f"SERVER={settings.sql_server};"
        f"DATABASE={settings.sql_database};"
        f"Encrypt=yes;TrustServerCertificate=no;"
        f"Connection Timeout={settings.sql_connection_timeout};"
    )

    access_token = _get_access_token()
    token_struct = _build_token_struct(access_token)

    conn = pyodbc.connect(
        conn_str,
        attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: token_struct},
    )
    conn.timeout = settings.sql_command_timeout
    logger.debug("SQL connection established to %s/%s", settings.sql_server, settings.sql_database)
    return conn


# ── Transient-error classification ────────────────────────────────────────────


def _is_transient(exc: pyodbc.Error) -> bool:
    """Return *True* if the pyodbc error is transient and worth retrying."""
    if hasattr(exc, "args") and len(exc.args) >= 1:
        sqlstate = str(exc.args[0]) if exc.args[0] else ""
        return sqlstate in _TRANSIENT_SQL_STATES
    return False


def _backoff_delay(attempt: int, base_ms: int, max_ms: int) -> float:
    """Compute exponential backoff with *full jitter*, returned in **seconds**."""
    exp_delay_ms = min(base_ms * (2 ** (attempt - 1)), max_ms)
    jittered_ms = random.uniform(0, exp_delay_ms)  # noqa: S311
    return jittered_ms / 1000.0


# ── Retry helper ──────────────────────────────────────────────────────────────


def execute_with_retry(
    operation: Callable[[pyodbc.Connection], T],
    *,
    max_retries: int | None = None,
    base_delay_ms: int | None = None,
    max_delay_ms: int | None = None,
) -> T:
    """Execute *operation(conn)* with automatic transient-fault retry.

    On each attempt a **fresh** connection is obtained via ``get_connection()``.
    If a transient ``pyodbc.Error`` is raised the old connection is closed,
    the helper sleeps with exponential back-off + full jitter, then opens a
    new connection and retries.  Permanent errors propagate immediately.

    Parameters
    ----------
    operation:
        Callable that receives a ``pyodbc.Connection`` and returns a result.
    max_retries:
        Override ``settings.sql_max_retries`` (default loaded from env).
    base_delay_ms:
        Override ``settings.sql_base_delay_ms``.
    max_delay_ms:
        Override ``settings.sql_max_delay_ms``.
    """
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.sql_max_retries
    base = base_delay_ms if base_delay_ms is not None else settings.sql_base_delay_ms
    cap = max_delay_ms if max_delay_ms is not None else settings.sql_max_delay_ms

    last_exc: pyodbc.Error | None = None
    conn: pyodbc.Connection | None = None

    for attempt in range(1, retries + 1):
        # Always open a fresh connection (previous one may be stale).
        try:
            conn = get_connection()
        except pyodbc.Error as connect_exc:
            # Connection failure itself may be transient.
            if not _is_transient(connect_exc) or attempt == retries:
                raise
            last_exc = connect_exc
            delay = _backoff_delay(attempt, base, cap)
            logger.warning(
                "Transient connect error (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                retries,
                delay,
                connect_exc,
            )
            time.sleep(delay)
            continue

        try:
            result = operation(conn)
            return result
        except pyodbc.Error as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == retries:
                logger.error(
                    "SQL error (attempt %d/%d, %s): %s",
                    attempt,
                    retries,
                    "max retries reached" if _is_transient(exc) else "non-transient",
                    exc,
                )
                raise
            delay = _backoff_delay(attempt, base, cap)
            logger.warning(
                "Transient SQL error (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                retries,
                delay,
                exc,
            )
            time.sleep(delay)
        finally:
            # Close the connection regardless of success/failure so the next
            # attempt starts with a clean connection.
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    # Should never reach here, but satisfies mypy.
    raise last_exc  # type: ignore[misc]
