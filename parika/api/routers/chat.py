"""
PARIKA API - Chat Router (REST, non-streaming)

Streaming chat lives at `WS /api/v1/ws/chat/{session_id}`
(`parika/api/ws/chat.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_core_execution_owner
from ..handlers.chat import handle_chat
from ..requests import ChatRequest as InternalChatRequest
from ..schemas.chat import ChatRequestBody, ChatResponseBody

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponseBody)
async def chat(
    body: ChatRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ChatResponseBody:
    """
    Submit one non-streaming chat turn.

    Every external client (Desktop, Web, Android, iOS, Voice, a future
    CLI client) sends this exact request body and receives this exact
    response body -- there is no client-specific request shape. The
    native PARIKA Console (`parika/console/`) is not a client of this
    endpoint, or of any endpoint in this API: it calls `Brain.handle()`
    directly, in-process, exactly as it always has -- see
    `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
    ("PARIKA Console" section).
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalChatRequest(text=body.text, session_id=body.session_id)
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return ChatResponseBody.model_validate(result)
