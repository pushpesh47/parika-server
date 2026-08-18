"""
PARIKA API - UI Context Handler

Handles the UI Context REST endpoint.
"""

from __future__ import annotations

from parika.api.auth.dependency import RequireAuth
from parika.api.auth.backend import AuthContext
from parika.api.dependencies import get_core_execution_owner
from parika.core.ui_context.exceptions import UIContextNotReadyError
from parika.core.ui_context.state import UIContextState
from parika.interfaces.runtime import ParikaRuntime


async def handle_get_ui_context(
    runtime: ParikaRuntime,
    auth: AuthContext,
) -> UIContextState:
    """
    Get the current semantic UI context snapshot.
    
    Args:
        runtime: PARIKA runtime with UI Context Projector
        auth: Authentication context
        
    Returns:
        Current UIContextState snapshot
        
    Raises:
        RuntimeError: If UI Context Projector is not ready
    """
    projector = runtime.ui_context_projector
    
    if not projector.is_ready():
        raise RuntimeError("UI Context Projector not ready")
    
    try:
        return projector.get_current_state()
    except UIContextNotReadyError as ex:
        raise RuntimeError(str(ex)) from ex