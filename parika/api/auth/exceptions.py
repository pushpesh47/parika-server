"""
PARIKA API - Authentication Exceptions

These are API-layer exceptions (never Core exceptions) describing
transport-facing authentication failures: a missing/invalid API key,
an invalid/expired JWT, or an unknown session token. `parika/api/errors.py`
maps every one of these to HTTP 401 via its suffix-matching rule.
"""

from __future__ import annotations


class AuthenticationError(Exception):
    """Base exception for every API-layer authentication failure."""


class MissingCredentialsError(AuthenticationError):
    """Raised when a protected endpoint receives no credentials at all."""


class InvalidCredentialsError(AuthenticationError):
    """Raised when supplied credentials do not verify."""


class ExpiredTokenError(AuthenticationError):
    """Raised when a JWT or session token has expired."""
