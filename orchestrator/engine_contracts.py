"""Orchestrator-internal payload types.

The platform dispatches per-run work to the engine via Service Bus
(``orchestrator.sb_contracts.RunMessage``). These types are used only between
the FastAPI layer, the orchestrator, and its activities.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BatchPayload(BaseModel):
    """Top-level orchestrator input — what FastAPI POSTs to /api/orchestration/start."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    batch_id: str = Field(..., alias="batchId")
    job_id: str = Field(..., alias="jobId")
    prompt_version_id: str = Field(..., alias="promptVersionId")
    run_count: int = Field(..., alias="runCount", ge=1)
    prompt: dict[str, Any]
    cvs: list[dict[str, Any]]


class DispatchRunInput(BaseModel):
    """Input to the ``dispatch_run`` activity (one CV × one run)."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    job_id: str
    run_id: str
    application_id: str
    document_id: str
    file_name: str
    mime_type: str
    blob_uri: str
    sha256: str
    run_index: int = Field(ge=0)
    prompt_blob_uri: str
    correlation_id: str
    traceparent: str = ""


class FinalizeBatchInput(BaseModel):
    """Input to the ``finalize_batch`` activity."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    cvs: list[dict[str, Any]]
    run_results: list[dict[str, Any]]


def normalize_completion_payload(payload: Any) -> dict[str, Any]:
    """Normalize completion payloads from HTTP/SB into a canonical dict.

    Supports dict payloads, JSON strings, and UTF-8 encoded bytes. Common
    field aliases are normalized to snake_case used by internal contracts.
    """
    value: Any = payload
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("completion payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("completion payload must be a JSON object")

    normalized = dict(value)
    aliases = {
        "runId": "run_id",
        "durationMs": "duration_ms",
        "tokensPrompt": "tokens_prompt",
        "tokensCompletion": "tokens_completion",
        "errorMessage": "error_message",
        "correlationId": "correlation_id",
        "traceParent": "traceparent",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    return normalized
