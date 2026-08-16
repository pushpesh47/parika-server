"""
PARIKA API - WebSocket Handlers

WebSocket handlers for streaming chat (see `docs/guides/Running.md`
section 12.3; shell output and coding/repository progress streaming
are not yet implemented -- see `parika/api/ws/chat.py` for the one
handler that exists today).

Every handler here bridges PARIKA's entirely synchronous Core
(`InterfaceSession.submit_text()`, `EventBus.publish()`) to Starlette's
async WebSocket primitives -- see `parika/api/ws/chat.py`'s own
docstring for the specific bridging approach used. No Core component
becomes `async`.
"""

from __future__ import annotations
