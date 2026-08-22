"""
PARIKA API - Chat Handler

Translates a `ChatRequest` into a call against the already-existing
`InterfaceSession.submit_text()` (which itself builds the Core-native
`Goal`/`BrainRequest` via `chat_capability.build_chat_goal()` and
submits it to `Brain.handle()`), and translates the resulting
`ChatTurnResult` back into a plain, JSON-serializable value.

This handler never constructs a `Goal`/`BrainRequest` itself and never
calls `Brain`/`Planner` directly -- see `parika/api/handlers/__init__.py`
for the full orchestration/translation-only rule every handler in this
package follows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.session import InterfaceSession
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore, SessionNotFoundError

from ..requests import ChatRequest
from parika.core.brain.brain_response import RequestStatus


def _load_or_create_session(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    session_id: str | None,
) -> InterfaceSession:
    if session_id:
        try:
            return InterfaceSession.load(session_id, runtime, session_store)

        except SessionNotFoundError:
            return InterfaceSession(runtime, session_id=session_id, session_store=session_store)

    return InterfaceSession(runtime, session_store=session_store)


def handle_chat(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: ChatRequest,
    *,
    on_token: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Submit one chat turn and return a plain-value summary of the
    result.

    Args:
        on_token:
            Optional streaming-fragment callback, forwarded unchanged
            to `InterfaceSession.submit_text()`. Supplied only by the
            WebSocket handler (`parika/api/ws/chat.py`); the REST
            handler never passes one.
    """

    session = _load_or_create_session(runtime, session_store, request.session_id)

    result = session.submit_text(request.text, on_token=on_token)

    message: str | None = None

    if result.succeeded and result.chat_response is not None:
        message = result.chat_response.message.content

    return {
        "session_id": session.id,
        "succeeded": result.succeeded,
        "status": result.status.value,
        "message": message,
        "error_message": None if result.succeeded else (result.error_message or "The request failed."),
    }
