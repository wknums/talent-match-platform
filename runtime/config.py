"""Pydantic-settings based configuration – environment variables only, no secrets in code."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded exclusively from environment variables."""

    # ── Authentication ────────────────────────────────────────────────────────
    auth_required: bool = False
    aad_issuer: str = ""
    aad_audience: str = ""

    # ── Azure SQL (passwordless) ──────────────────────────────────────────────
    sql_server: str = "localhost"
    sql_database: str = "awrplatform"
    sql_odbc_driver: str = "ODBC Driver 18 for SQL Server"
    sql_connection_timeout: int = 30
    sql_command_timeout: int = 60
    sql_max_retries: int = 6
    sql_base_delay_ms: int = 500
    sql_max_delay_ms: int = 60_000

    # ── Service Bus ───────────────────────────────────────────────────────────
    sb_namespace: str = ""
    sb_queue: str = "engine-runs"
    sb_dlq: str = "engine-runs/$deadletterqueue"

    # ── Observability ─────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    applicationinsights_connection_string: str = ""

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance (cached)."""
    return Settings()
