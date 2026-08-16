"""
PARIKA API - Authentication

Owns every authentication *policy* decision (API keys, JWT) entirely
within the API layer -- see `docs/guides/Running.md` section 12
(Server Platform). `parika/core/security/` supplies only the
underlying transport-agnostic cryptographic primitives these backends
use.

Supported modes today: `none` (Local Development), `api_key` (LAN),
`jwt` (Internet) -- see `build_auth_backend()` below and
`docs/guides/Running.md` section 12.5. A `SessionTokenBackend` (opaque,
process-local, short-lived tokens issued after a primary `api_key`/
`jwt` handshake, intended for WebSocket connections that should not
re-present a long-lived credential on every message) was drafted and
fully tested during Phase 3.5a but deliberately removed before Phase
3.5a's close: it had no issuance endpoint and no wiring into
`build_auth_backend()`'s mode selector, so it was unreachable
production code. Reintroduce it -- together with whatever endpoint
actually issues a token and the connection flow that consumes it --
when a concrete need for it exists, rather than carrying an unused
backend forward.
"""

from __future__ import annotations

from .api_key_backend import ApiKeyBackend, configure_hashed_api_keys
from .backend import AuthContext, AuthenticationBackend
from .exceptions import (
    AuthenticationError,
    ExpiredTokenError,
    InvalidCredentialsError,
    MissingCredentialsError,
)
from .jwt_backend import JwtBackend
from .none_backend import NoAuthBackend

__all__ = [
    "ApiKeyBackend",
    "AuthContext",
    "AuthenticationBackend",
    "AuthenticationError",
    "ExpiredTokenError",
    "InvalidCredentialsError",
    "JwtBackend",
    "MissingCredentialsError",
    "NoAuthBackend",
    "configure_hashed_api_keys",
]


def build_auth_backend(*, mode: str, config: dict) -> AuthenticationBackend:
    """
    Construct the configured `AuthenticationBackend` from
    `[api.auth]` settings (see `docs/guides/Running.md` section 12.5).

    Args:
        mode:
            One of `"none"` | `"api_key"` | `"jwt"`.

        config:
            The `[api.auth]` configuration mapping (already resolved
            through `Configuration`).
    """

    if mode == "none":
        return NoAuthBackend()

    if mode == "api_key":
        return ApiKeyBackend(hashed_keys=tuple(config.get("api_keys", ())))

    if mode == "jwt":
        secret = config.get("jwt_secret", "")
        expiry_seconds = int(config.get("jwt_expiry_seconds", 3600))
        return JwtBackend(secret=secret, expiry_seconds=expiry_seconds)

    raise ValueError(
        f"Unknown [api.auth].mode '{mode}'. Expected 'none', 'api_key', or 'jwt'."
    )
