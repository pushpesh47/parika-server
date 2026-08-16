"""
PARIKA API - Status Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_runtime
from ..handlers.status import handle_status
from ..schemas.status import StatusResponse

router = APIRouter(prefix="/status", tags=["status"])


@router.get("", response_model=StatusResponse)
async def get_status(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> StatusResponse:
    """
    Aggregate runtime status snapshot, mirroring the existing
    `/status` slash command.
    """
    result = handle_status(runtime, None)
    return StatusResponse.model_validate(result)
