"""
PARIKA API - Media Handler

Translates `GET /api/v1/media/state` into a direct read of the shared
`MediaStateStore` (via `ServiceContainer`) - exactly like
`parika/api/handlers/voice.py::handle_voice_get_settings()` reads the
shared `VoiceLanguagePreferenceStore` directly rather than through
`ToolManager`/`Brain`: this is a pure state read, not a capability
execution, so it never constructs a `Goal`/`BrainRequest` and never
calls `ToolManager`/`Brain`/`Planner` - see
`parika/api/handlers/__init__.py`'s orchestration/translation-only
rule.
"""

from __future__ import annotations

from typing import Any

from parika.interfaces.runtime import ParikaRuntime
from parika.tools.media.state_store import MediaStateStore

from ..requests import MediaGetStateRequest


def handle_media_get_state(
    runtime: ParikaRuntime, request: MediaGetStateRequest
) -> dict[str, Any]:
    """
    Read PARIKA's last known media playback state.

    This may be stale if the Web Client has not reported an update
    recently, and `client_connected=False` means no Web Client is
    connected over `WS /api/v1/ws/media/{client_id}` at all right now
    - see `docs/guides/Running.md`'s Media API section.
    """

    state_store = runtime.service_container.get(MediaStateStore)
    return state_store.get().to_dict()
