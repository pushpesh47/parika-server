"""
PARIKA Core - Security: Hashing Primitives

Provides generic, transport-agnostic, low-level hashing and
constant-time comparison helpers usable by any present or future
component that needs to store or verify a secret (an API key, a
password, or any other credential-shaped value) without ever storing
it in plaintext.

This module knows nothing about HTTP, JWT, API keys specifically,
sessions, or any other wire format -- it hashes and verifies opaque
strings. Every format- or transport-specific decision (what a
credential looks like, how long a token lives, how it is transmitted)
belongs in the API layer (`parika/api/auth/`), never here.

This is the first module to populate the `Security` Core component,
following the exact same precedent already established by
`parika/core/utilities/progress.py` populating the previously empty
`Utilities` component: a small, stateless, reusable helper with no
lifecycle, no registry, and no "Security class" (see
`docs/architecture/Core_Component_Responsibilities.md` section 6,
"Does NOT ... Act as a service ... Contain a Security class").

Uses only the standard library (`hashlib`, `hmac`, `secrets`) -- no
new third-party dependency is introduced by this module.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .exceptions import InvalidCredentialsError

_DEFAULT_ITERATIONS = 200_000
_ALGORITHM = "sha256"
_SALT_BYTES = 16


def hash_secret(secret: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """
    Hash an opaque secret string for durable storage.

    Uses PBKDF2-HMAC-SHA256 (stdlib `hashlib.pbkdf2_hmac`) with a
    freshly generated random salt. The returned string encodes the
    algorithm, iteration count, salt, and derived key together (each
    hex-encoded, separated by `$`), so `verify_secret()` never needs a
    second, separately stored parameter to check a hash later.

    Args:
        secret:
            The plaintext secret to hash. Never logged, never returned
            unmodified by this function.

        iterations:
            PBKDF2 iteration count. Higher is slower but more
            resistant to brute-force attacks. Defaults to a value
            reasonable for a local-first, single-operator deployment;
            callers may increase it for higher-security deployments.

    Returns:
        An opaque, storage-safe string of the form
        `"<algorithm>$<iterations>$<salt-hex>$<derived-key-hex>"`.
    """

    salt = secrets.token_bytes(_SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        _ALGORITHM,
        secret.encode("utf-8"),
        salt,
        iterations,
    )

    return "$".join(
        (
            _ALGORITHM,
            str(iterations),
            salt.hex(),
            derived_key.hex(),
        )
    )


def verify_secret(secret: str, stored_hash: str) -> bool:
    """
    Verify a plaintext secret against a hash produced by
    `hash_secret()`.

    Args:
        secret:
            Plaintext secret supplied by the caller (e.g. an API key
            presented on an incoming request).

        stored_hash:
            The previously stored hash string, as produced by
            `hash_secret()`.

    Returns:
        `True` if `secret` matches `stored_hash`; `False` otherwise.
        Never raises for a merely-wrong secret -- only for a
        structurally malformed `stored_hash` (see
        `InvalidCredentialsError`), since a malformed stored hash
        indicates a configuration/storage error, not a failed
        verification attempt.

    Raises:
        InvalidCredentialsError:
            If `stored_hash` is not in the format produced by
            `hash_secret()`.
    """

    try:
        algorithm, iterations_text, salt_hex, expected_hex = stored_hash.split("$")
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(expected_hex)

    except (ValueError, AttributeError) as ex:
        raise InvalidCredentialsError(
            "Stored hash is not in the expected format."
        ) from ex

    if algorithm != _ALGORITHM:
        raise InvalidCredentialsError(
            f"Unsupported hash algorithm '{algorithm}'."
        )

    candidate_key = hashlib.pbkdf2_hmac(
        algorithm,
        secret.encode("utf-8"),
        salt,
        iterations,
    )

    return hmac.compare_digest(candidate_key, expected_key)


def constant_time_equals(left: str, right: str) -> bool:
    """
    Compare two opaque strings (e.g. two raw API key values) in
    constant time, avoiding a timing side channel.

    Generic enough to compare any two credential-shaped strings;
    carries no HTTP/JWT/API-key-specific knowledge.
    """

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
