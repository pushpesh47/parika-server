"""
PARIKA API - UI Context WebSocket

WS /api/v1/ws/ui -- bidirectional transport for real-time semantic UI context updates.
Follows the same auth/accept mechanics as ws/chat.py and ws/media.py.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from parika.core.ui_context.state import (
    UIContextState,
    RequestStatus,
    DomainInfo,
    SynthesisInfo,
    DependencyInfo,
)
from parika.interfaces.runtime import ParikaRuntime

from ..auth.exceptions import AuthenticationError

router = APIRouter()

# Event types for WebSocket protocol
UI_CONTEXT_SNAPSHOT = "ui.context.snapshot"
UI_CONTEXT_CHANGED = "ui.context.changed"


def _extract_ws_credential(websocket: WebSocket) -> str | None:
    """Extract authentication credential from WebSocket request."""
    authorization = websocket.headers.get("authorization")

    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip()

    api_key_header = websocket.headers.get("x-api-key")

    if api_key_header:
        return api_key_header.strip()

    return websocket.query_params.get("token")


def _serialize_state(state: UIContextState) -> dict[str, Any]:
    """Serialize UIContextState to JSON-compatible dict."""
    return {
        "version": state.version,
        "context": state.context,
        "confidence": state.confidence,
        "source": state.source.value,
        "attention": state.attention.value,
        "urgency": state.urgency.value,
        "focus": state.focus.value,
        "surfaces": [
            {
                "capability_id": surface.capability_id,
                "label": surface.label,
                "tier": surface.tier.value,
                "metadata": dict(surface.metadata),
            }
            for surface in state.surfaces
        ],
        "timestamp": state.timestamp.isoformat(),
        "metadata": dict(state.metadata),
        "request_status": state.request_status.value,
        "domains": [
            {
                "name": domain.name,
                "focus": domain.focus.value,
                "importance": domain.importance,
                "status": domain.status,
                "capability_ids": list(domain.capability_ids),
            }
            for domain in state.domains
        ],
        "synthesis": (
            {
                "goal_id": state.synthesis.goal_id,
                "capability_id": state.synthesis.capability_id,
                "status": state.synthesis.status,
                "depends_on": list(state.synthesis.depends_on),
                "completed_dependencies": list(state.synthesis.completed_dependencies),
                "failed_dependencies": list(state.synthesis.failed_dependencies),
            }
            if state.synthesis else None
        ),
        "dependencies": [
            {
                "goal_id": dep.goal_id,
                "capability_id": dep.capability_id,
                "depends_on": list(dep.depends_on),
                "status": dep.status,
                "is_synthesis": dep.is_synthesis,
            }
            for dep in state.dependencies
        ],
    }


async def _send_loop(
    websocket: WebSocket,
    outbound: "asyncio.Queue[dict[str, Any]]",
) -> None:
    """
    Independently deliver every message enqueued for this connection.
    
    Decoupled from receive loop so updates can be pushed at any time.
    Runs until cancelled by the route handler on disconnect.
    """
    try:
        while True:
            message = await outbound.get()
            await websocket.send_json(message)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Connection likely closed, exit gracefully
        pass


@router.websocket("/ws/ui")
async def websocket_ui(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time semantic UI context updates.
    
    Protocol:
    
    Server -> Client (initial snapshot on connect):
        {
            "type": "ui.context.snapshot",
            "payload": { ... UIContextState ... }
        }
    
    Server -> Client (semantic change notifications):
        {
            "type": "ui.context.changed",
            "payload": {
                "version": 1,
                "previous_version": 0,
                "changed_fields": ["context", "focus"],
                "source_event": "task.started",
                "timestamp": "...",
                "state": { ... full UIContextState ... }
            }
        }
    
    Authentication:
        Same as other WebSocket endpoints - Bearer token, X-API-Key, or query param token.
    """
    auth_backend = websocket.app.state.auth_backend

    try:
        auth_backend.authenticate(_extract_ws_credential(websocket))

    except AuthenticationError:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    runtime = websocket.app.state.runtime
    projector = runtime.ui_context_projector

    if not projector.is_ready():
        await websocket.close(code=1011, reason="UI Context Projector not ready")
        return

    # Create outbound queue for this connection
    outbound: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()

    # Send initial snapshot
    current_state = projector.get_current_state()
    await websocket.send_json({
        "type": UI_CONTEXT_SNAPSHOT,
        "payload": _serialize_state(current_state),
    })

    # Track last seen version to avoid sending duplicates
    last_version = current_state.version

    # Subscribe to UI context changes
    def on_context_changed(event: Any) -> None:
        nonlocal last_version
        if event.version > last_version:
            last_version = event.version
            # Get full state and send
            try:
                state = projector.get_current_state()
                outbound.put_nowait({
                    "type": UI_CONTEXT_CHANGED,
                    "payload": {
                        "version": event.version,
                        "previous_version": event.previous_version,
                        "changed_fields": list(event.changed_fields),
                        "source_event": event.source_event,
                        "timestamp": event.timestamp.isoformat(),
                        "state": _serialize_state(state),
                    },
                })
            except Exception:
                # Projector might not be ready
                pass

    runtime.event_bus.subscribe("ui.context.changed", on_context_changed)

    # Start send loop
    send_task = asyncio.create_task(_send_loop(websocket, outbound))

    try:
        # Keep connection alive, handle incoming messages (if any)
        while True:
            incoming = await websocket.receive_text()
            # Currently no client-to-server messages defined for UI context
            # But we keep the receive loop to detect disconnect
            try:
                data = json.loads(incoming)
                # Echo unknown message types back as error (forward-compatible)
                if "type" in data:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type '{data['type']}' for UI context WebSocket.",
                    })
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON message.",
                })

    except WebSocketDisconnect:
        pass

    finally:
        send_task.cancel()
        runtime.event_bus.unsubscribe("ui.context.changed", on_context_changed)