"""Result intake from the engine — two paths, one effect.

Both paths look up ``run-index/{run_id}.json`` in ``BLOB_RESULTS_CONTAINER``
to recover the owning batch's Durable orchestration instance, then raise the
external event ``run-{run_id}`` so the orchestrator's ``task_all`` advances.

- ``sb_result_handler``: triggered on Service Bus queue ``engine-results``
   when the engine wrapper runs with ``REPORT_MODE=servicebus``.
- ``http_patch_run``: HTTP ``PATCH /api/runs/{run_id}`` when the engine
   wrapper runs with ``REPORT_MODE=http``.
"""


import json
import logging
from typing import Any

import azure.durable_functions as df  # type: ignore[import-untyped]
import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from opentelemetry import trace as _otel_trace
from opentelemetry.trace import Link, SpanContext, TraceFlags

from orchestrator.engine_contracts import normalize_completion_payload
from orchestrator.sb_contracts import FinishRunRequest, RunResultMessage
from runtime.config import get_settings
from runtime.events import extract_trace_metadata
from runtime.telemetry import log_lifecycle_event

logger = logging.getLogger(__name__)
_tracer = _otel_trace.get_tracer(__name__)

bp = df.Blueprint()


# ── Service Bus trigger ──────────────────────────────────────────────────────
@bp.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%SB_RESULTS_QUEUE%",
    connection="SbConnection",
)
@bp.durable_client_input(client_name="client")
async def sb_result_handler(
    msg,
    client,
):
    body = msg.get_body().decode("utf-8")
    try:
        normalized_body = normalize_completion_payload(body)
        result = RunResultMessage.model_validate(normalized_body)
    except Exception:
        logger.exception("invalid RunResultMessage body; dead-lettering by exception")
        raise

    batch_id = _lookup_batch_id(result.run_id)
    if batch_id is None:
        logger.warning("no run-index for run_id=%s; ignoring", result.run_id)
        return  # ack and drop; not our message

    app_props = getattr(msg, "application_properties", None) or {}
    _, traceparent = extract_trace_metadata(
        application_properties=app_props,
        payload=result.model_dump(mode="json"),
    )
    if not _claim_result_delivery(
        batch_id=batch_id,
        run_id=result.run_id,
        correlation_id=result.correlation_id or "",
        traceparent=traceparent,
    ):
        logger.info("duplicate SB result delivery ignored for run_id=%s", result.run_id)
        return

    links = _links_from_traceparent(traceparent)
    with _tracer.start_as_current_span("result_intake.sb", links=links) as span:
        span.set_attribute("awr.run_id", result.run_id)
        span.set_attribute("awr.batch_id", batch_id)
        span.set_attribute("awr.correlation_id", result.correlation_id or "")
        span.set_attribute("awr.run.status", result.status)
        log_lifecycle_event(
            stage="result_intake.sb",
            status=result.status,
            batch_id=batch_id,
            run_id=result.run_id,
            correlation_id=result.correlation_id or "",
            traceparent=traceparent,
        )

        event_payload = result.model_dump(mode="json")
        if traceparent:
            event_payload["traceparent"] = traceparent

        await client.raise_event(
            batch_id,
            f"run-{result.run_id}",
            event_payload,
        )


