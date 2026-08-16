"""
PARIKA API - Authentication FastAPI Dependency

The single `require_auth` dependency every protected router uses.
`/api/v1/health`, `/api/v1/live`, and `/api/v1/ready` never depend on
this (see `docs/guides/Running.md` section 12.4) so they remain
answerable even without a configured backend.

This module is the transport-local dependency-injection seam:
FastAPI's `Depends()` is used here, and only here, for
authentication -- never inside Core.
"""

from __future__ import annotations

from fastapi import Depends, Request

from .backend import AuthContext


def _extract_credential(request: Request) -> str | None:
    """
    Extract a bearer-style credential from either the standard
    `Authorization: Bearer <token>` header or an `X-API-Key` header
    (the latter mirroring OpenHands Agent Server's
    `X-Session-API-Key` convention).
    """

    authorization = request.headers.get("Authorization")

    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip()

    api_key_header = request.headers.get("X-API-Key")

    if api_key_header:
        return api_key_header.strip()

    return None


def get_auth_context(request: Request) -> AuthContext:
    """
    Resolve the `AuthContext` for the current request using whichever
    `AuthenticationBackend` `parika/server/app.py` attached to
    `app.state.auth_backend` at startup (per `[api.auth].mode`).

    Raises whatever `parika.api.auth.exceptions` exception the
    configured backend raises for missing/invalid credentials; the
    centralized error handler (`parika/api/errors.py`) maps it to
    HTTP 401.
    """

    backend = request.app.state.auth_backend
    credential = _extract_credential(request)

    return backend.authenticate(credential)


RequireAuth = Depends(get_auth_context)
