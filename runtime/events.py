"""Live progress event payloads and SignalR projection helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable

import httpx
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from opentelemetry import metrics as _otel_metrics
from opentelemetry import trace as _otel_trace
from opentelemetry.trace import Link, SpanContext, TraceFlags

from runtime.config import get_settings

logger = logging.getLogger(__name__)
_tracer = _otel_trace.get_tracer(__name__)
_meter = _otel_metrics.get_meter(__name__)
_events_built = _meter.create_counter("awr.live_progress.events_built")
_events_projected = _meter.create_counter("awr.live_progress.events_projected")


def build_live_progress_event(
    *,
    event_type: str,
    progress: dict[str, Any],
    occurred_at: str,
    sequence: int,
    correlation_id: str,
    traceparent: str,
    run_id: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    batch_id = str(progress.get("batchId") or progress.get("submissionId") or "")
    application, run = _find_application_run(progress, run_id)
    event_artifacts = artifacts if artifacts is not None else (run.get("artifacts") if run else None) or []

    event = {
        "specVersion": "awr.platform.progress.v1",
        "eventType": event_type,
        "sequence": sequence,
        "occurredAt": occurred_at,
        "submission": {
            "submissionId": progress.get("submissionId") or batch_id,
            "batchId": batch_id,
            "jobId": progress.get("jobId"),
            "status": progress.get("status"),
        },
        "application": (
            {
                "applicationId": application.get("applicationId"),
                "documentId": application.get("documentId"),
                "status": application.get("status"),
            }
            if application
            else None
        ),
        "run": (
            {
                "runId": run.get("runId") or run_id,
                "runIndex": run.get("runIndex"),
                "status": run.get("status"),
                "artifactCount": run.get("artifactCount"),
            }
            if run or run_id
            else None
        ),
        "progress": {
            "status": progress.get("status"),
            "cvsCompleted": progress.get("cvsCompleted"),
            "cvsTotal": progress.get("cvsTotal"),
            "runsCompleted": progress.get("runsCompleted"),
            "runsDispatched": progress.get("runsDispatched"),
            "runsTotal": progress.get("runsTotal"),
            "lastUpdatedAt": progress.get("lastUpdatedAt"),
        },
        "artifacts": event_artifacts,
        "trace": {
            "correlationId": correlation_id,
            "traceparent": traceparent,
        },
        "fallback": {
            "mode": "poll",
            "pollUrl": f"/assess/batch/{batch_id}/status",
        },
    }
    _events_built.add(1, {"event_type": event_type})
    logger.info(
        "built live progress event event_type=%s batch_id=%s run_id=%s correlation_id=%s",
        event_type,
        batch_id,
        run_id or "",
        correlation_id,
    )
    return event


def project_live_progress_event(event: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    trace = event.get("trace") or {}
    traceparent = str(trace.get("traceparent") or "")
    correlation_id = str(trace.get("correlationId") or "")
    batch_id = str(((event.get("submission") or {}).get("batchId")) or "")
    links = _links_from_traceparent(traceparent)

    with _tracer.start_as_current_span("live_progress.project", links=links) as span:
        span.set_attribute("awr.batch_id", batch_id)
        span.set_attribute("awr.correlation_id", correlation_id)
        span.set_attribute("awr.event_type", str(event.get("eventType") or ""))

        if not settings.live_progress_enabled:
            outcome = {"projected": False, "reason": "disabled", "transport": "poll"}
            _record_projection_outcome(outcome)
            logger.info("live progress projection disabled for batch_id=%s", batch_id)
            return outcome

        endpoint, access_key = _resolve_signalr_endpoint(settings)
        if not endpoint:
            outcome = {"projected": False, "reason": "not-configured", "transport": "poll"}
            _record_projection_outcome(outcome)
            logger.info("live progress projection not configured for batch_id=%s", batch_id)
            return outcome

        group = f"{settings.live_progress_group_prefix}:{batch_id}"
        url = f"{endpoint}/api/v1/hubs/{settings.signalr_hub_name}/groups/{group}"
        body = {"target": settings.live_progress_target, "arguments": [event]}

        try:
            bearer_token = _build_signalr_bearer_token(
                url=url,
                access_key=access_key,
                token_scope=settings.signalr_token_scope,
            )
            _post_to_signalr_group(url=url, bearer_token=bearer_token, body=body)
        except (AzureError, httpx.HTTPError) as exc:
            span.record_exception(exc)
            outcome = {"projected": False, "reason": "signalr-error", "transport": "poll"}
            _record_projection_outcome(outcome)
            logger.warning("live progress projection failed for batch_id=%s: %s", batch_id, exc)
            return outcome

        outcome = {"projected": True, "transport": "signalr"}
        _record_projection_outcome(outcome)
        logger.info("live progress projected to SignalR for batch_id=%s", batch_id)
        return outcome


def _find_application_run(
    progress: dict[str, Any], run_id: str | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not run_id:
        return None, None

    for application in progress.get("applications", []):
        for run in application.get("runs", []):
            if run.get("runId") == run_id:
                return application, run
    return None, None


def _parse_signalr_connection_string(connection_string: str) -> tuple[str, str]:
    parts: dict[str, str] = {}
    for part in connection_string.split(";"):
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        parts[key] = value
    return parts.get("Endpoint", "").rstrip("/"), parts.get("AccessKey", "")


def _resolve_signalr_endpoint(settings: Any) -> tuple[str, str]:
    endpoint, access_key = _parse_signalr_connection_string(settings.signalr_connection_string)
    if endpoint:
        return endpoint, access_key
    return settings.signalr_service_endpoint.rstrip("/"), ""


def _build_signalr_bearer_token(*, url: str, access_key: str, token_scope: str) -> str:
    if not access_key:
        return _build_signalr_managed_identity_bearer_token(token_scope=token_scope)

    header = _base64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _base64url_json({"aud": url, "exp": int(time.time()) + 300})
    signing_input = f"{header}.{payload}".encode("utf-8")
    signature = hmac.new(access_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_base64url(signature)}"


def _build_signalr_managed_identity_bearer_token(*, token_scope: str) -> str:
    credential = DefaultAzureCredential()
    return credential.get_token(token_scope).token


def _base64url_json(value: dict[str, Any]) -> str:
    return _base64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _post_to_signalr_group(*, url: str, bearer_token: str, body: dict[str, Any]) -> None:
    settings = get_settings()
    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=settings.live_progress_timeout_s,
    )
    response.raise_for_status()


def _record_projection_outcome(outcome: dict[str, Any]) -> None:
    _events_projected.add(
        1,
        {
            "projected": str(bool(outcome.get("projected"))).lower(),
            "transport": str(outcome.get("transport") or ""),
            "reason": str(outcome.get("reason") or "none"),
        },
    )


def _parse_traceparent(tp: str) -> SpanContext | None:
    if not tp:
        return None
    parts = tp.split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None
    try:
        trace_id = int(parts[1], 16)
        span_id = int(parts[2], 16)
        flags = int(parts[3], 16)
    except ValueError:
        return None
    if trace_id == 0 or span_id == 0:
        return None
    return SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(flags),
    )


def _links_from_traceparent(tp: str) -> list[Link]:
    ctx = _parse_traceparent(tp)
    return [Link(ctx)] if ctx is not None else []