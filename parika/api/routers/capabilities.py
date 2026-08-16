"""
PARIKA API - Capabilities Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_core_execution_owner, get_runtime
from ..handlers.capabilities import handle_capabilities_list, handle_capability_execute
from ..requests import CapabilityExecuteRequest
from ..schemas.capabilities import (
    CapabilitiesListResponse,
    CapabilityExecuteRequestBody,
    CapabilityExecuteResponse,
)

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=CapabilitiesListResponse)
async def list_capabilities(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> CapabilitiesListResponse:
    """List every registered capability, mirroring `/capabilities`."""
    result = handle_capabilities_list(runtime, None)
    return CapabilitiesListResponse(capabilities=result)


@router.post("/{capability_id}/execute", response_model=CapabilityExecuteResponse)
async def execute_capability(
    capability_id: str,
    body: CapabilityExecuteRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> CapabilityExecuteResponse:
    """
    Generic compatibility/fallback capability execution endpoint (see
    `docs/guides/Running.md` section 12.3). Prefer a dedicated
    domain-specific endpoint (e.g. `/api/v1/weather`) whenever one
    exists for this capability.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            CapabilityExecuteRequest(
                capability_id=capability_id,
                arguments=body.arguments,
                parameters=body.parameters,
            )
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return CapabilityExecuteResponse.model_validate(result)