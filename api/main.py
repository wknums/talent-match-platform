"""FastAPI application entry-point.

Initialises middleware, OpenTelemetry, routes, and error handlers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routes_assess import router as assess_router
from runtime.config import get_settings
from runtime.errors import ProblemDetail, problem_response
from runtime.telemetry import setup_telemetry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan – startup / shutdown hooks."""
    settings = get_settings()
    setup_telemetry(service_name="awr-platform-api", otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    logger.info("awr-platform API starting", extra={"env": settings.model_dump(exclude={"aad_issuer", "aad_audience"})})
    yield
    logger.info("awr-platform API shutting down")


app = FastAPI(
    title="AWR Platform API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Correlation-ID middleware ──────────────────────────────────────────────────
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Propagate or generate a correlation-id on every request."""
    from api.deps import ensure_correlation_id

    correlation_id = ensure_correlation_id(request)
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    return response


# ── Global exception handler (RFC 7807) ───────────────────────────────────────
@app.exception_handler(ProblemDetail)
async def problem_detail_handler(_request: Request, exc: ProblemDetail) -> JSONResponse:
    return problem_response(exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"path": request.url.path})
    return problem_response(
        ProblemDetail(
            status=500,
            title="Internal Server Error",
            detail=str(exc) if get_settings().auth_required is False else "An unexpected error occurred.",
        )
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(assess_router)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
