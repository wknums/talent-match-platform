"""Routes implementing the platform-mode contract: /assess/batch.

See ``specs/002-platform-mode-shift/platform-contract.md``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Request, status
from fastapi.responses import JSONResponse

from api import durable_client
from api.auth import require_auth
from api.models import (
    BatchError,
    BatchProgress,
    BatchResult,
    BatchStatus,
    BatchStatusResponse,
    BatchSubmitRequest,
    BatchSubmitResponse,
    CancelResponse,
    CvResult,
)
from runtime.errors import ProblemDetail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assess", tags=["assess"])


# ── POST /assess/batch ───────────────────────────────────────────────────────
@router.post(
    "/batch",
    response_model=BatchSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a batch of CVs for scoring (platform mode).",
)
async def submit_batch(
    body: BatchSubmitRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    _claims: dict[str, Any] = Depends(require_auth),
) -> BatchSubmitResponse:
    if idempotency_key != str(body.batch_id):
        raise ProblemDetail(
            status=400,
            title="Idempotency-Key mismatch",
            detail="Idempotency-Key header must equal body.batchId.",
        )

    submission_id = str(body.batch_id)
    correlation_id = request.headers.get("x-correlation-id", "")
    traceparent = request.headers.get("traceparent", "")
    payload = body.model_dump(mode="json", by_alias=True)

    try:
        await durable_client.start_batch(
            instance_id=submission_id,
            payload=payload,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )
    except durable_client.OrchestrationConflictError as exc:
        raise ProblemDetail(
            status=409,
            title="Idempotency conflict",
            detail="A different submission already exists for this batchId.",
        ) from exc

    return BatchSubmitResponse(
        submission_id=submission_id,
        status=BatchStatus.QUEUED,
        poll_url=f"/assess/batch/{submission_id}/status",
        estimated_completion_seconds=max(60, len(body.cvs) * body.run_count * 20),
    )


# ── GET /assess/batch/{submissionId}/status ──────────────────────────────────
@router.get(
    "/batch/{submission_id}/status",
    response_model=BatchStatusResponse,
    summary="Poll batch status (platform mode).",
)
async def get_batch_status(
    submission_id: str = Path(..., min_length=1, max_length=128),
) -> BatchStatusResponse:
    try:
        raw = await durable_client.get_batch_status(instance_id=submission_id)
    except durable_client.DurableClientError as exc:
        if exc.status_code == 404:
            # Fallback: Durable history may have been purged. The result blob
            # outlives Durable state — if it exists, the batch completed.
            blob_result = durable_client.read_batch_result_from_blob(
                instance_id=submission_id
            )
            if blob_result is not None:
                raw = {
                    "status": "completed",
                    "progress": None,
                    "result": blob_result,
                    "error": None,
                    "retryAfterSeconds": None,
                }
            else:
                raise ProblemDetail(
                    status=404,
                    title="Not Found",
                    detail=f"submissionId {submission_id} not found.",
                ) from exc
        else:
            raise ProblemDetail(status=502, title="Upstream error", detail=str(exc)) from exc

    return _to_status_response(submission_id, raw)


# ── POST /assess/batch/{submissionId}/cancel ─────────────────────────────────
@router.post(
    "/batch/{submission_id}/cancel",
    response_model=CancelResponse,
    summary="Request cancellation of an in-flight batch.",
)
async def cancel_batch(
    submission_id: str = Path(..., min_length=1, max_length=128),
    _claims: dict[str, Any] = Depends(require_auth),
) -> JSONResponse:
    try:
        result = await durable_client.cancel_batch(
            instance_id=submission_id,
            reason="client requested cancel",
        )
    except durable_client.DurableClientError as exc:
        raise ProblemDetail(status=502, title="Upstream error", detail=str(exc)) from exc

    http_status = result.pop("_http_status", 202)
    if http_status == 409:
        return JSONResponse(
            status_code=409,
            content=CancelResponse(status=BatchStatus.COMPLETED).model_dump(),
        )
    if http_status == 200:
        return JSONResponse(
            status_code=200,
            content=CancelResponse(status=BatchStatus.CANCELLED).model_dump(),
        )
    return JSONResponse(
        status_code=202,
        content=CancelResponse(status=BatchStatus.CANCELLING).model_dump(),
    )


# ── helpers ──────────────────────────────────────────────────────────────────
def _to_status_response(submission_id: str, raw: dict[str, Any]) -> BatchStatusResponse:
    progress = None
    if raw.get("progress"):
        progress = BatchProgress(**raw["progress"])

    result = None
    if raw.get("result"):
        cvs = [CvResult(**cv) for cv in raw["result"].get("cvs", [])]
        result = BatchResult(cvs=cvs)

    error = None
    if raw.get("error"):
        error = BatchError(**raw["error"])

    return BatchStatusResponse(
        submission_id=submission_id,
        status=BatchStatus(raw["status"]),
        progress=progress,
        estimated_completion_seconds=raw.get("estimatedCompletionSeconds"),
        retry_after_seconds=raw.get("retryAfterSeconds", 10),
        result=result,
        error=error,
    )
