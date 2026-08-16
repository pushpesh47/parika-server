"""
PARIKA Media Tool - State Store

`MediaStateStore` holds PARIKA's single, shared, last-known
`MediaState` - the same shared-single-instance-via-`ServiceContainer`
pattern `parika.modules.voice.operation_registry.TtsOperationRegistry`
already establishes (see that module's own docstring): constructed
once at the composition root (`parika/interfaces/runtime.py`) and
injected into both `MediaToolDriver` (the natural-language/Planner
path) and the Media API/WebSocket layer (the Web Client's direct
path), so both read and write the exact same instance - one shared
state, never two.

PARIKA is never the authority on *actual* playback: this store only
ever holds what a Web Client most recently reported, or what PARIKA
itself locally knows immediately after dispatching a command (e.g.
`LOADING` right after a `media.play` command is enqueued - never
`PLAYING`, since that would claim a browser-side fact PARIKA cannot
yet know). See `docs/architecture/adr/0004-media-capability.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Any, Mapping

from parika.core.event_bus.event_bus import EventBus

from .events import MEDIA_STATE_CHANGED_EVENT, MediaStateChangedEvent
from .model import MediaSource, MediaSourceType, MediaState, PlaybackStatus

_CLIENT_STATUS_BY_EVENT_TYPE: Mapping[str, PlaybackStatus] = {
    "media.play_started": PlaybackStatus.PLAYING,
    "media.play_paused": PlaybackStatus.PAUSED,
    "media.play_stopped": PlaybackStatus.STOPPED,
    "media.play_ended": PlaybackStatus.ENDED,
    "media.buffering": PlaybackStatus.BUFFERING,
    "media.error": PlaybackStatus.ERROR,
}
"""
Web-Client-to-server event types that map directly onto one
`PlaybackStatus` - see `docs/guides/Running.md`'s Media API section,
"Web Client -> Server events".
"""


def _source_from_payload(payload: object) -> MediaSource | None:
    if not isinstance(payload, Mapping):
        return None

    raw_type = payload.get("type")

    try:
        source_type = MediaSourceType(str(raw_type))
    except ValueError:
        return None

    try:
        return MediaSource(
            source_type=source_type,
            url=payload.get("url"),
            path=payload.get("path"),
            media_id=payload.get("media_id"),
            title=payload.get("title"),
            artist=payload.get("artist"),
            album=payload.get("album"),
            duration=payload.get("duration"),
            mime_type=payload.get("mime_type"),
        )
    except ValueError:
        return None


class MediaStateStore:
    """
    Thread-safe holder of PARIKA's single, shared `MediaState`.
    """

    def __init__(self, *, event_bus: EventBus | None = None) -> None:
        self._lock = RLock()
        self._state = MediaState.initial()
        self._event_bus = event_bus

    def get(self) -> MediaState:
        """Return the current `MediaState` snapshot."""

        with self._lock:
            return self._state

    def set_client_connected(self, connected: bool) -> MediaState:
        """
        Record whether a Web Client is currently connected, without
        otherwise changing the held state. Called by
        `MediaConnectionRegistry` on connect/disconnect - see
        `connection_registry.py`.
        """

        with self._lock:
            from dataclasses import replace

            self._state = replace(
                self._state,
                client_connected=connected,
                updated_at=datetime.now(UTC),
            )
            new_state = self._state

        self._publish_changed(new_state)
        return new_state

    def record_command_dispatched(
        self, command_type: str, *, source: MediaSource | None
    ) -> MediaState:
        """
        Record the *local* effect of successfully dispatching a
        command to a connected Web Client - never a claim of actual
        playback. Only `media.play` moves status to `LOADING`; every
        other command leaves `status` untouched, since PARIKA does
        not yet know whether e.g. a `media.pause` command actually
        paused anything until the Web Client reports back.
        """

        from dataclasses import replace

        with self._lock:
            if command_type == "media.play" and source is not None:
                self._state = replace(
                    self._state,
                    status=PlaybackStatus.LOADING,
                    source=source,
                    position=0.0,
                    error_message=None,
                    updated_at=datetime.now(UTC),
                )

            new_state = self._state

        self._publish_changed(new_state)
        return new_state

    def apply_client_event(
        self, event_type: str, payload: Mapping[str, Any]
    ) -> MediaState:
        """
        Apply one inbound Web-Client-to-server event to the held
        state. See `docs/guides/Running.md`'s Media API section for
        the full event catalog.

        Unrecognized event types are accepted as a no-op state read
        (the caller/router already validated `event_type` against
        the known set before calling this) - this method itself never
        raises for the state-update step, matching Section 25 of the
        Media task's failure-semantics requirement that Web-Client-
        reported state is applied best-effort.
        """

        from dataclasses import replace

        with self._lock:
            current = self._state
            changes: dict[str, Any] = {"updated_at": datetime.now(UTC)}

            if event_type == "media.state_changed":
                state_payload = payload.get("state", payload)

                if isinstance(state_payload, Mapping):
                    if "status" in state_payload:
                        try:
                            changes["status"] = PlaybackStatus(
                                str(state_payload["status"])
                            )
                        except ValueError:
                            pass

                    for field_name in (
                        "position", "volume", "muted", "playback_rate", "visible",
                    ):
                        if field_name in state_payload:
                            changes[field_name] = state_payload[field_name]

                    if "source" in state_payload:
                        changes["source"] = _source_from_payload(
                            state_payload["source"]
                        )

                    if "error_message" in state_payload:
                        changes["error_message"] = state_payload["error_message"]

            elif event_type == "media.position_changed":
                if "position" in payload:
                    changes["position"] = payload["position"]

            elif event_type == "media.source_changed":
                source = _source_from_payload(payload.get("source"))
                if source is not None:
                    changes["source"] = source

            elif event_type == "media.error":
                changes["status"] = PlaybackStatus.ERROR
                changes["error_message"] = payload.get("message")

            elif event_type in _CLIENT_STATUS_BY_EVENT_TYPE:
                changes["status"] = _CLIENT_STATUS_BY_EVENT_TYPE[event_type]

                if changes["status"] is not PlaybackStatus.ERROR:
                    changes["error_message"] = None

            self._state = replace(current, **changes)
            new_state = self._state

        self._publish_changed(new_state)
        return new_state

    def _publish_changed(self, state: MediaState) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(
                MEDIA_STATE_CHANGED_EVENT, MediaStateChangedEvent(state=state)
            )
