"""
PARIKA Core - Security

Shared namespace for low-level, transport-agnostic security modules
used across the PARIKA Core (see
`docs/architecture/Core_Component_Responsibilities.md` section 6).

This namespace provides reusable cryptographic *mechanism* only
(hashing, constant-time comparison). It never performs authentication
or authorization *decisions*, never depends on HTTP/JWT/any wire
format, and is never a service or a "Security class" -- exactly like
`Utilities`, it is populated only with focused, stateless helper
modules once they are genuinely required.

JWT, API-key policy, and session tokens are transport/API-layer
concerns and live in `parika/api/auth/`, not here.
"""

from __future__ import annotations

from .exceptions import InvalidCredentialsError, SecurityError
from .hashing import constant_time_equals, hash_secret, verify_secret

__all__ = [
    "InvalidCredentialsError",
    "SecurityError",
    "constant_time_equals",
    "hash_secret",
    "verify_secret",
]
