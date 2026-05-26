"""Orchestrator-internal payload types.

The platform dispatches per-run work to the engine via Service Bus
(``orchestrator.sb_contracts.RunMessage``). These types are used only between
the FastAPI layer, the orchestrator, and its activities.
"""

from __future__ import annotations

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
