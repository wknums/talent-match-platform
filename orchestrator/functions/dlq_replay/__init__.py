"""Manual DLQ drain / replay for the engine SB queues.

Operational tool exposed as HTTP-triggered Functions. Not bound to APIM —
intended to be called from a privileged ops context (e.g., `az functionapp
invoke` or a `curl` with the function key).

Endpoints (under `/api/dlq/`):

- ``POST /api/dlq/peek/{kind}``     — read up to N messages from a DLQ
                                       without consuming them.
- ``POST /api/dlq/replay/{kind}``   — drain DLQ and re-publish to the main
                                       queue. ``kind`` ∈ ``runs`` | ``results``.

Both endpoints accept ``?max=10`` (default 10, capped at 100).
"""


import json
import logging
from typing import Any

import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusSubQueue

from runtime.config import get_settings

logger = logging.getLogger(__name__)

bp = func.Blueprint()


def _resolve_queue(kind: str) -> tuple[str, str]:
    settings = get_settings()
    if kind == "runs":
        return settings.sb_runs_queue, settings.sb_runs_dlq
    if kind == "results":
        return settings.sb_results_queue, settings.sb_results_dlq
    raise ValueError(f"unknown DLQ kind: {kind!r}")


def _sb_client() -> ServiceBusClient:
    from azure.identity import DefaultAzureCredential

    settings = get_settings()
    fqns = (
        settings.sb_namespace
        if settings.sb_namespace.endswith(".servicebus.windows.net")
        else f"{settings.sb_namespace}.servicebus.windows.net"
    )
    return ServiceBusClient(
        fully_qualified_namespace=fqns,
        credential=DefaultAzureCredential(),
    )


@bp.route(route="dlq/peek/{kind}", methods=["POST"])
def http_dlq_peek(req):
    kind = req.route_params.get("kind", "")
    max_n = min(int(req.params.get("max", "10")), 100)
    try:
        main_queue, _ = _resolve_queue(kind)
    except ValueError as exc:
        return func.HttpResponse(status_code=400, body=str(exc))

    peeked: list[dict[str, Any]] = []
    with _sb_client() as sb:
        with sb.get_queue_receiver(
            queue_name=main_queue, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=5
        ) as receiver:
            for msg in receiver.peek_messages(max_message_count=max_n):
                peeked.append(_msg_summary(msg))
    return func.HttpResponse(
        body=json.dumps({"kind": kind, "peeked": peeked}),
        status_code=200,
        mimetype="application/json",
    )


@bp.route(route="dlq/replay/{kind}", methods=["POST"])
def http_dlq_replay(req):
    kind = req.route_params.get("kind", "")
    max_n = min(int(req.params.get("max", "10")), 100)
    try:
        main_queue, _ = _resolve_queue(kind)
    except ValueError as exc:
        return func.HttpResponse(status_code=400, body=str(exc))

    replayed = 0
    failed: list[dict[str, Any]] = []
    with _sb_client() as sb:
        with sb.get_queue_receiver(
            queue_name=main_queue, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=5
        ) as receiver, sb.get_queue_sender(main_queue) as sender:
            messages = receiver.receive_messages(max_message_count=max_n, max_wait_time=5)
            for msg in messages:
                try:
                    body = bytes(msg).decode("utf-8") if msg.body else ""
                    if kind == "results":
                        parsed = _parse_json_payload(body)
                        if not parsed.get("run_id") or not parsed.get("status"):
                            receiver.complete_message(msg)
                            failed.append(
                                {
                                    "message_id": msg.message_id,
                                    "error": "poison message missing run_id/status",
                                }
                            )
                            continue

                    new = ServiceBusMessage(body, content_type=msg.content_type or "application/json")
                    if msg.message_id:
                        new.message_id = msg.message_id
                    if msg.correlation_id:
                        new.correlation_id = msg.correlation_id
                    if getattr(msg, "application_properties", None):
                        new.application_properties = dict(msg.application_properties)  # type: ignore[assignment]
                    sender.send_messages(new)
                    receiver.complete_message(msg)
                    replayed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("DLQ replay failed for message_id=%s", msg.message_id)
                    failed.append({"message_id": msg.message_id, "error": str(exc)})
    return func.HttpResponse(
        body=json.dumps({"kind": kind, "replayed": replayed, "failed": failed}),
        status_code=200,
        mimetype="application/json",
    )


def _msg_summary(msg: Any) -> dict[str, Any]:
    return {
        "message_id": msg.message_id,
        "correlation_id": msg.correlation_id,
        "dead_letter_reason": getattr(msg, "dead_letter_reason", None),
        "dead_letter_error_description": getattr(msg, "dead_letter_error_description", None),
        "enqueued_time_utc": str(getattr(msg, "enqueued_time_utc", "")),
    }


def _parse_json_payload(body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
