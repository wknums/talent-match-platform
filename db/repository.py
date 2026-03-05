"""Repository layer – engine-agnostic CRUD for RunRecord & Artifact.

All SQL is parameterised. Transient faults are handled by the ``with_retry``
decorator (see runtime.transient).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import pyodbc

from api.models import (
    ArtifactItem,
    ArtifactResponse,
    RunResponse,
    RunStatus,
)
from db.connection import get_connection
from runtime.transient import with_sql_retry

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunRepository:
    """Data-access object for engine.RunRecord, engine.Artifact, engine.Idempotency."""

    # ── Idempotency ───────────────────────────────────────────────────────────

    @with_sql_retry
    def get_by_idempotency_key(self, idempotency_key: str) -> RunResponse | None:
        """Return an existing run for the given idempotency key, or None."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM engine.RunRecord WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_run(row)
        finally:
            conn.close()

    # ── Insert ────────────────────────────────────────────────────────────────

    @with_sql_retry
    def insert_run_started(
        self,
        *,
        idempotency_key: str,
        engine: str,
        parameters: dict[str, Any],
    ) -> RunResponse:
        """Insert a new run in PENDING status."""
        run_id = uuid.uuid4()
        now = _utcnow()
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO engine.RunRecord
                    (id, idempotency_key, engine, status, parameters, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(run_id), idempotency_key, engine, RunStatus.PENDING.value, json.dumps(parameters), now),
            )
            conn.commit()
        finally:
            conn.close()

        return RunResponse(
            id=run_id,
            idempotency_key=idempotency_key,
            engine=engine,
            status=RunStatus.PENDING,
            parameters=parameters,
            created_at=now,
        )

    # ── Update ────────────────────────────────────────────────────────────────

    @with_sql_retry
    def update_run_finished(
        self,
        *,
        run_id: uuid.UUID,
        status: RunStatus,
        duration_ms: int | None = None,
        tokens_prompt: int | None = None,
        tokens_completion: int | None = None,
        error_message: str | None = None,
    ) -> RunResponse:
        """Mark a run as finished with timings and token usage."""
        now = _utcnow()
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE engine.RunRecord
                SET status = ?, duration_ms = ?, tokens_prompt = ?,
                    tokens_completion = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, duration_ms, tokens_prompt, tokens_completion, error_message, now, str(run_id)),
            )
            conn.commit()
            cursor.execute("SELECT * FROM engine.RunRecord WHERE id = ?", (str(run_id),))
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            raise ValueError(f"Run {run_id} not found after update")
        return self._row_to_run(row)

    # ── Artifacts ─────────────────────────────────────────────────────────────

    @with_sql_retry
    def insert_artifacts(self, *, run_id: uuid.UUID, items: list[ArtifactItem]) -> list[ArtifactResponse]:
        """Batch-insert artifacts for a run."""
        conn = get_connection()
        results: list[ArtifactResponse] = []
        now = _utcnow()
        try:
            cursor = conn.cursor()
            for item in items:
                artifact_id = uuid.uuid4()
                cursor.execute(
                    """
                    INSERT INTO engine.Artifact
                        (id, run_id, name, uri, content_type, size_bytes, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(artifact_id),
                        str(run_id),
                        item.name,
                        item.uri,
                        item.content_type,
                        item.size_bytes,
                        json.dumps(item.metadata),
                        now,
                    ),
                )
                results.append(
                    ArtifactResponse(
                        id=artifact_id,
                        run_id=run_id,
                        name=item.name,
                        uri=item.uri,
                        content_type=item.content_type,
                        size_bytes=item.size_bytes,
                        metadata=item.metadata,
                        created_at=now,
                    )
                )
            conn.commit()
        finally:
            conn.close()
        return results

    # ── Reads ─────────────────────────────────────────────────────────────────

    @with_sql_retry
    def get_run(self, run_id: uuid.UUID) -> RunResponse | None:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM engine.RunRecord WHERE id = ?", (str(run_id),))
            row = cursor.fetchone()
            return self._row_to_run(row) if row else None
        finally:
            conn.close()

    @with_sql_retry
    def get_runs(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        engine: str | None = None,
        status: RunStatus | None = None,
    ) -> tuple[list[RunResponse], int]:
        """Return paginated runs with optional filters."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            where_clauses: list[str] = []
            params: list[Any] = []

            if engine is not None:
                where_clauses.append("engine = ?")
                params.append(engine)
            if status is not None:
                where_clauses.append("status = ?")
                params.append(status.value)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Total count
            cursor.execute(f"SELECT COUNT(*) FROM engine.RunRecord{where_sql}", params)
            total: int = cursor.fetchone()[0]

            # Page
            cursor.execute(
                f"SELECT * FROM engine.RunRecord{where_sql} ORDER BY created_at DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                [*params, offset, limit],
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        return [self._row_to_run(r) for r in rows], total

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_run(row: Any) -> RunResponse:
        """Map a pyodbc Row to a RunResponse model.

        Column order must match the engine.RunRecord table:
            id, idempotency_key, engine, status, parameters,
            duration_ms, tokens_prompt, tokens_completion,
            error_message, created_at, updated_at
        """
        return RunResponse(
            id=uuid.UUID(row.id),
            idempotency_key=row.idempotency_key,
            engine=row.engine,
            status=RunStatus(row.status),
            parameters=json.loads(row.parameters) if isinstance(row.parameters, str) else row.parameters,
            duration_ms=row.duration_ms,
            tokens_prompt=row.tokens_prompt,
            tokens_completion=row.tokens_completion,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=getattr(row, "updated_at", None),
        )
