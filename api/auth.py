"""Optional AAD / Microsoft Entra JWT validation for admin endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from runtime.config import Settings, get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_CACHE_TTL_S = 300.0
_JWKS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_OPENID_CONFIG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_T = TypeVar("_T")


async def _get_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    if credentials is None:
        return None
    return credentials.credentials


def _decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Validate and decode a Microsoft Entra JWT.

    Uses python-jose with the issuer and audience from settings.
    """
    try:
        from jose import jwt as jose_jwt  # type: ignore[import-untyped]

        signing_key = _get_signing_key(token, settings)
        payload: dict[str, Any] = jose_jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            audience=settings.aad_audience,
            issuer=settings.aad_issuer,
        )
        return payload
    except Exception as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def _get_signing_key(token: str, settings: Settings) -> dict[str, Any]:
    from jose import jwt as jose_jwt  # type: ignore[import-untyped]

    if not settings.aad_issuer or not settings.aad_audience:
        raise RuntimeError("AAD issuer and audience must be configured when auth is required")

    header = jose_jwt.get_unverified_header(token)
    kid = str(header.get("kid") or "")
    keys = _get_jwks(settings.aad_issuer)

    if kid:
        for key in keys:
            if str(key.get("kid") or "") == kid:
                return key

    if len(keys) == 1:
        return keys[0]

    raise RuntimeError("Unable to resolve signing key for JWT")


def _get_jwks(issuer: str) -> list[dict[str, Any]]:
    jwks_uri = str(_get_openid_configuration(issuer).get("jwks_uri") or "")
    if not jwks_uri:
        raise RuntimeError("OpenID configuration did not include jwks_uri")

    cached = _cache_get(_JWKS_CACHE, jwks_uri)
    if cached is not None:
        return cached

    payload = _fetch_json(jwks_uri)
    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise RuntimeError("JWKS payload did not include any signing keys")

    normalized = [key for key in keys if isinstance(key, dict)]
    if not normalized:
        raise RuntimeError("JWKS payload did not include valid signing keys")

    _cache_put(_JWKS_CACHE, jwks_uri, normalized)
    return normalized


def _get_openid_configuration(issuer: str) -> dict[str, Any]:
    normalized_issuer = issuer.rstrip("/")
    cached = _cache_get(_OPENID_CONFIG_CACHE, normalized_issuer)
    if cached is not None:
        return cached

    payload = _fetch_json(f"{normalized_issuer}/.well-known/openid-configuration")
    _cache_put(_OPENID_CONFIG_CACHE, normalized_issuer, payload)
    return payload


def _fetch_json(url: str) -> dict[str, Any]:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return payload


def _cache_get(cache: dict[str, tuple[float, _T]], key: str) -> _T | None:
    entry = cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at <= time.time():
        cache.pop(key, None)
        return None
    return value


def _cache_put(cache: dict[str, tuple[float, _T]], key: str, value: _T) -> None:
    cache[key] = (time.time() + _CACHE_TTL_S, value)


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
