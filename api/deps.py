"""Shared FastAPI dependencies: correlation-id, pagination, DI helpers."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Annotated

from fastapi import Query, Request

# ── Correlation ID ────────────────────────────────────────────────────────────
_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
_traceparent_var: ContextVar[str] = ContextVar("traceparent", default="")

CORRELATION_HEADER = "X-Correlation-Id"
TRACEPARENT_HEADER = "traceparent"


def ensure_correlation_id(request: Request) -> str:
    """Read or generate a correlation-id and store it in a ContextVar."""
    cid = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
    _correlation_id_var.set(cid)
    tp = request.headers.get(TRACEPARENT_HEADER) or ""
    _traceparent_var.set(tp)
    return cid


def get_correlation_id() -> str:
    """Return the current correlation-id (for log records, outgoing calls, etc.)."""
    return _correlation_id_var.get() or str(uuid.uuid4())


def get_traceparent() -> str:
    """Return the current W3C ``traceparent`` (empty if none was supplied)."""
    return _traceparent_var.get()


# ── Pagination ────────────────────────────────────────────────────────────────
class PaginationParams:
    """Query-parameter based pagination."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
