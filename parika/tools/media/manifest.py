"""
PARIKA Media Tool - Manifest

Defines the thirteen `media.*` Capabilities and their Tool Affordance
Contracts, following the Expense Tool's "one Tool per Capability"
convention exactly (see `parika/tools/expense/manifest.py`'s own
module docstring for why: `ToolRequest` carries no capability
identifier, so a single multi-capability Tool could not tell which
operation a request targeted).

This module owns Tool creation; `ToolManager` only registers and
stores the `Tool` instances produced here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

MEDIA_TOOL_VERSION = "1.0.0"


class MediaOperation(StrEnum):
    """The thirteen Capabilities the Media Tool implements."""

    PLAY = "play"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    SKIP = "skip"
    PREVIOUS = "previous"
    SEEK = "seek"
    SET_VOLUME = "set_volume"
    MUTE = "mute"
    UNMUTE = "unmute"
    SHOW = "show"
    HIDE = "hide"
    GET_STATE = "get_state"


OPERATION_CAPABILITY_ID: Mapping[MediaOperation, str] = {
    operation: f"media.{operation.value}" for operation in MediaOperation
}

OPERATION_TOOL_ID: Mapping[MediaOperation, str] = {
    operation: f"tool.media_{operation.value}" for operation in MediaOperation
}

_TOOL_NAMES: Mapping[MediaOperation, str] = {
    MediaOperation.PLAY: "Media Play",
    MediaOperation.PAUSE: "Media Pause",
    MediaOperation.RESUME: "Media Resume",
    MediaOperation.STOP: "Media Stop",
    MediaOperation.SKIP: "Media Skip",
    MediaOperation.PREVIOUS: "Media Previous",
    MediaOperation.SEEK: "Media Seek",
    MediaOperation.SET_VOLUME: "Media Set Volume",
    MediaOperation.MUTE: "Media Mute",
    MediaOperation.UNMUTE: "Media Unmute",
    MediaOperation.SHOW: "Media Show",
    MediaOperation.HIDE: "Media Hide",
    MediaOperation.GET_STATE: "Media Get State",
}

_FAILURE_SEMANTICS_NO_CLIENT = (
    "If the result has \"status\": \"unavailable\", no compatible Web "
    "Client is currently connected - tell the user playback control "
    "is not currently available rather than claiming the action "
    "happened."
)

_RESULT_SEMANTICS_DISPATCH_ONLY = (
    "A \"status\": \"dispatched\" result means the command was sent to "
    "the Web Client, not that it has taken effect yet - the Web "
    "Client still has to actually load/pause/seek/etc. and report "
    "back. Do not tell the user something is now playing/paused/etc. "
    "as a certainty; say it was requested/sent."
)

MEDIA_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    "media.play": {
        "description": (
            "Resolve a song/video/local file/URL and send a play "
            "command to the connected Web Client."
        ),
        "purpose": (
            "Handles requests like 'play Imagine Dragons Believer', "
            "'play this YouTube video', 'play any south indian "
            "movies from youtube', or 'play the song in "
            "/home/user/Music/test.mp3'. PARIKA never plays audio/"
            "video itself - actual playback happens in the separate "
            "Web Client."
        ),
        "use_when": (
            "the user wants to start playing a specific song, video, "
            "local file, or URL, or describes what kind of media "
            "they want played."
        ),
        "avoid_when": (
            "the user wants to resume already-loaded media (use "
            "resume) or is only asking about the currently playing "
            "media's state (use get_state)."
        ),
        "requires": (
            "a query describing what to play: a plain-text search "
            "(song/artist/movie description), a local filesystem "
            "path, a YouTube URL, or a direct media file URL."
        ),
        "result_semantics": (
            "Returns the resolved source (type, title, and "
            "identifying URL/path) and whether the command was "
            "dispatched. " + _RESULT_SEMANTICS_DISPATCH_ONLY
        ),
        "failure_semantics": (
            "If the result has \"status\": \"not_found\", nothing "
            "matching could be resolved - say so and ask for more "
            "detail. If \"status\": \"unsupported\", the URL is a "
            "webpage, not a playable media file/YouTube link. "
            + _FAILURE_SEMANTICS_NO_CLIENT
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to play: a search phrase, a local file "
                        "path, a YouTube URL, or a direct media URL."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Optional display title override.",
                },
            },
            "required": ["query"],
        },
    },
    "media.pause": {
        "description": "Pause the currently loaded media in the Web Client.",
        "purpose": "Handles 'pause', 'pause the music/video'.",
        "use_when": "media is currently playing and the user wants it paused.",
        "avoid_when": "nothing is currently playing.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.resume": {
        "description": "Resume already-loaded, paused media in the Web Client.",
        "purpose": "Handles 'resume', 'unpause', 'continue playing'.",
        "use_when": "media is currently paused and the user wants it resumed.",
        "avoid_when": "no media has been loaded yet - use play instead.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.stop": {
        "description": "Stop playback entirely in the Web Client.",
        "purpose": "Handles 'stop playing', 'stop the music/video'.",
        "use_when": "the user wants playback stopped entirely, not just paused.",
        "avoid_when": "the user only wants to pause (use pause) - stopping "
        "typically clears the loaded source, pausing does not.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.skip": {
        "description": "Skip to the next item in the Web Client's queue.",
        "purpose": "Handles 'skip', 'next', 'play the next one'.",
        "use_when": "the user wants to move forward to the next queued item.",
        "avoid_when": "there is nothing to skip to.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.previous": {
        "description": "Go back to the previous item in the Web Client's queue.",
        "purpose": "Handles 'previous', 'go back', 'play the last one again'.",
        "use_when": "the user wants to move back to the previous queued item.",
        "avoid_when": "there is nothing to go back to.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.seek": {
        "description": "Seek to a specific position, in seconds, in the Web Client.",
        "purpose": "Handles 'seek to 1:30', 'jump to the 2 minute mark'.",
        "use_when": "the user wants playback moved to a specific time.",
        "avoid_when": "the user wants to skip to a different item entirely.",
        "requires": "position_seconds, a non-negative number.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": (
            "If \"status\": \"invalid\", the position was negative or "
            "not a number. " + _FAILURE_SEMANTICS_NO_CLIENT
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "position_seconds": {
                    "type": "number",
                    "description": "Target position in seconds, e.g. 90 for 1:30.",
                },
            },
            "required": ["position_seconds"],
        },
    },
    "media.set_volume": {
        "description": "Set the playback volume in the Web Client.",
        "purpose": "Handles 'set volume to 50%', 'turn it up/down'.",
        "use_when": "the user gives an explicit or relative volume request.",
        "avoid_when": "the user wants to mute/unmute entirely (use mute/unmute).",
        "requires": "volume_percent, 0-100.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": (
            "If \"status\": \"invalid\", the value was outside 0-100. "
            + _FAILURE_SEMANTICS_NO_CLIENT
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "volume_percent": {
                    "type": "number",
                    "description": "Target volume, 0-100 (e.g. 50 for 50%).",
                },
            },
            "required": ["volume_percent"],
        },
    },
    "media.mute": {
        "description": "Mute audio output in the Web Client.",
        "purpose": "Handles 'mute', 'mute it'.",
        "use_when": "the user wants audio muted without stopping playback.",
        "avoid_when": "the user wants playback stopped/paused instead.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.unmute": {
        "description": "Unmute audio output in the Web Client.",
        "purpose": "Handles 'unmute', 'unmute it', 'turn the sound back on'.",
        "use_when": "audio is currently muted and the user wants it audible again.",
        "avoid_when": "audio is not currently muted.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.show": {
        "description": "Show the video/player surface in the Web Client.",
        "purpose": "Handles 'show the video', 'show the player'.",
        "use_when": "the user wants the visual player/video surface shown.",
        "avoid_when": "the media is audio-only.",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.hide": {
        "description": "Hide the video/player surface in the Web Client.",
        "purpose": "Handles 'hide the video', 'hide the player'.",
        "use_when": "the user wants the visual player/video surface hidden.",
        "avoid_when": "the user wants playback stopped entirely (use stop).",
        "requires": "nothing.",
        "result_semantics": _RESULT_SEMANTICS_DISPATCH_ONLY,
        "failure_semantics": _FAILURE_SEMANTICS_NO_CLIENT,
        "parameters": {"type": "object", "properties": {}},
    },
    "media.get_state": {
        "description": (
            "Read PARIKA's last known media playback state (status, "
            "current source, position, volume, etc.)."
        ),
        "purpose": "Answers 'what's playing', 'is it paused', 'what's the volume'.",
        "use_when": "the user asks about the current media/playback state.",
        "avoid_when": "the user wants to change playback, not just read it.",
        "requires": "nothing. Never dispatches a command to the Web Client - "
        "purely a read of PARIKA's own last-known state.",
        "result_semantics": (
            "Returns the last known state. This may be stale if the "
            "Web Client has not reported an update recently, and "
            "\"client_connected\": false means no Web Client is "
            "connected at all right now."
        ),
        "failure_semantics": "This operation cannot fail for a normal request.",
        "parameters": {"type": "object", "properties": {}},
    },
}
"""
Tool Affordance Contracts, registered as each Capability's
`CapabilityDefinition.metadata["tool_affordance"]` (see
`parika/modules/media/module_driver.py`).
"""


def create_media_tool(operation: MediaOperation) -> Tool:
    """Build the immutable Tool descriptor for one Media Capability."""

    capability_id = OPERATION_CAPABILITY_ID[operation]

    return Tool(
        id=OPERATION_TOOL_ID[operation],
        name=_TOOL_NAMES[operation],
        version=MEDIA_TOOL_VERSION,
        description=MEDIA_TOOL_AFFORDANCES[capability_id]["description"],
        capabilities=(capability_id,),
    )
