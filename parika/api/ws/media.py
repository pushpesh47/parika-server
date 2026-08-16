"""
PARIKA API - Media WebSocket

`WS /api/v1/ws/media/{client_id}` -- the minimal new bidirectional
transport the Media Capability requires. See
`parika/tools/media/connection_registry.py`'s own docstring for why a
new route was introduced rather than extending `ws/chat.py`: the Chat
WebSocket is hardwired to chat's own inbound/outbound shapes, buffers
every outgoing message inside its own single receive loop, and keeps
no registry of open connections at all, so nothing outside that one
receive loop can push a message to it. This route follows the exact
same auth/accept mechanics as `ws/chat.py`, plus a second, independent
send loop so a command can be pushed at any time, not only in
response to an inbound message.

Full protocol (see `docs/guides/Running.md`'s Media API section for
the authoritative contract with examples):

Server -> Web Client (commands, enqueued by `parika/tools/media
/driver.py` through `MediaConnectionRegistry.dispatch()`):
    `{"type": "media.play", "payload": {"source": {...}}}`
    `{"type": "media.pause"}` / `"media.resume"` / `"media.stop"` /
    `"media.skip"` / `"media.previous"` / `"media.mute"` /
    `"media.unmute"` / `"media.show"` / `"media.hide"`
    `{"type": "media.seek", "payload": {"position_seconds": ...}}`
    `{"type": "media.set_volume", "payload": {"volume_percent": ...}}`

Web Client -> Server (events, applied to `MediaStateStore`):
    `{"type": "media.ready"}` -- handshake; marks this connection as
    media-ready (see `MediaConnectionRegistry.mark_ready()`), the
    precondition `dispatch()` now requires before a command is
    delivered to it. Does not itself change `MediaStateStore`'s held
    state - readiness is a connection-registry concept, not a
    `MediaState` field (see `docs/guides/Running.md`'s Media API
    section, "Web Client readiness and connecting").
    `{"type": "media.state_changed", "payload": {"state": {...}}}`
    `{"type": "media.position_changed", "payload": {"position": ...}}`
    `{"type": "media.play_started" | "media.play_paused" |
      "media.play_stopped" | "media.play_ended" | "media.buffering"}`
    `{"type": "media.error", "payload": {"message": "..."}}`
    `{"type": "media.source_changed", "payload": {"source": {...}}}`

An unrecognized inbound `type` is reported back as
`{"type": "error", "message": "..."}` over the same socket and
otherwise ignored, rather than closing the connection - a forward-
compatible Web Client sending a newer event type PARIKA does not yet
know about must not be disconnected for it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from parika.tools.media.connection_registry import MediaConnectionRegistry
from parika.tools.media.state_store import MediaStateStore

from ..auth.exceptions import AuthenticationError

router = APIRouter()

_CLIENT_EVENT_TYPES = frozenset({
    "media.ready",
    "media.state_changed",
    "media.position_changed",
    "media.play_started",
    "media.play_paused",
    "media.play_stopped",
    "media.play_ended",
    "media.buffering",
    "media.error",
    "media.source_changed",
})


def _extract_ws_credential(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization")

    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip()

    api_key_header = websocket.headers.get("x-api-key")

    if api_key_header:
        return api_key_header.strip()

    return websocket.query_params.get("token")


async def _send_loop(
    websocket: WebSocket, outbound: "asyncio.Queue[dict[str, Any]]"
) -> None:
    """
    Independently deliver every command enqueued for this connection -
    decoupled from `_receive_loop` below so a command dispatched at
    any time (not only in response to an inbound message) is still
    delivered promptly. Runs until cancelled by the route handler on
    disconnect.
    """

    while True:
        message = await outbound.get()
        await websocket.send_json(message)


@router.websocket("/ws/media/{client_id}")
async def websocket_media(websocket: WebSocket, client_id: str) -> None:
    auth_backend = websocket.app.state.auth_backend

    try:
        auth_backend.authenticate(_extract_ws_credential(websocket))

    except AuthenticationError:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    runtime = websocket.app.state.runtime
    connection_registry = runtime.service_container.get(MediaConnectionRegistry)
    state_store = runtime.service_container.get(MediaStateStore)

    loop = asyncio.get_running_loop()
    outbound: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()

    connection_registry.register(client_id, loop=loop, outbound=outbound)
    state_store.set_client_connected(True)

    send_task = asyncio.create_task(_send_loop(websocket, outbound))

    try:
        while True:
            incoming: dict[str, Any] = await websocket.receive_json()
            event_type = str(incoming.get("type", "")).strip()

            if event_type not in _CLIENT_EVENT_TYPES:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown media event type '{event_type}'."}
                )
                continue

            if event_type == "media.ready":
                connection_registry.mark_ready(client_id)
                continue

            payload = incoming.get("payload", {})

            if not isinstance(payload, dict):
                payload = {}

            state_store.apply_client_event(event_type, payload)

    except WebSocketDisconnect:
        pass

    finally:
        send_task.cancel()
        connection_registry.unregister(client_id)
        state_store.set_client_connected(connection_registry.is_connected())
