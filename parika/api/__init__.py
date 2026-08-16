"""
PARIKA API Layer

The transport-facing REST/WebSocket surface described in
`docs/guides/Running.md` section 12. This package contains
no business logic: it translates HTTP/WebSocket requests into calls
against the existing `Router` Core component
(`parika/api/router_bindings.py`), and translates results back into
JSON. Every decision remains owned by an existing Core component; see
`parika/api/handlers/__init__.py` for the explicit rule governing
`parika/api/handlers/`.

This package is never imported by `parika/core/`, `parika/modules/`,
`parika/tools/`, or `parika/providers/`.
"""

from __future__ import annotations
