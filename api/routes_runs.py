"""Routes for /runs endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, status

from api.auth import require_auth
from api.deps import PaginationParams
from api.models import (
    CreateRunRequest,
    FinishRunRequest,
    PaginatedRunsResponse,
    RunResponse,
    RunStatus,
)
from db.repository import RunRepository
from runtime.errors import ProblemDetail

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_repo() -> RunRepository:
    """Factory for the run repository (DI seam)."""
    return RunRepository()


# ── POST /runs (idempotent start) ────────────────────────────────────────────
@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new run (idempotent)",
)
async def create_run(
    body: CreateRunRequest,
    _claims: dict[str, Any] = Depends(require_auth),
    repo: RunRepository = Depends(_get_repo),
) -> RunResponse:
    existing = repo.get_by_idempotency_key(body.idempotency_key)
    if existing is not None:
        logger.info("Idempotent hit for key=%s", body.idempotency_key)
        return existing

    run = repo.insert_run_started(
        idempotency_key=body.idempotency_key,
        engine=body.engine,
        parameters=body.parameters,
    )
    return run


# ── PATCH /runs/{runId} (finish) ─────────────────────────────────────────────
@router.patch(
    "/{run_id}",
    response_model=RunResponse,
    summary="Finish a run with timings, tokens, and status",
)
async def finish_run(
    body: FinishRunRequest,
    run_id: uuid.UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_auth),
    repo: RunRepository = Depends(_get_repo),
) -> RunResponse:
    run = repo.get_run(run_id)
    if run is None:
        raise ProblemDetail(status=404, title="Not Found", detail=f"Run {run_id} does not exist.")

    updated = repo.update_run_finished(
        run_id=run_id,
        status=body.status,
        duration_ms=body.duration_ms,
        tokens_prompt=body.tokens_prompt,
        tokens_completion=body.tokens_completion,
        error_message=body.error_message,
    )
    return updated


# ── GET /runs ─────────────────────────────────────────────────────────────────
@router.get("", response_model=PaginatedRunsResponse, summary="List runs with filters + paging")
async def list_runs(
    paging: PaginationParams = Depends(),
    engine: str | None = Query(default=None),
    status_filter: RunStatus | None = Query(default=None, alias="status"),
    repo: RunRepository = Depends(_get_repo),
) -> PaginatedRunsResponse:
    items, total = repo.get_runs(
        offset=paging.offset,
        limit=paging.page_size,
        engine=engine,
        status=status_filter,
    )
    return PaginatedRunsResponse(items=items, total=total, page=paging.page, page_size=paging.page_size)


# ── GET /runs/{runId} ────────────────────────────────────────────────────────
@router.get("/{run_id}", response_model=RunResponse, summary="Get a single run")
async def get_run(
    run_id: uuid.UUID = Path(...),
    repo: RunRepository = Depends(_get_repo),
) -> RunResponse:
    run = repo.get_run(run_id)
    if run is None:
        raise ProblemDetail(status=404, title="Not Found", detail=f"Run {run_id} does not exist.")
    return run
