"""Service Bus wire contracts shared with the engine queue-worker.

These models mirror `contracts.models` in `auto-assessment-assist` exactly so
that `RunMessage.model_validate_json(body)` round-trips without transformation.

- ``RunMessage``       — Platform → Engine, queue: ``engine-runs``.
- ``RunResultMessage`` — Engine → Platform, queue: ``engine-results``
                          (when engine ``REPORT_MODE=servicebus``).
- ``FinishRunRequest`` — Engine → Platform, HTTP ``PATCH /runs/{runId}`` body
                          (when engine ``REPORT_MODE=http``).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Nested ───────────────────────────────────────────────────────────────────

class RunProfile(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")

    join_mode: Optional[str] = None
    json_template_blob_uri: Optional[str] = None


class OutputParams(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")

    results_container: Optional[str] = None
    results_prefix: Optional[str] = None


class AoaiParams(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")

    deployment: Optional[str] = None
    api_version: Optional[str] = None
    max_output_tokens: Optional[int] = None


class RunParameters(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")

    cv_blob_uris: List[str] = Field(default_factory=list)
    spec_blob_uri: Optional[str] = None
    prompt_blob_uri: Optional[str] = None
    run_profile: Optional[RunProfile] = None
    return_artifacts: Optional[bool] = True
    output: Optional[OutputParams] = None
    aoai: Optional[AoaiParams] = None


class ArtifactItem(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    blob_uri: str
    mime: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None


# ── 1) RunMessage — Platform → Engine (SB inbound to engine) ─────────────────

class RunMessage(BaseModel):
    """Per-run message published to the ``engine-runs`` Service Bus queue."""

    model_config = ConfigDict(strict=True, extra="forbid")

    message_id: str = Field(..., description="UUID – unique message identifier.")
    run_id: str = Field(..., description="UUID – platform-assigned run identifier.")
    engine: str = Field(..., description="Expected value: 'awreason'.")
    parameters: RunParameters = Field(default_factory=RunParameters)
    correlation_id: str = Field(..., description="UUID – end-to-end correlation.")
    enqueued_at: str = Field(..., description="RFC 3339 / ISO 8601 UTC timestamp.")


# ── 2) RunResultMessage — Engine → Platform (SB outbound from engine) ────────

class RunResultMessage(BaseModel):
    model_config = ConfigDict(strict=True)

    run_id: str
    status: str = Field(..., description="'Succeeded' | 'Failed' | 'Partial'.")
    duration_ms: int
    tokens_prompt: int
    tokens_completion: int
    error_message: Optional[str] = None
    correlation_id: str
    traceparent: Optional[str] = None
    artifacts: Optional[List[ArtifactItem]] = None


# ── 3) FinishRunRequest — Engine → Platform (HTTP PATCH body) ────────────────

class FinishRunRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    status: str
    duration_ms: int
    tokens_prompt: int
    tokens_completion: int
    error_message: Optional[str] = None
    correlation_id: Optional[str] = None
    traceparent: Optional[str] = None
    artifacts: Optional[List[ArtifactItem]] = None
