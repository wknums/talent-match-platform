"""RFC 7807 Problem Detail helpers."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class ProblemDetail(Exception):
    """Exception that renders as an RFC 7807 ``application/problem+json`` response."""

    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: str | None = None,
        type_uri: str = "about:blank",
        instance: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.type_uri = type_uri
        self.instance = instance
        self.extra = extra or {}
        super().__init__(detail or title)


def problem_response(exc: ProblemDetail) -> JSONResponse:
    """Create a ``JSONResponse`` from a :class:`ProblemDetail`."""
    body: dict[str, Any] = {
        "type": exc.type_uri,
        "title": exc.title,
        "status": exc.status,
    }
    if exc.detail:
        body["detail"] = exc.detail
    if exc.instance:
        body["instance"] = exc.instance
    body.update(exc.extra)
    return JSONResponse(status_code=exc.status, content=body, media_type="application/problem+json")
