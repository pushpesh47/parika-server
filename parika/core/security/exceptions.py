"""
PARIKA Core - Security Exceptions

Defines the exception types raised by the low-level, transport-
agnostic security primitives in `parika/core/security/`.

These exceptions describe cryptographic-primitive-level failures only
(e.g. "the supplied secret does not match the stored hash"). They are
deliberately generic and carry no knowledge of HTTP, JWT, API keys, or
any other wire format -- callers in the API layer (`parika/api/auth/`)
catch these and translate them into transport-specific responses.
"""

from __future__ import annotations


class SecurityError(Exception):
    """
    Base exception for every error raised by `parika/core/security/`.
    """


class InvalidCredentialsError(SecurityError):
    """
    Raised when a supplied secret does not match its stored hash.

    Carries no information about *why* verification failed (wrong
    secret, malformed hash, ...) beyond this exception type, so
    callers can never accidentally leak a timing or error-message
    side channel about which part of a credential was wrong.
    """
