"""Fan-out / fan-in Durable Functions orchestrator and activity.

Enqueues N run messages to Service Bus for Engine workers in a separate repo.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import azure.durable_functions as df  # type: ignore[import-untyped]
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from orchestrator.sb_contracts import RunMessage
from runtime.config import get_settings

logger = logging.getLogger(__name__)

app = func.FunctionApp()

# ── Durable orchestrator ──────────────────────────────────────────────────────

@app.orchestration_trigger(context_name="context")
def fanout_orchestrator(context: df.DurableOrchestrationContext) -> list[str]:  # type: ignore[no-any-unimported]
    """Fan-out: enqueue each run message as a parallel activity."""
    input_payload: dict[str, Any] = context.get_input()  # type: ignore[assignment]
    run_messages: list[dict[str, Any]] = input_payload.get("runs", [])

    tasks = [context.call_activity("enqueue_run", msg) for msg in run_messages]
    results: list[str] = yield context.task_all(tasks)  # type: ignore[assignment]
    return results


# ── Activity: send a single message to Service Bus ───────────────────────────

@app.activity_trigger(input_name="payload")
def enqueue_run(payload: dict[str, Any]) -> str:
    """Send a single RunMessage to the Service Bus queue.

    Uses DefaultAzureCredential (Managed Identity in Azure, az-login locally).
    """
    settings = get_settings()
    msg = RunMessage(**payload)

    credential = DefaultAzureCredential()
    with ServiceBusClient(
        fully_qualified_namespace=settings.sb_namespace,
        credential=credential,
    ) as client:
        with client.get_queue_sender(queue_name=settings.sb_queue) as sender:
            sb_msg = ServiceBusMessage(
                body=msg.model_dump_json(),
                message_id=msg.message_id,
                correlation_id=msg.correlation_id,
                content_type="application/json",
            )
            sender.send_messages(sb_msg)

    logger.info("Enqueued run_id=%s to %s", msg.run_id, settings.sb_queue)
    return str(msg.run_id)


# ── HTTP starter (triggers the orchestrator) ──────────────────────────────────

@app.route(route="orchestrate", methods=["POST"])
@app.durable_client_input(client_name="starter")
async def http_start(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    """HTTP trigger that starts the fan-out orchestrator."""
    client = df.DurableOrchestrationClient(starter)
    body = req.get_json()
    instance_id = await client.start_new("fanout_orchestrator", client_input=body)
    logger.info("Started orchestration %s", instance_id)
    return client.create_check_status_response(req, instance_id)
