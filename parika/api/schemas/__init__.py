"""
PARIKA API - Schemas

Pure Pydantic request/response models for the `/api/v1` HTTP and
WebSocket surface.

This package is the *only* place transport-facing DTOs are defined
(see `docs/guides/Running.md` section 12).
Nothing under `parika/core/`, `parika/modules/`, `parika/tools/`, or
`parika/providers/` ever imports from this package, and this package
never imports a concrete transport (HTTP/WebSocket) type from Core --
translation between the two happens in `parika/api/handlers/`.
"""

from __future__ import annotations
