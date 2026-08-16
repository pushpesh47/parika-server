"""
PARIKA API - Media Schemas

Wire-format response for `GET /api/v1/media/state` - a read-only
snapshot of PARIKA's last known media playback state (see
`parika.tools.media.model.MediaState`).

The bidirectional command/event contract itself
(`WS /api/v1/ws/media/{client_id}`) is documented in
`docs/guides/Running.md`'s Media API section rather than modeled as
FastAPI/Pydantic schemas, exactly like the existing Chat WebSocket
(`parika/api/schemas/chat.py`'s `ChatWs*` models cover only its own
minimal `type` discriminator shape) - FastAPI's generated OpenAPI
schema never includes WebSocket routes at all (see
`scripts/generate_api_docs.py`), so a fuller Pydantic model here would
not even appear in `docs/api/PARIKA_API_Reference.html`.
"""

from __future__ import annotations

from .common import ApiModel


class MediaSourceBody(ApiModel):
    type: str
    url: str | None = None
    path: str | None = None
    media_id: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    mime_type: str | None = None


class MediaStateResponseBody(ApiModel):
    """
    Mirrors `MediaState.to_dict()` exactly - the same shape returned
    by the `media.get_state` Capability and applied by
    `MediaStateStore.apply_client_event()`.
    """

    status: str
    source: MediaSourceBody | None = None
    position: float | None = None
    volume: float
    muted: bool
    playback_rate: float
    visible: bool
    client_connected: bool
    error_message: str | None = None
    updated_at: str
