"""
PARIKA Media Tool - Events

Immutable EventBus payloads published around Media command dispatch
and state synchronization, following the same
`@dataclass(frozen=True, slots=True, kw_only=True)` convention as
every other Core/Tool event (e.g. `parika/core/tool_manager/events.py`).

Channel names (all dotted, lowercase, matching the rest of the
codebase's `Channel Catalog` -
`docs/architecture/Core_Component_Responsibilities.md`):

- `media.command.dispatched` - a `media.*` command was enqueued to at
  least one connected Web Client.
- `media.command.unavailable` - a `media.*` command could not be
  dispatched because no Web Client is currently connected.
- `media.state.changed` - PARIKA's held `MediaState` changed, either
  because a command was dispatched (locally-known state only, e.g.
  `LOADING`) or because a Web Client reported its own state.
- `media.client.connected` / `media.client.disconnected` - a Web
  Client connected/disconnected over
  `WS /api/v1/ws/media/{client_id}`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import MediaState

MEDIA_COMMAND_DISPATCHED_EVENT = "media.command.dispatched"
MEDIA_COMMAND_UNAVAILABLE_EVENT = "media.command.unavailable"
MEDIA_STATE_CHANGED_EVENT = "media.state.changed"
MEDIA_CLIENT_CONNECTED_EVENT = "media.client.connected"
MEDIA_CLIENT_DISCONNECTED_EVENT = "media.client.disconnected"


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaCommandDispatchedEvent:
    """Published after a `media.*` command was enqueued to a Web Client."""

    command_type: str
    client_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaCommandUnavailableEvent:
    """
    Published when a `media.*` command could not be dispatched because
    no Web Client is connected.
    """

    command_type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaStateChangedEvent:
    """Published whenever PARIKA's held `MediaState` changes."""

    state: MediaState


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaClientConnectedEvent:
    """Published when a Web Client connects over the Media WebSocket."""

    client_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaClientDisconnectedEvent:
    """Published when a Web Client disconnects from the Media WebSocket."""

    client_id: str