# ── HTTP PATCH fallback ──────────────────────────────────────────────────────
@bp.route(route="runs/{run_id}", methods=["PATCH"])
@bp.durable_client_input(client_name="client")
async def http_patch_run(
    req,
    client,
):
    run_id = req.route_params.get("run_id", "")
    if not run_id:
        return func.HttpResponse(status_code=400, body="run_id required")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(status_code=400, body="invalid json")

    try:
        normalized_body = normalize_completion_payload(body)
    except (TypeError, ValueError):
        return func.HttpResponse(status_code=400, body="invalid json")

    try:
        finish = FinishRunRequest.model_validate(normalized_body)
    except Exception as exc:
        return func.HttpResponse(status_code=400, body=f"invalid FinishRunRequest: {exc}")

    batch_id = _lookup_batch_id(run_id)
    if batch_id is None:
        return func.HttpResponse(status_code=404, body="unknown run_id")

    correlation_id, traceparent = extract_trace_metadata(
        headers=dict(req.headers),
        payload=normalized_body,
    )
    if not _claim_result_delivery(
        batch_id=batch_id,
        run_id=run_id,
        correlation_id=correlation_id,
        traceparent=traceparent,
    ):
        logger.info("duplicate HTTP result delivery ignored for run_id=%s", run_id)
        return func.HttpResponse(status_code=202)

    links = _links_from_traceparent(traceparent)
    with _tracer.start_as_current_span("result_intake.http", links=links) as span:
        span.set_attribute("awr.run_id", run_id)
        span.set_attribute("awr.batch_id", batch_id)
        span.set_attribute("awr.correlation_id", correlation_id)
        span.set_attribute("awr.run.status", finish.status)
        log_lifecycle_event(
            stage="result_intake.http",
            status=finish.status,
            batch_id=batch_id,
            run_id=run_id,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )

        # Shape the FinishRunRequest into the RunResultMessage shape consumed by
        # the orchestrator's finalize step.
        payload: dict[str, Any] = {
            "run_id": run_id,
            "status": finish.status,
            "duration_ms": finish.duration_ms,
            "tokens_prompt": finish.tokens_prompt,
            "tokens_completion": finish.tokens_completion,
            "error_message": finish.error_message,
            "correlation_id": correlation_id,
            "artifacts": (
                [a.model_dump(mode="json") for a in finish.artifacts]
                if finish.artifacts
                else None
            ),
        }
        if traceparent:
            payload["traceparent"] = traceparent
        await client.raise_event(batch_id, f"run-{run_id}", payload)
        return func.HttpResponse(status_code=202)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _parse_traceparent(tp: str) -> SpanContext | None:
    """Decode a W3C ``traceparent`` into a remote SpanContext, or None."""
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


def _coerce_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(v)


def _lookup_batch_id(run_id: str) -> str | None:
    """Read ``batches/*/run-index/{run_id}.json`` to recover the owning batch.

    The blob path encodes the batch but we don't know which yet, so we use
    the run-index blob list-by-name trick: blob names are
    ``batches/{batchId}/run-index/{run_id}.json``. We list blobs by suffix
    via a `find_blobs_by_tags` style query — too heavy. Instead the orchestrator
    writes a flat companion index at ``run-index/{run_id}.json`` so lookup is
    O(1).
    """
    settings = get_settings()
    account = settings.blob_account
    container = settings.blob_results_container
    if not account:
        logger.error("BLOB_ACCOUNT not configured; cannot look up run_id=%s", run_id)
        return None

    url = (
        account if account.startswith("https://")
        else f"https://{account}.blob.core.windows.net"
    )
    from azure.identity import DefaultAzureCredential

    svc = BlobServiceClient(account_url=url, credential=DefaultAzureCredential())
    blob = svc.get_blob_client(container=container, blob=f"run-index/{run_id}.json")
    try:
        data = blob.download_blob().readall()
    except ResourceNotFoundError:
        return None
    try:
        return json.loads(data).get("batchId")
    except json.JSONDecodeError:
        logger.exception("corrupt run-index blob for run_id=%s", run_id)
        return None


def _claim_result_delivery(
    *,
    batch_id: str,
    run_id: str,
    correlation_id: str,
    traceparent: str,
) -> bool:
    """Claim first delivery of a run result using a blob marker.

    Duplicate deliveries are expected under at-least-once transports. The first
    successful writer wins; later duplicates are acknowledged and dropped.
    """
    settings = get_settings()
    account = settings.blob_account
    container = settings.blob_results_container
    if not account:
        logger.warning("BLOB_ACCOUNT not configured; duplicate protection disabled for run_id=%s", run_id)
        return True

    url = account if account.startswith("https://") else f"https://{account}.blob.core.windows.net"
    from azure.identity import DefaultAzureCredential

    svc = BlobServiceClient(account_url=url, credential=DefaultAzureCredential())
    blob = svc.get_blob_client(container=container, blob=f"result-delivery/{run_id}.json")
    marker = json.dumps(
        {
            "batchId": batch_id,
            "runId": run_id,
            "correlationId": correlation_id,
            "traceparent": traceparent,
        }
    ).encode("utf-8")
    try:
        blob.upload_blob(marker, overwrite=False)
        return True
    except ResourceExistsError:
        return False
