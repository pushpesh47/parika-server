"""
PARIKA API - "none" Authentication Backend

Used for the Local Development deployment profile (see
`docs/guides/Running.md` section 12.5): every request is treated as
already authenticated. This is the
default so that `python -m parika.server` has zero friction during
local development, matching today's `[api]` defaults exactly.
"""

from __future__ import annotations

from .backend import AuthContext


class NoAuthBackend:
    """Accepts every request unconditionally."""

    def authenticate(self, credential: str | None) -> AuthContext:
        return AuthContext(subject="anonymous", mode="none")
