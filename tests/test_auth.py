from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt

from api.auth import _decode_jwt
from runtime.config import Settings


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _rsa_material(kid: str) -> tuple[bytes, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }
    return private_pem, jwk


def _settings() -> Settings:
    return Settings(
        auth_required=True,
        aad_issuer="https://login.example.com/tenant/v2.0",
        aad_audience="api://awr-platform",
    )


def _token(private_pem: bytes, *, issuer: str, audience: str, kid: str) -> str:
    return jwt.encode(
        {
            "sub": "user-1",
            "iss": issuer,
            "aud": audience,
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_decode_jwt_fetches_metadata_and_verifies_signature() -> None:
    settings = _settings()
    private_pem, jwk = _rsa_material("kid-1")
    token = _token(
        private_pem,
        issuer=settings.aad_issuer,
        audience=settings.aad_audience,
        kid="kid-1",
    )

    calls: list[str] = []

    def fake_get(url: str, timeout: float = 5.0):
        calls.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"jwks_uri": f"{settings.aad_issuer}/discovery/v2.0/keys"},
            )
        if url.endswith("/discovery/v2.0/keys"):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"keys": [jwk]},
            )
        raise AssertionError(f"unexpected url {url}")

    with patch("api.auth.httpx.get", side_effect=fake_get, create=True):
        claims = _decode_jwt(token, settings)

    assert claims["sub"] == "user-1"
    assert calls == [
        f"{settings.aad_issuer}/.well-known/openid-configuration",
        f"{settings.aad_issuer}/discovery/v2.0/keys",
    ]


def test_decode_jwt_rejects_signature_mismatch() -> None:
    settings = _settings()
    signing_key, _ = _rsa_material("kid-1")
    _, wrong_jwk = _rsa_material("kid-1")
    token = _token(
        signing_key,
        issuer=settings.aad_issuer,
        audience=settings.aad_audience,
        kid="kid-1",
    )

    def fake_get(url: str, timeout: float = 5.0):
        if url.endswith("/.well-known/openid-configuration"):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"jwks_uri": f"{settings.aad_issuer}/discovery/v2.0/keys"},
            )
        if url.endswith("/discovery/v2.0/keys"):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"keys": [wrong_jwk]},
            )
        raise AssertionError(f"unexpected url {url}")

    with patch("api.auth.httpx.get", side_effect=fake_get, create=True):
        with pytest.raises(HTTPException) as exc:
            _decode_jwt(token, settings)

    assert exc.value.status_code == 401