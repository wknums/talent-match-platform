"""Pydantic-settings based configuration – environment variables only, no secrets in code."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded exclusively from environment variables."""

    # ── Authentication ────────────────────────────────────────────────────────
    auth_required: bool = False
    aad_issuer: str = ""
    aad_audience: str = ""

    # ── Functions host (Durable) ──────────────────────────────────────────────
    functions_host_url: str = "http://localhost:7071"
    functions_host_key: str = ""
    functions_http_timeout_s: float = 10.0

    # ── Service Bus (Platform ↔ Engine dispatch) ──────────────────────────────
    # Platform publishes `RunMessage` to `sb_runs_queue` and receives
    # `RunResultMessage` from `sb_results_queue` when ENGINE_REPORT_MODE=servicebus.
    # Sequential / low-volume client↔engine traffic bypasses the platform entirely.
    sb_namespace: str = ""
    sb_runs_queue: str = "engine-runs"
    sb_results_queue: str = "engine-results"
    sb_runs_dlq: str = "engine-runs/$DeadLetterQueue"
    sb_results_dlq: str = "engine-results/$DeadLetterQueue"

    # ── Engine result-report mode ─────────────────────────────────────────────
    # `servicebus` → engine writes results to `sb_results_queue`.
    # `http`       → engine PATCH /runs/{runId} back to the platform.
    engine_report_mode: Literal["servicebus", "http"] = "servicebus"

    # ── Storage (CV refs + batch results, MI auth, no SAS) ────────────────────
    blob_account: str = ""
    blob_container: str = "cv-uploads"
    blob_results_container: str = "batch-results"

    # ── Observability ─────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    applicationinsights_connection_string: str = ""

    # ── Live progress projection ──────────────────────────────────────────────
    live_progress_enabled: bool = False
    live_progress_target: str = "batchProgress"
    live_progress_group_prefix: str = "submission"
    live_progress_timeout_s: float = 5.0
    signalr_connection_string: str = ""
    signalr_service_endpoint: str = ""
    signalr_token_scope: str = "https://signalr.azure.com/.default"
    signalr_hub_name: str = "batch-progress"

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance (cached)."""
    return Settings()
