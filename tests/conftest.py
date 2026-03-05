"""Shared pytest fixtures — disable telemetry for unit tests."""

import os

# Disable OTLP exporter during tests to prevent gRPC connection hang
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"] = ""
