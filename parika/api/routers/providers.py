"""
PARIKA API - Providers Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_runtime
from ..handlers.providers import handle_providers_list
from ..schemas.providers import ProvidersListResponse

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=ProvidersListResponse)
async def list_providers(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> ProvidersListResponse:
    """List every registered Provider, mirroring the existing `/providers` slash command."""
    result = handle_providers_list(runtime, None)
    return ProvidersListResponse(providers=result)
