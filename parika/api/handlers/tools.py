"""
PARIKA API - Tools Handler
"""

from __future__ import annotations

from typing import Any

from parika.interfaces.runtime import ParikaRuntime

from ..requests import ToolsListRequest


def handle_tools_list(runtime: ParikaRuntime, request: ToolsListRequest | None) -> list[dict[str, Any]]:
    """
    Return every registered Tool, mirroring `/tools`.
    """

    return [
        {
            "id": tool.id,
            "name": tool.name,
            "version": tool.version,
            "description": tool.description,
            "capabilities": list(tool.capabilities),
            "enabled": tool.enabled,
        }
        for tool in sorted(runtime.tool_manager.get_all(), key=lambda item: item.id)
    ]
