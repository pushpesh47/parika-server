"""
PARIKA API - API Key Authentication Backend

Verifies a bearer-style API key against a configured list of hashed
keys, using only the transport-agnostic hashing primitives from
`parika/core/security/` (never storing or comparing plaintext keys).

Recommended for the LAN deployment profile -- see
`docs/guides/Running.md` section 12.5.
"""

from __future__ import annotations

from collections.abc import Sequence

from parika.core.security import hash_secret, verify_secret
from parika.core.security.exceptions import InvalidCredentialsError as _HashVerificationError

from .backend import AuthContext
from .exceptions import InvalidCredentialsError, MissingCredentialsError


class ApiKeyBackend:
    """
    Verifies a presented API key against `[api.auth].api_keys`
    (already-hashed values -- see `configure_hashed_api_keys()` and
    `docs/guides/Running.md` section 12.5).
    """

    def __init__(self, hashed_keys: Sequence[str]) -> None:
        self._hashed_keys = tuple(hashed_keys)

    def authenticate(self, credential: str | None) -> AuthContext:
        if not credential:
            raise MissingCredentialsError("No API key was supplied.")

        for hashed_key in self._hashed_keys:
            try:
                if verify_secret(credential, hashed_key):
                    return AuthContext(subject=f"api_key:{hashed_key[:16]}", mode="api_key")

            except _HashVerificationError:
                # A malformed configured hash is a configuration error,
                # not a reason to accept an otherwise-unverifiable key;
                # continue checking the remaining configured keys.
                continue

        raise InvalidCredentialsError("The supplied API key is not recognized.")


def configure_hashed_api_keys(plaintext_keys: Sequence[str]) -> tuple[str, ...]:
    """
    Convenience helper for operators/tests: hash a list of plaintext
    API keys the same way `[api.auth].api_keys` expects them to be
    stored, using the shared Core hashing primitive.
    """

    return tuple(hash_secret(key) for key in plaintext_keys)
