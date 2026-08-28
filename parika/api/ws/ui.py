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
    RequestLifecycle,
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
                "contextual_role": surface.contextual_role.value,
                "relevance": surface.relevance,
                "metadata": dict(surface.metadata),
                "domain": surface.domain,
                "semantic_type": surface.semantic_type,
                "capability_category": surface.capability_category,
                "capability_tags": list(surface.capability_tags),
                "freshness": (
                    {
                        "domain": surface.freshness.domain,
                        "last_updated": surface.freshness.last_updated.isoformat() if surface.freshness.last_updated else None,
                        "status": surface.freshness.status,
                        "max_age_seconds": surface.freshness.max_age_seconds,
                    }
                    if surface.freshness else None
                ),
            }
            for surface in state.surfaces
        ],
        "timestamp": state.timestamp.isoformat(),
        "metadata": dict(state.metadata),
        "request_status": state.request_status.value,
        "lifecycle": state.lifecycle.value,
        "domains": [
            {
                "name": domain.name,
                "focus": domain.focus.value,
                "importance": domain.importance,
                "status": domain.status,
                "capability_ids": list(domain.capability_ids),
                "contextual_role": domain.contextual_role.value,
                "relevance": domain.relevance,
                "entities": [
                    {
                        "name": e.name,
                        "entity_type": e.entity_type.value,
                        "domain": e.domain,
                        "confidence": e.confidence,
                        "metadata": dict(e.metadata),
                    }
                    for e in domain.entities
                ],
                "topics": [
                    {
                        "name": t.name,
                        "domain": t.domain,
                        "relevance": t.relevance,
                        "source": t.source,
                    }
                    for t in domain.topics
                ],
                "freshness": (
                    {
                        "domain": domain.freshness.domain,
                        "last_updated": domain.freshness.last_updated.isoformat() if domain.freshness.last_updated else None,
                        "status": domain.freshness.status,
                        "max_age_seconds": domain.freshness.max_age_seconds,
                    }
                    if domain.freshness else None
                ),
                "domain_category": domain.domain_category,
                "primary_entities": list(domain.primary_entities),
                "primary_topics": list(domain.primary_topics),
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
                "contextual_role": state.synthesis.contextual_role.value,
                "domain": state.synthesis.domain,
                "semantic_type": state.synthesis.semantic_type,
                "dependency_domains": list(state.synthesis.dependency_domains),
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
                "contextual_role": dep.contextual_role.value,
                "domain": dep.domain,
                "semantic_type": dep.semantic_type,
                "capability_category": dep.capability_category,
                "capability_tags": list(dep.capability_tags),
                "dependency_domains": list(dep.dependency_domains),
            }
            for dep in state.dependencies
        ],
        # Phase 2 fields
        "user_intent": state.user_intent.value,
        "conversational_context": (
            {
                "current_domain": state.conversational_context.current_domain,
                "active_subject": state.conversational_context.active_subject,
                "ongoing_task": state.conversational_context.ongoing_task,
                "previous_domain": state.conversational_context.previous_domain,
                "turn_count": state.conversational_context.turn_count,
                "last_user_request": state.conversational_context.last_user_request,
                "contextual_transition": state.conversational_context.contextual_transition.value,
            }
            if state.conversational_context else None
        ),
        "semantic_relevance": [
            {
                "domain": rel.domain,
                "score": rel.score,
                "signals": list(rel.signals),
            }
            for rel in state.semantic_relevance
        ],
        "entities": [
            {
                "name": e.name,
                "entity_type": e.entity_type.value,
                "domain": e.domain,
                "confidence": e.confidence,
                "metadata": dict(e.metadata),
            }
            for e in state.entities
        ],
        "topics": [
            {
                "name": t.name,
                "domain": t.domain,
                "relevance": t.relevance,
                "source": t.source,
            }
            for t in state.topics
        ],
        "context_transition": state.context_transition.value,
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