"""
PARIKA API - Media Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_runtime
from ..handlers.media import handle_media_get_state
from ..schemas.media import MediaStateResponseBody

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/state", response_model=MediaStateResponseBody)
async def get_state(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> MediaStateResponseBody:
    """
    Read PARIKA's last known media playback state. May be stale if no
    Web Client has reported recently; `client_connected=false` means
    no Web Client is connected at all right now.
    """
    from ..requests import MediaGetStateRequest
    result = handle_media_get_state(runtime, MediaGetStateRequest())
    return MediaStateResponseBody.model_validate(result)