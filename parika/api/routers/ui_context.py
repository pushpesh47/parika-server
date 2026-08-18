"""
PARIKA API - UI Context Router

REST endpoint for server-side semantic UI context.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.dependency import RequireAuth
from ..auth.backend import AuthContext
from ..dependencies import get_runtime
from ..handlers.ui_context import handle_get_ui_context
from ..schemas.ui_context import UIContextResponse
from parika.interfaces.runtime import ParikaRuntime

router = APIRouter(prefix="/ui", tags=["ui-context"])


@router.get("/context", response_model=UIContextResponse)
async def get_ui_context(
    auth: AuthContext = RequireAuth,
    runtime: ParikaRuntime = Depends(get_runtime),
) -> UIContextResponse:
    """
    Get the current semantic UI context snapshot.
    
    Returns the server-side semantic state for the Contextual HUD.
    The Web Client interprets this state using PARIKA Visual Grammar.
    
    Response includes:
    - version: Monotonically increasing semantic version
    - context: Current semantic domain (weather, expense, chat, etc.)
    - confidence: Context confidence (0.0 to 1.0)
    - source: Why this context was selected (capability, workflow, task, interaction, system, fallback)
    - attention: Attention level (primary, secondary, ambient)
    - urgency: Urgency level (normal, elevated, critical)
    - focus: Current semantic sub-context focus
    - surfaces: Semantic capabilities organized by tier (primary, secondary, ambient)
    - timestamp: UTC timestamp of this snapshot
    
    Authentication:
        Requires valid authentication per [api.auth].mode configuration.
    
    Errors:
        401: Authentication required
        500: UI Context Projector not ready
    """
    state = await handle_get_ui_context(runtime, auth)
    return UIContextResponse.from_state(state)