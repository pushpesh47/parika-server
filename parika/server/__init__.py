"""
PARIKA Server Runtime

The long-running Server Runtime process described in
`docs/guides/Running.md` (Server Platform, section 12). Wraps the
existing, unmodified `build_default_runtime()`/`shutdown_runtime()`
(`parika/interfaces/runtime.py`) and mounts the `parika/api/` REST/
WebSocket surface. Contains no business logic of its own.
"""

from __future__ import annotations
