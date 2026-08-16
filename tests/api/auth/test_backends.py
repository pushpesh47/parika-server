"""
Tests for `parika.api.auth` backends.
"""

from __future__ import annotations

import time

import pytest

from parika.api.auth import (
    ApiKeyBackend,
    ExpiredTokenError,
    InvalidCredentialsError,
    JwtBackend,
    MissingCredentialsError,
    NoAuthBackend,
    build_auth_backend,
    configure_hashed_api_keys,
)


def test_no_auth_backend_always_succeeds() -> None:
    backend = NoAuthBackend()
    context = backend.authenticate(None)

    assert context.mode == "none"


def test_api_key_backend_accepts_configured_key() -> None:
    hashed = configure_hashed_api_keys(["secret-key-1"])
    backend = ApiKeyBackend(hashed_keys=hashed)

    context = backend.authenticate("secret-key-1")

    assert context.mode == "api_key"


def test_api_key_backend_rejects_unknown_key() -> None:
    hashed = configure_hashed_api_keys(["secret-key-1"])
    backend = ApiKeyBackend(hashed_keys=hashed)

    with pytest.raises(InvalidCredentialsError):
        backend.authenticate("wrong-key")


def test_api_key_backend_rejects_missing_credential() -> None:
    backend = ApiKeyBackend(hashed_keys=())

    with pytest.raises(MissingCredentialsError):
        backend.authenticate(None)


def test_jwt_backend_round_trip() -> None:
    backend = JwtBackend(secret="test-secret", expiry_seconds=60)
    token = backend.issue_token("user-1")

    context = backend.authenticate(token)

    assert context.subject == "user-1"
    assert context.mode == "jwt"


def test_jwt_backend_rejects_expired_token() -> None:
    backend = JwtBackend(secret="test-secret", expiry_seconds=0)
    token = backend.issue_token("user-1")

    time.sleep(1.1)

    with pytest.raises(ExpiredTokenError):
        backend.authenticate(token)


def test_jwt_backend_rejects_wrong_secret() -> None:
    issuer = JwtBackend(secret="secret-a", expiry_seconds=60)
    verifier = JwtBackend(secret="secret-b", expiry_seconds=60)
    token = issuer.issue_token("user-1")

    with pytest.raises(InvalidCredentialsError):
        verifier.authenticate(token)


def test_build_auth_backend_none() -> None:
    backend = build_auth_backend(mode="none", config={})
    assert isinstance(backend, NoAuthBackend)


def test_build_auth_backend_api_key() -> None:
    backend = build_auth_backend(mode="api_key", config={"api_keys": []})
    assert isinstance(backend, ApiKeyBackend)


def test_build_auth_backend_jwt() -> None:
    backend = build_auth_backend(
        mode="jwt", config={"jwt_secret": "s", "jwt_expiry_seconds": 60}
    )
    assert isinstance(backend, JwtBackend)


def test_build_auth_backend_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        build_auth_backend(mode="oauth2", config={})
