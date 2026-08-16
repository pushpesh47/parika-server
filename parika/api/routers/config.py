"""
PARIKA API - Configuration and Reload Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_core_execution_owner, get_runtime
from ..handlers.config import handle_config_get, handle_reload
from ..schemas.config import ConfigResponse, ReloadResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    key: str | None = None,
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> ConfigResponse:
    """
    Read-only Configuration view, mirroring `/config`. `Configuration`
    is read-only by design (see
    `docs/architecture/Core_Component_Responsibilities.md` section 1);
    this endpoint never accepts a write.
    """
    from ..requests import ConfigGetRequest
    result = handle_config_get(runtime, ConfigGetRequest(key=key))
    return ConfigResponse.model_validate(result)


@router.post("/reload", response_model=ReloadResponse)
async def reload_modules(
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ReloadResponse:
    """
    Reload every active Module and reconnect every registered
    Provider, mirroring `/reload`.
    """
    # Reload modifies state - must go through Core
    from ..requests import ReloadRequest
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(ReloadRequest())
    )
    result = await future
    return ReloadResponse.model_validate(result)
