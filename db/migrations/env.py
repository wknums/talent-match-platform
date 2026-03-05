"""Alembic env.py – uses pyodbc + DefaultAzureCredential (token auth) for Azure SQL.

This file is executed by Alembic during migration operations.  It builds a
connection string *without* UID/PWD and injects the Entra access token via the
ODBC ``attrs_before`` mechanism (SQL_COPT_SS_ACCESS_TOKEN = 1256).
"""

from __future__ import annotations

import struct
from logging.config import fileConfig

from alembic import context
from azure.identity import DefaultAzureCredential

from runtime.config import get_settings

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy MetaData needed – we use raw SQL migrations.
target_metadata = None

# ── Helpers ───────────────────────────────────────────────────────────────────

_SQL_TOKEN_URL = "https://database.windows.net/.default"
SQL_COPT_SS_ACCESS_TOKEN = 1256


def _get_token_struct() -> bytes:
    credential = DefaultAzureCredential()
    token = credential.get_token(_SQL_TOKEN_URL).token
    token_bytes = token.encode("UTF-16-LE")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def _build_connection_string() -> str:
    settings = get_settings()
    return (
        f"DRIVER={{{settings.sql_odbc_driver}}};"
        f"SERVER={settings.sql_server};"
        f"DATABASE={settings.sql_database};"
        f"Encrypt=yes;TrustServerCertificate=no;"
        f"Connection Timeout={settings.sql_connection_timeout};"
    )


# ── Offline mode (generates SQL script) ──────────────────────────────────────

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode – emit SQL to stdout."""
    context.configure(
        url=_build_connection_string(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (applies to live DB) ─────────────────────────────────────────

def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live Azure SQL database."""
    import pyodbc

    conn_str = _build_connection_string()
    token_struct = _get_token_struct()

    connection = pyodbc.connect(
        conn_str,
        attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct},
        autocommit=True,
    )

    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()

    connection.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
