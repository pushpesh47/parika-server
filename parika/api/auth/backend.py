"""
PARIKA API - Authentication Backend Protocol

Defines the small `AuthenticationBackend` Protocol every auth mode
(`none`, `api_key`, `jwt`) implements identically, so that adding a
future mode (OAuth2, mTLS, ...) never requires an endpoint redesign
(see `docs/guides/Running.md` section 12.5).

This module -- and every module under `parika/api/auth/` -- is
API-layer code. It is never imported by `parika/core/`, and it is the
one place JWT/API-key *policy* lives in full. `parika/core/security/`
supplies only the underlying cryptographic primitives these backends
use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthContext:
    """
    Immutable identity established for one authenticated request or
    WebSocket connection.
    """

    subject: str
    """Opaque identifier of the authenticated caller (an API key's
    configured label or a JWT subject claim)."""

    mode: str
    """Which auth mode authenticated this request: "none" | "api_key" |
    "jwt"."""


class AuthenticationBackend(Protocol):
    """
    Structurally-typed authentication backend.

    Every backend receives the raw credential string extracted from
    the request (a bearer token, an API key header value, ...) by the
    FastAPI dependency in `dependency.py`, and either returns an
    `AuthContext` or raises one of `parika.api.auth.exceptions`'
    exceptions. A backend never reads the HTTP request itself -- that
    keeps every backend testable with a plain string in, `AuthContext`
    or exception out.
    """

    def authenticate(self, credential: str | None) -> AuthContext:
        ...
