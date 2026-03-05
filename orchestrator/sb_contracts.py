"""Service Bus message contracts used by the orchestrator and engine workers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunMessage(BaseModel):
    """Message placed on Service Bus for an engine worker to process."""

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: uuid.UUID
    engine: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    enqueued_at: datetime = Field(default_factory=datetime.utcnow)


class RunResultMessage(BaseModel):
    """Result reported back by an engine worker (via Service Bus or callback)."""

    run_id: uuid.UUID
    status: str
    duration_ms: int | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    error_message: str | None = None
    correlation_id: str = ""
