"""001 – initial schema: engine.RunRecord, engine.Artifact, engine.Idempotency.

Revision ID: 001_initial_schema
Revises: –
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'engine') EXEC('CREATE SCHEMA engine');")

    op.execute(
        """
        CREATE TABLE engine.RunRecord (
            id                  UNIQUEIDENTIFIER    NOT NULL PRIMARY KEY DEFAULT NEWID(),
            idempotency_key     NVARCHAR(128)       NOT NULL,
            engine              NVARCHAR(64)        NOT NULL,
            status              NVARCHAR(32)        NOT NULL DEFAULT 'pending',
            parameters          NVARCHAR(MAX)       NULL,        -- JSON
            duration_ms         INT                 NULL,
            tokens_prompt       INT                 NULL,
            tokens_completion   INT                 NULL,
            error_message       NVARCHAR(MAX)       NULL,
            created_at          DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME(),
            updated_at          DATETIME2           NULL
        );
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX UQ_RunRecord_IdempotencyKey
            ON engine.RunRecord (idempotency_key);
        """
    )

    op.execute(
        """
        CREATE TABLE engine.Artifact (
            id              UNIQUEIDENTIFIER    NOT NULL PRIMARY KEY DEFAULT NEWID(),
            run_id          UNIQUEIDENTIFIER    NOT NULL
                REFERENCES engine.RunRecord(id),
            name            NVARCHAR(256)       NOT NULL,
            uri             NVARCHAR(2048)      NOT NULL,
            content_type    NVARCHAR(128)       NOT NULL DEFAULT 'application/octet-stream',
            size_bytes      BIGINT              NULL,
            metadata        NVARCHAR(MAX)       NULL,        -- JSON
            created_at      DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IX_Artifact_RunId ON engine.Artifact (run_id);
        """
    )

    # Optional idempotency ledger (for auditing / TTL cleanup)
    op.execute(
        """
        CREATE TABLE engine.Idempotency (
            idempotency_key NVARCHAR(128)       NOT NULL PRIMARY KEY,
            run_id          UNIQUEIDENTIFIER    NOT NULL,
            created_at      DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS engine.Idempotency;")
    op.execute("DROP TABLE IF EXISTS engine.Artifact;")
    op.execute("DROP TABLE IF EXISTS engine.RunRecord;")
    op.execute("DROP SCHEMA IF EXISTS engine;")
