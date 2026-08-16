"""
PARIKA API - Chat WebSocket

`WS /api/v1/ws/chat/{session_id}` -- see
`docs/guides/Running.md` (Server Platform, section 12). Streams each
token fragment as it arrives from
`InterfaceSession.submit_text(text, on_token=...)`, exactly as
`CliApplication._handle_streamed_chat()` already does for the CLI,
then sends one terminal `{"type": "done", ...}` message mirroring
Ollama's own `"done": true` streaming convention.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth.exceptions import AuthenticationError
from ..handlers.chat import handle_chat
from ..requests import ChatRequest
from ..dependencies import get_core_execution_owner

router = APIRouter()


def _extract_ws_credential(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization")

    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip()

    api_key_header = websocket.headers.get("x-api-key")

    if api_key_header:
        return api_key_header.strip()

    return websocket.query_params.get("token")


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    core_execution_owner = websocket.app.state.core_execution_owner
    
    # Check if CoreExecutionOwner is available (not None and initialized)
    if core_execution_owner is None:
        await websocket.close(code=1008)
        return

    auth_backend = websocket.app.state.auth_backend

    try:
        auth_backend.authenticate(_extract_ws_credential(websocket))
    except AuthenticationError:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:
        while True:
            incoming: dict[str, Any] = await websocket.receive_json()
            text = str(incoming.get("text", "")).strip()

            if not text:
                continue

            buffered_tokens: list[str] = []

            # Submit the Core work to be executed on the Core worker thread
            # We wrap the handle_chat call in a lambda to capture the current values
            future = core_execution_owner.submit(
                lambda: handle_chat(
                    core_execution_owner.runtime,
                    core_execution_owner.session_store,
                    ChatRequest(text=text, session_id=session_id),
                    on_token=buffered_tokens.append,
                )
            )
            
            # Await the result without blocking the ASGI event loop
            result = await future

            for token in buffered_tokens:
                await websocket.send_json({"type": "token", "content": token})

            await websocket.send_json({"type": "done", "done": True, "response": result})

    except WebSocketDisconnect:
        return