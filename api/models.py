"""Pydantic models for the platform-mode contract.

Wire shape per ``specs/002-platform-mode-shift/platform-contract.md`` (mirror of
the client's ``specs/008-platform-mode-shift/platform-contract.md``).
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# ── Submission status ────────────────────────────────────────────────────────
class BatchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


# ── Submit request (POST /assess/batch) ──────────────────────────────────────
class InlinePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["inline"] = "inline"
    text: str = Field(..., min_length=1)


class CvRef(BaseModel):
    """A CV passed by reference (blob URI)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    application_id: str = Field(..., alias="applicationId", min_length=1, max_length=64)
    document_id: str = Field(..., alias="documentId", min_length=1, max_length=64)
    file_name: str = Field(..., alias="fileName", min_length=1, max_length=500)
    mime_type: str = Field(..., alias="mimeType", min_length=1, max_length=100)
    blob_uri: HttpUrl = Field(..., alias="blobUri")
    sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class BatchSubmitRequest(BaseModel):
    """POST /assess/batch body."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    batch_id: uuid.UUID = Field(..., alias="batchId")
    job_id: str = Field(..., alias="jobId", min_length=1, max_length=64)
    prompt_version_id: str = Field(..., alias="promptVersionId", min_length=1, max_length=64)
    run_count: int = Field(..., alias="runCount", ge=1, le=10)
    prompt: InlinePrompt
    cvs: list[CvRef] = Field(..., min_length=1, max_length=100)
    callback_url: HttpUrl | None = Field(default=None, alias="callbackUrl")


class BatchSubmitResponse(BaseModel):
    """202 Accepted body for POST /assess/batch."""

    model_config = ConfigDict(populate_by_name=True)

    submission_id: str = Field(..., alias="submissionId")
    status: BatchStatus = BatchStatus.QUEUED
    poll_url: str = Field(..., alias="pollUrl")
    estimated_completion_seconds: int | None = Field(default=None, alias="estimatedCompletionSeconds")


# ── Status response (GET /assess/batch/{id}/status) ──────────────────────────
class BatchProgress(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    cvs_completed: int = Field(..., alias="cvsCompleted", ge=0)
    cvs_total: int = Field(..., alias="cvsTotal", ge=0)
    runs_completed: int | None = Field(default=None, alias="runsCompleted", ge=0)
    runs_total: int | None = Field(default=None, alias="runsTotal", ge=0)
    runs_dispatched: int | None = Field(default=None, alias="runsDispatched", ge=0)
    last_updated_at: str | None = Field(default=None, alias="lastUpdatedAt")
    applications: list[dict[str, Any]] | None = None


class RunEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    run_id: str = Field(..., alias="runId")
    run_index: int = Field(..., alias="runIndex", ge=0)
    status: str
    document_id: str | None = Field(default=None, alias="documentId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    traceparent: str | None = None
    artifacts: list[dict[str, Any]] | None = None


class AggregatedOutcome(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    final_score: float | None = Field(default=None, alias="finalScore")
    final_decision: str | None = Field(default=None, alias="finalDecision")
    must_have_result: bool | None = Field(default=None, alias="mustHaveResult")


class CvResult(BaseModel):
    """Per-CV result block returned when batch completes."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    application_id: str = Field(..., alias="applicationId")
    runs: list[RunEvidence]
    aggregated: AggregatedOutcome | None = None
    error: dict[str, Any] | None = None


class BatchResult(BaseModel):
    cvs: list[CvResult]


class BatchError(BaseModel):
    code: str
    message: str


class BatchStatusResponse(BaseModel):
    """200 OK body for GET /assess/batch/{id}/status."""

    model_config = ConfigDict(populate_by_name=True)

    submission_id: str = Field(..., alias="submissionId")
    status: BatchStatus
    progress: BatchProgress | None = None
    estimated_completion_seconds: int | None = Field(default=None, alias="estimatedCompletionSeconds")
    retry_after_seconds: int | None = Field(default=None, alias="retryAfterSeconds")
    result: BatchResult | None = None
    error: BatchError | None = None


# ── Cancel response (POST /assess/batch/{id}/cancel) ─────────────────────────
class CancelResponse(BaseModel):
    status: BatchStatus
