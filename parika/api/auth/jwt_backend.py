"""
PARIKA API - JWT Authentication Backend

Owns JWT issuance and verification end to end, entirely within the
API layer: JWT is an API concern, never a `parika/core/security/`
primitive (that package holds only transport-agnostic hashing
primitives -- see `docs/guides/Running.md` section 12.5).

Recommended for the Internet deployment profile.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt

from .backend import AuthContext
from .exceptions import ExpiredTokenError, InvalidCredentialsError, MissingCredentialsError

_ALGORITHM = "HS256"


class JwtBackend:
    """
    Issues and verifies HS256 JWTs signed with `[api.auth].jwt_secret`.
    """

    def __init__(self, secret: str, *, expiry_seconds: int = 3600) -> None:
        if not secret:
            raise ValueError(
                "JwtBackend requires a non-empty signing secret "
                "([api.auth].jwt_secret)."
            )

        self._secret = secret
        self._expiry_seconds = expiry_seconds

    def issue_token(self, subject: str, *, extra_claims: dict[str, Any] | None = None) -> str:
        """
        Issue a new signed JWT for `subject`.
        """

        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(seconds=self._expiry_seconds),
        }
        claims.update(extra_claims or {})

        return pyjwt.encode(claims, self._secret, algorithm=_ALGORITHM)

    def authenticate(self, credential: str | None) -> AuthContext:
        if not credential:
            raise MissingCredentialsError("No JWT was supplied.")

        try:
            claims = pyjwt.decode(credential, self._secret, algorithms=[_ALGORITHM])

        except pyjwt.ExpiredSignatureError as ex:
            raise ExpiredTokenError("The supplied JWT has expired.") from ex

        except pyjwt.InvalidTokenError as ex:
            raise InvalidCredentialsError("The supplied JWT is not valid.") from ex

        subject = claims.get("sub")

        if not subject:
            raise InvalidCredentialsError("The supplied JWT has no subject claim.")

        return AuthContext(subject=str(subject), mode="jwt")
