"""Routes for artifact registration: POST /runs/{runId}/artifacts."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, status

from api.auth import require_auth
from api.models import ArtifactResponse, BatchRegisterArtifactsRequest
from db.repository import RunRepository
from runtime.errors import ProblemDetail

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_repo() -> RunRepository:
    return RunRepository()


@router.post(
    "/runs/{run_id}/artifacts",
    response_model=list[ArtifactResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Batch-register artifacts for a run",
    tags=["artifacts"],
)
async def register_artifacts(
    body: BatchRegisterArtifactsRequest,
    run_id: uuid.UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_auth),
    repo: RunRepository = Depends(_get_repo),
) -> list[ArtifactResponse]:
    run = repo.get_run(run_id)
    if run is None:
        raise ProblemDetail(status=404, title="Not Found", detail=f"Run {run_id} does not exist.")

    artifacts = repo.insert_artifacts(run_id=run_id, items=body.artifacts)
    return artifacts
