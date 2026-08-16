"""
PARIKA Media Tool - Driver

Implements the `ToolDriver` contract for all thirteen `media.*`
Capabilities.

A single `MediaToolDriver` instance is bound to exactly one
`MediaOperation` at construction time (see `manifest.py`'s module
docstring, mirroring the Expense Tool's own convention exactly).
`MediaModuleDriver` constructs thirteen instances - one per
Capability - all sharing the same `MediaStateStore`,
`MediaCommandDispatcher`, and `MediaResolver`.

**This driver never claims playback succeeded.** Every command
handler either reports `"status": "dispatched"` (the command was
handed to a connected Web Client - not proof it took effect) or
`"status": "unavailable"` (no Web Client is connected at all). Actual
playback confirmation only ever arrives later, as an inbound
`media.state_changed`/`media.play_started`/... event applied by
`MediaStateStore.apply_client_event()` - see
`docs/architecture/adr/0004-media-capability.md`.

Dispatch never blocks on delivery or confirmation (see
`connection_registry.py`'s own docstring for why) - every handler
below returns as soon as the command has been enqueued (or found
undeliverable), regardless of whether/when the Web Client actually
acts on it.
"""

from __future__ import annotations

from typing import Any, Mapping

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .connection_registry import MediaCommandDispatcher
from .exceptions import (
    MediaSourceNotFoundError,
    MediaUnsupportedSourceError,
    MediaValidationError,
)
from .manifest import MediaOperation
from .model import MediaSource
from .resolution import MediaResolver
from .state_store import MediaStateStore


class MediaToolDriver:
    """
    ToolDriver implementing one Media Tool Capability.
    """

    def __init__(
        self,
        operation: MediaOperation,
        *,
        state_store: MediaStateStore,
        dispatcher: MediaCommandDispatcher,
        resolver: MediaResolver,
    ) -> None:
        self._operation = operation
        self._state_store = state_store
        self._dispatcher = dispatcher
        self._resolver = resolver

    def execute(self, request: ToolRequest) -> ToolResponse:
        handler = _HANDLERS[self._operation]
        return handler(self, request.arguments)


def _dispatch_command(
    driver: MediaToolDriver,
    command_type: str,
    *,
    payload: Mapping[str, Any] | None = None,
    source: MediaSource | None = None,
) -> ToolResponse:
    """
    Enqueue one command to the Web Client (see
    `MediaCommandDispatcher.dispatch()`) and record the local, non-
    authoritative state effect - shared tail end of every command
    handler below.
    """

    message: dict[str, Any] = {"type": command_type}

    if payload is not None:
        message["payload"] = dict(payload)

    dispatched = driver._dispatcher.dispatch(message)

    if not dispatched:
        return ToolResponse(
            result={
                "status": "unavailable",
                "message": (
                    "No compatible Web Client is currently connected; "
                    f"'{command_type}' was not sent."
                ),
            }
        )

    driver._state_store.record_command_dispatched(command_type, source=source)

    result: dict[str, Any] = {"status": "dispatched", "command": command_type}

    if source is not None:
        result["source"] = source.to_dict()

    return ToolResponse(result=result)


def _handle_play(driver: MediaToolDriver, arguments: Mapping[str, Any]) -> ToolResponse:
    query = arguments.get("query")

    if not isinstance(query, str) or not query.strip():
        raise MediaValidationError("request.arguments['query'] must be a non-empty string.")

    raw_title = arguments.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None

    try:
        source = driver._resolver.resolve(query, title=title)

    except MediaSourceNotFoundError as ex:
        return ToolResponse(result={"status": "not_found", "message": str(ex)})

    except MediaUnsupportedSourceError as ex:
        return ToolResponse(result={"status": "unsupported", "message": str(ex)})

    return _dispatch_command(
        driver, "media.play", payload={"source": source.to_dict()}, source=source
    )


def _handle_seek(driver: MediaToolDriver, arguments: Mapping[str, Any]) -> ToolResponse:
    raw_position = arguments.get("position_seconds")

    try:
        position = float(raw_position)  # type: ignore[arg-type]

    except (TypeError, ValueError):
        return ToolResponse(
            result={"status": "invalid", "message": "position_seconds must be a number."}
        )

    if position < 0:
        return ToolResponse(
            result={"status": "invalid", "message": "position_seconds must not be negative."}
        )

    return _dispatch_command(
        driver, "media.seek", payload={"position_seconds": position}
    )


def _handle_set_volume(
    driver: MediaToolDriver, arguments: Mapping[str, Any]
) -> ToolResponse:
    raw_volume = arguments.get("volume_percent")

    try:
        volume = float(raw_volume)  # type: ignore[arg-type]

    except (TypeError, ValueError):
        return ToolResponse(
            result={"status": "invalid", "message": "volume_percent must be a number."}
        )

    if not 0.0 <= volume <= 100.0:
        return ToolResponse(
            result={
                "status": "invalid",
                "message": "volume_percent must be between 0 and 100.",
            }
        )

    return _dispatch_command(
        driver, "media.set_volume", payload={"volume_percent": volume}
    )


def _handle_get_state(
    driver: MediaToolDriver, arguments: Mapping[str, Any]
) -> ToolResponse:
    state = driver._state_store.get()
    return ToolResponse(result={"status": "success", "state": state.to_dict()})


def _make_simple_command_handler(command_type: str):
    """
    Build a handler for a `media.*` operation that takes no arguments
    and carries no payload - pause/resume/stop/skip/previous/mute/
    unmute/show/hide.
    """

    def _handler(driver: MediaToolDriver, arguments: Mapping[str, Any]) -> ToolResponse:
        return _dispatch_command(driver, command_type)

    return _handler


_HANDLERS = {
    MediaOperation.PLAY: _handle_play,
    MediaOperation.PAUSE: _make_simple_command_handler("media.pause"),
    MediaOperation.RESUME: _make_simple_command_handler("media.resume"),
    MediaOperation.STOP: _make_simple_command_handler("media.stop"),
    MediaOperation.SKIP: _make_simple_command_handler("media.skip"),
    MediaOperation.PREVIOUS: _make_simple_command_handler("media.previous"),
    MediaOperation.SEEK: _handle_seek,
    MediaOperation.SET_VOLUME: _handle_set_volume,
    MediaOperation.MUTE: _make_simple_command_handler("media.mute"),
    MediaOperation.UNMUTE: _make_simple_command_handler("media.unmute"),
    MediaOperation.SHOW: _make_simple_command_handler("media.show"),
    MediaOperation.HIDE: _make_simple_command_handler("media.hide"),
    MediaOperation.GET_STATE: _handle_get_state,
}
