"""
PARIKA API - Chat Schemas

Wire-format request/response for `POST /api/v1/chat` and the WebSocket
message shapes for `WS /api/v1/ws/chat/{session_id}` (see
`docs/guides/Running.md` section 12).

These are the edge translation types every client uses: every
client sends this exact `ChatRequestBody`; Brain never sees it --
`parika/api/handlers/chat.py` translates it into a call against the
existing `InterfaceSession.submit_text()`, which itself builds the
Core-native `Goal`/`BrainRequest`.
"""

from __future__ import annotations

from .common import ApiModel


class ChatRequestBody(ApiModel):
    text: str
    session_id: str | None = None


class ChatResponseBody(ApiModel):
    session_id: str
    succeeded: bool
    message: str | None = None
    error_message: str | None = None


class ChatWsIncoming(ApiModel):
    """
    Message a client sends over `WS /api/v1/ws/chat/{session_id}`.
    """

    type: str = "message"
    text: str


class ChatWsToken(ApiModel):
    """Streamed content fragment, mirroring Ollama's own streaming shape."""

    type: str = "token"
    content: str


class ChatWsDone(ApiModel):
    """Terminal message for one chat turn, mirroring Ollama's `done: true`."""

    type: str = "done"
    done: bool = True
    response: ChatResponseBody


class ChatWsError(ApiModel):
    type: str = "error"
    message: str
