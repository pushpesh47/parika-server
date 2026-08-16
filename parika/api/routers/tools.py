"""
PARIKA API - Tools Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_runtime
from ..handlers.tools import handle_tools_list
from ..schemas.tools import ToolsListResponse

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolsListResponse)
async def list_tools(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> ToolsListResponse:
    """List every registered Tool, mirroring the existing `/tools` slash command."""
    result = handle_tools_list(runtime, None)
    return ToolsListResponse(tools=result)
