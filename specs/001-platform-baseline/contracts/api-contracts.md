# API Contracts: AWR Platform Baseline

**Base URL**: `https://{apim-gateway}/api/v1`  
**Auth**: Optional AAD JWT Bearer token (when `AUTH_REQUIRED=true`)  
**Content-Type**: `application/json`  
**Error Format**: RFC 7807 `application/problem+json`

---

## Runs

### POST /runs — Create a Run (Idempotent)

**Request**:
```json
{
  "idempotency_key": "client-generated-uuid-or-string",
  "metadata": { }
}
```

**Headers**:
- `X-Correlation-Id` (optional): Client-provided correlation ID. Generated if absent.

**Response 201 Created** (new run):
```json
{
  "id": "a1b2c3d4-...",
  "idempotency_key": "client-generated-uuid-or-string",
  "status": "started",
  "created_at": "2026-03-02T10:30:00Z",
  "completed_at": null,
  "duration_ms": null,
  "tokens_used": null,
  "error_detail": null,
  "correlation_id": "req-abc-123"
}
```

**Response 200 OK** (duplicate idempotency key — returns existing):
Same schema as 201.

**Response 400 Bad Request**:
```json
{
  "type": "urn:awr:problem:validation-error",
  "title": "Validation Error",
  "status": 400,
  "detail": "idempotency_key is required",
  "instance": "req-abc-123"
}
```

---

### GET /runs — List Runs (with filters + pagination)

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | — | Filter by status: `started`, `completed`, `failed`, `cancelled` |
| `limit` | int | 50 | Page size (max 100) |
| `cursor` | string | — | Cursor token from previous response |

**Response 200 OK**:
```json
{
  "items": [
    {
      "id": "a1b2c3d4-...",
      "idempotency_key": "...",
      "status": "completed",
      "created_at": "2026-03-02T10:30:00Z",
      "completed_at": "2026-03-02T10:31:00Z",
      "duration_ms": 1200,
      "tokens_used": 500,
      "error_detail": null,
      "correlation_id": "req-abc-123"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0Ijo...",
  "total_count": null
}
```

---

### GET /runs/{runId} — Get Single Run

**Response 200 OK**:
```json
{
  "id": "a1b2c3d4-...",
  "idempotency_key": "...",
  "status": "completed",
  "created_at": "2026-03-02T10:30:00Z",
  "completed_at": "2026-03-02T10:31:00Z",
  "duration_ms": 1200,
  "tokens_used": 500,
  "error_detail": null,
  "correlation_id": "req-abc-123",
  "artifacts": [
    {
      "id": "e5f6g7h8-...",
      "artifact_type": "report",
      "blob_path": "runs/a1b2c3d4/output-report.pdf",
      "size_bytes": 204800,
      "created_at": "2026-03-02T10:31:05Z"
    }
  ]
}
```

**Response 404 Not Found**:
```json
{
  "type": "urn:awr:problem:run-not-found",
  "title": "Run Not Found",
  "status": 404,
  "detail": "No run with id 'a1b2c3d4-...' exists",
  "instance": "req-abc-123"
}
```

---

### PATCH /runs/{runId} — Complete a Run

**Request**:
```json
{
  "status": "completed",
  "duration_ms": 1200,
  "tokens_used": 500,
  "error_detail": null
}
```

**Response 200 OK**: Updated run record (same schema as GET).

**Response 404 Not Found**: Run does not exist.

**Response 409 Conflict**:
```json
{
  "type": "urn:awr:problem:run-already-completed",
  "title": "Conflict",
  "status": 409,
  "detail": "Run 'a1b2c3d4-...' is already in 'completed' status",
  "instance": "req-abc-123"
}
```

---

## Artifacts

### POST /runs/{runId}/artifacts — Batch Register Artifacts

**Request**:
```json
{
  "artifacts": [
    {
      "artifact_type": "report",
      "blob_path": "runs/a1b2c3d4/output-report.pdf",
      "size_bytes": 204800
    },
    {
      "artifact_type": "log",
      "blob_path": "runs/a1b2c3d4/engine.log",
      "size_bytes": 8192
    }
  ]
}
```

**Response 201 Created**:
```json
{
  "artifacts": [
    {
      "id": "e5f6g7h8-...",
      "run_id": "a1b2c3d4-...",
      "artifact_type": "report",
      "blob_path": "runs/a1b2c3d4/output-report.pdf",
      "size_bytes": 204800,
      "created_at": "2026-03-02T10:31:05Z"
    },
    {
      "id": "i9j0k1l2-...",
      "run_id": "a1b2c3d4-...",
      "artifact_type": "log",
      "blob_path": "runs/a1b2c3d4/engine.log",
      "size_bytes": 8192,
      "created_at": "2026-03-02T10:31:05Z"
    }
  ]
}
```

**Response 400 Bad Request**: Empty artifact list.

**Response 404 Not Found**: Run does not exist.

---

## Common Headers

| Header | Direction | Description |
|--------|-----------|-------------|
| `X-Correlation-Id` | Request/Response | Distributed trace correlation ID |
| `Authorization` | Request | `Bearer <AAD-JWT>` (when `AUTH_REQUIRED=true`) |
| `Content-Type` | Request/Response | `application/json` |

## Common Error Schema (RFC 7807)

```json
{
  "type": "urn:awr:problem:{error-type}",
  "title": "Human-readable summary",
  "status": 400,
  "detail": "Specific error explanation",
  "instance": "correlation-id-or-request-id"
}
```
