"""
PARIKA API - Health, Readiness, and Liveness Router

Deliberately unauthenticated and never routed through `Router.dispatch`
-- `/health`/`/live` must be answerable even before `ParikaRuntime`
exists (see `docs/guides/Running.md` section 12.4).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from ..schemas.status import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Basic reachability -- always `200` the instant the ASGI app exists."""

    return HealthResponse(status="ok")


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Process liveness -- the event loop is responsive."""

    return HealthResponse(status="ok")


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """
    Readiness -- `200` only once CoreExecutionOwner has been started
    and the single Runtime/Core environment has been successfully
    initialized on the Core worker thread; `503` before that
    (e.g. during the brief startup window or if initialization failed).
    """
    
    core_execution_owner = getattr(request.app.state, "core_execution_owner", None)
    
    # Check if CoreExecutionOwner exists and is initialized
    if core_execution_owner is not None and core_execution_owner.wait_for_ready(timeout=0):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=ReadyResponse(status="ready").model_dump(),
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ReadyResponse(status="starting").model_dump(),
    )
