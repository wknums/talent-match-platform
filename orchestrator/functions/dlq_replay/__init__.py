"""DLQ replay utility – reads dead-letter messages and re-enqueues them.

Designed to run as a timer-triggered or manually triggered Azure Function.
"""

from __future__ import annotations

import logging
from typing import Any

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode

from runtime.config import get_settings

logger = logging.getLogger(__name__)

app = func.FunctionApp()


@app.route(route="dlq-replay", methods=["POST"])
def dlq_replay(req: func.HttpRequest) -> func.HttpResponse:
    """Manually triggered DLQ replay.

    Reads up to *max_messages* from the dead-letter sub-queue and re-sends them
    to the main queue for reprocessing.
    """
    settings = get_settings()
    max_messages = int(req.params.get("max", "10"))
    credential = DefaultAzureCredential()

    replayed = 0
    with ServiceBusClient(
        fully_qualified_namespace=settings.sb_namespace,
        credential=credential,
    ) as client:
        dlq_receiver = client.get_queue_receiver(
            queue_name=settings.sb_queue,
            sub_queue=ServiceBusReceiveMode.DEAD_LETTER,  # type: ignore[arg-type]
            max_wait_time=5,
        )
        sender = client.get_queue_sender(queue_name=settings.sb_queue)

        with dlq_receiver, sender:
            for msg in dlq_receiver:
                if replayed >= max_messages:
                    break
                body = str(msg)
                sender.send_messages(ServiceBusMessage(body=body, content_type="application/json"))
                dlq_receiver.complete_message(msg)
                replayed += 1
                logger.info("Replayed DLQ message: %s", msg.message_id)

    return func.HttpResponse(f"Replayed {replayed} messages", status_code=200)
