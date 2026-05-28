"""HTTP client for the platform's Azure Functions host (Durable Functions).

FastAPI is the public API surface (per APIM). The orchestration runs in a
separate Functions process. This module is the only place that knows how to
talk to that process.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from runtime.config import get_settings

logger = logging.getLogger(__name__)


class DurableClientError(RuntimeError):
    """Raised when the Functions host returns an unexpected error."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"functions host returned {status_code}: {body!r}")
        self.status_code = status_code
        self.body = body


class OrchestrationConflictError(DurableClientError):
    """Raised when a start request collides with an existing different submission."""


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.functions_host_url,
        timeout=settings.functions_http_timeout_s,
        headers=(
            {"x-functions-key": settings.functions_host_key}
            if settings.functions_host_key
            else {}
        ),
    )


async def start_batch(
    *,
    instance_id: str,
    payload: dict[str, Any],
    correlation_id: str,
    traceparent: str = "",
) -> None:
    """Start (or attach to) a batch orchestration with a client-supplied instance id.

    Idempotent on ``instance_id``: if an orchestration with that id already exists
    the Functions host returns 200; if a different submission collided on the id
    the host returns 409 and this raises ``OrchestrationConflictError``.
    """
    headers: dict[str, str] = {"x-correlation-id": correlation_id}
    if traceparent:
        headers["traceparent"] = traceparent
    try:
        async with _client() as http:
            resp = await http.post(
                "/api/orchestration/start",
                json={"instance_id": instance_id, "payload": payload},
                headers=headers,
            )
            if resp.status_code == 409:
                raise OrchestrationConflictError(resp.status_code, resp.text)
            if resp.status_code >= 400:
                raise DurableClientError(resp.status_code, resp.text)
    except (httpx.HTTPError, ValueError) as exc:
        # Transport/config failures must surface as upstream errors, not 500s.
        raise DurableClientError(502, str(exc)) from exc


async def get_batch_status(*, instance_id: str) -> dict[str, Any]:
    """Return normalised status dict from the Functions host.

    Shape: ``{ "status": "queued|running|completed|failed|cancelled",
               "progress": {"cvsCompleted": int, "cvsTotal": int} | None,
               "result": {...} | None,
               "error": {"code": str, "message": str} | None }``
    """
    async with _client() as http:
        resp = await http.get(f"/api/orchestration/{instance_id}")
        if resp.status_code == 404:
            raise DurableClientError(404, "not found")
        if resp.status_code >= 400:
            raise DurableClientError(resp.status_code, resp.text)
        return resp.json()  # type: ignore[no-any-return]


async def cancel_batch(*, instance_id: str, reason: str) -> dict[str, Any]:
    """Request cancellation of an in-flight batch.

    Returns the current normalised status. The Functions host should:
    - 202 if cancellation was requested (status -> cancelling)
    - 200 if already cancelled (terminal)
    - 409 if already completed (too late)
    """
    async with _client() as http:
        resp = await http.post(
            f"/api/orchestration/{instance_id}/terminate",
            json={"reason": reason},
        )
        if resp.status_code >= 500:
            raise DurableClientError(resp.status_code, resp.text)
        body: dict[str, Any] = resp.json() if resp.content else {}
        body["_http_status"] = resp.status_code
        return body


def read_batch_result_from_blob(*, instance_id: str) -> dict[str, Any] | None:
    """Read ``batches/{instance_id}/result.json`` from the results container.

    Used as a fallback when Durable history has been purged but the batch
    finished successfully and its result blob persists.
    """
    settings = get_settings()
    if not settings.blob_account:
        return None
    url = (
        settings.blob_account
        if settings.blob_account.startswith("https://")
        else f"https://{settings.blob_account}.blob.core.windows.net"
    )
    svc = BlobServiceClient(account_url=url, credential=DefaultAzureCredential())
    blob = svc.get_blob_client(
        container=settings.blob_results_container,
        blob=f"batches/{instance_id}/result.json",
    )
    try:
        data = blob.download_blob().readall()
    except ResourceNotFoundError:
        return None
    try:
        return json.loads(data)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.exception("corrupt result blob for instance_id=%s", instance_id)
        return None
