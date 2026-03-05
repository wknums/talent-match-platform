"""Pydantic v2 request/response models and RFC 7807 problem detail."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────
class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Requests ──────────────────────────────────────────────────────────────────
class CreateRunRequest(BaseModel):
    """Idempotent run start request."""

    idempotency_key: str = Field(..., min_length=1, max_length=128, description="Client-supplied idempotency key.")
    engine: str = Field(..., min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)


class FinishRunRequest(BaseModel):
    """Patch a run with final timings, token usage, and status."""

    status: RunStatus
    duration_ms: int | None = Field(default=None, ge=0)
    tokens_prompt: int | None = Field(default=None, ge=0)
    tokens_completion: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class ArtifactItem(BaseModel):
    """Single artifact within a batch-register call."""

    name: str = Field(..., min_length=1, max_length=256)
    uri: str = Field(..., min_length=1)
    content_type: str = Field(default="application/octet-stream")
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchRegisterArtifactsRequest(BaseModel):
    """Batch register artifacts for a run."""

    artifacts: list[ArtifactItem] = Field(..., min_length=1)


# ── Responses ─────────────────────────────────────────────────────────────────
class RunResponse(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    engine: str
    status: RunStatus
    parameters: dict[str, Any]
    duration_ms: int | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    name: str
    uri: str
    content_type: str
    size_bytes: int | None = None
    metadata: dict[str, Any]
    created_at: datetime


class PaginatedRunsResponse(BaseModel):
    items: list[RunResponse]
    total: int
    page: int
    page_size: int
