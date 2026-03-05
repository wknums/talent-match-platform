"""Optional AAD / Microsoft Entra JWT validation for admin endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from runtime.config import Settings, get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def _get_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    if credentials is None:
        return None
    return credentials.credentials


def _decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Validate and decode a Microsoft Entra JWT.

    Uses python-jose with the issuer and audience from settings.
    In production you should fetch the JWKS from the OpenID configuration endpoint
    and cache the keys.
    """
    try:
        from jose import jwt as jose_jwt  # type: ignore[import-untyped]

        # TODO: fetch JWKS from {issuer}/.well-known/openid-configuration and cache
        # For scaffold purposes we validate structure only; replace with real JWKS fetch.
        payload: dict[str, Any] = jose_jwt.decode(
            token,
            key="",  # placeholder – replace with JWKS
            algorithms=["RS256"],
            audience=settings.aad_audience,
            issuer=settings.aad_issuer,
            options={"verify_signature": False},  # TODO: enable signature verification
        )
        return payload
    except Exception as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def require_auth(
    token: str | None = Depends(_get_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Dependency that enforces authentication when AUTH_REQUIRED=true.

    Returns the decoded JWT claims dict, or an empty dict when auth is disabled.
    """
    if not settings.auth_required:
        return {}

    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    return _decode_jwt(token, settings)
