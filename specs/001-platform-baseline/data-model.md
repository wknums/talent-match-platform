# Data Model: AWR Platform Baseline

**Date**: 2026-03-02  
**Schema**: `engine`

## Entity Relationship

```
┌──────────────────┐       ┌──────────────────┐
│   Idempotency    │       │    RunRecord      │
├──────────────────┤       ├──────────────────┤
│ idempotency_key  │──────▶│ id (PK)          │
│ run_id (FK)      │       │ status           │
│ created_at       │       │ created_at       │
└──────────────────┘       │ completed_at     │
                           │ duration_ms      │
                           │ tokens_used      │
                           │ error_detail     │
                           │ correlation_id   │
                           └───────┬──────────┘
                                   │ 1:N
                           ┌───────▼──────────┐
                           │    Artifact       │
                           ├──────────────────┤
                           │ id (PK)          │
                           │ run_id (FK)      │
                           │ artifact_type    │
                           │ blob_path        │
                           │ size_bytes       │
                           │ created_at       │
                           └──────────────────┘
```

## Tables

### engine.RunRecord

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UNIQUEIDENTIFIER | NO | `NEWID()` | Primary key |
| `idempotency_key` | NVARCHAR(256) | NO | — | Unique constraint for idempotent creation |
| `status` | NVARCHAR(32) | NO | `'started'` | Run status: `started`, `completed`, `failed`, `cancelled` |
| `created_at` | DATETIME2 | NO | `SYSUTCDATETIME()` | UTC timestamp of run creation |
| `completed_at` | DATETIME2 | YES | NULL | UTC timestamp of run completion |
| `duration_ms` | BIGINT | YES | NULL | Total execution duration in milliseconds |
| `tokens_used` | BIGINT | YES | NULL | Token count consumed by the engine |
| `error_detail` | NVARCHAR(MAX) | YES | NULL | Error message/stack if status is `failed` |
| `correlation_id` | NVARCHAR(128) | YES | NULL | Distributed tracing correlation ID |

**Indexes**:
- `PK_RunRecord` on `id`
- `UQ_RunRecord_IdempotencyKey` on `idempotency_key` (UNIQUE)
- `IX_RunRecord_Status_CreatedAt` on `(status, created_at DESC)` for filtered listing
- `IX_RunRecord_CreatedAt` on `created_at DESC` for pagination

### engine.Artifact

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UNIQUEIDENTIFIER | NO | `NEWID()` | Primary key |
| `run_id` | UNIQUEIDENTIFIER | NO | — | Foreign key to RunRecord |
| `artifact_type` | NVARCHAR(64) | NO | — | Type classifier (e.g., `report`, `log`, `model`) |
| `blob_path` | NVARCHAR(1024) | NO | — | Azure Blob Storage path |
| `size_bytes` | BIGINT | YES | NULL | File size in bytes |
| `created_at` | DATETIME2 | NO | `SYSUTCDATETIME()` | UTC timestamp |

**Indexes**:
- `PK_Artifact` on `id`
- `FK_Artifact_RunRecord` on `run_id` → `engine.RunRecord(id)`
- `IX_Artifact_RunId` on `run_id` for run-scoped lookups

### engine.Idempotency

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `idempotency_key` | NVARCHAR(256) | NO | — | Primary key — the client-provided key |
| `run_id` | UNIQUEIDENTIFIER | NO | — | Foreign key to RunRecord |
| `created_at` | DATETIME2 | NO | `SYSUTCDATETIME()` | UTC timestamp |

**Indexes**:
- `PK_Idempotency` on `idempotency_key`
- `FK_Idempotency_RunRecord` on `run_id` → `engine.RunRecord(id)`

## Notes

- All tables are in the `engine` schema to isolate platform data.
- `UNIQUEIDENTIFIER` is used for IDs to support distributed generation without coordination.
- `DATETIME2` is used everywhere (not `DATETIME`) for higher precision and range.
- The `Idempotency` table is optional — the unique constraint on `RunRecord.idempotency_key` provides the same guarantee, but the separate table allows for TTL-based cleanup of old keys without touching the main table.
