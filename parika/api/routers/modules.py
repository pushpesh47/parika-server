"""
PARIKA API - Modules Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_core_execution_owner, get_runtime
from ..handlers.modules import handle_modules_list, handle_module_start, handle_module_stop
from ..schemas.modules import ModuleActionResponse, ModulesListResponse

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("", response_model=ModulesListResponse)
async def list_modules(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> ModulesListResponse:
    """List every registered Module, mirroring the existing `/modules` slash command."""
    result = handle_modules_list(runtime, None)
    return ModulesListResponse(modules=result)


@router.post("/{module_id}/start", response_model=ModuleActionResponse)
async def start_module(
    module_id: str,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ModuleActionResponse:
    """Start (load) a registered Module."""
    # Module start/stop modifies state - must go through Core
    from ..requests import ModuleStartRequest
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(ModuleStartRequest(module_id=module_id))
    )
    result = await future
    return ModuleActionResponse.model_validate(result)


@router.post("/{module_id}/stop", response_model=ModuleActionResponse)
async def stop_module(
    module_id: str,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ModuleActionResponse:
    """Stop (unload) an active Module."""
    # Module start/stop modifies state - must go through Core
    from ..requests import ModuleStopRequest
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(ModuleStopRequest(module_id=module_id))
    )
    result = await future
    return ModuleActionResponse.model_validate(result)
