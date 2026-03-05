"""OpenTelemetry initialisation – tracing, logging, and metrics with correlationId propagation."""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import-untyped]
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_telemetry(*, service_name: str, otlp_endpoint: str) -> None:
    """Bootstrap OpenTelemetry SDK with OTLP exporter and FastAPI instrumentation.

    Call once at application startup (lifespan hook).
    """
    resource = Resource.create({"service.name": service_name})

    provider = TracerProvider(resource=resource)

    # OTLP gRPC exporter (App Insights via OTEL collector, or direct)
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP exporter configured → %s", otlp_endpoint)
        except ImportError:
            logger.warning("opentelemetry-exporter-otlp not installed; skipping OTLP export")

    # Azure Monitor exporter (optional, if connection string is set)
    try:
        import os

        conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
        if conn_str:
            from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter  # type: ignore[import-untyped]

            az_exporter = AzureMonitorTraceExporter(connection_string=conn_str)
            provider.add_span_processor(BatchSpanProcessor(az_exporter))
            logger.info("Azure Monitor exporter configured")
    except ImportError:
        logger.debug("azure-monitor-opentelemetry-exporter not installed; skipping")

    trace.set_tracer_provider(provider)

    # Instrument FastAPI (auto-injects span context on each request)
    FastAPIInstrumentor.instrument()

    # Configure structured JSON logging
    _configure_json_logging()


def _configure_json_logging() -> None:
    """Set up JSON-formatted logging with correlation-id in every record."""
    import json as _json
    import sys

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            from api.deps import get_correlation_id

            log_obj: dict[str, Any] = {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "correlationId": get_correlation_id(),
            }
            if record.exc_info and record.exc_info[1]:
                log_obj["exception"] = self.formatException(record.exc_info)
            return _json.dumps(log_obj)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
