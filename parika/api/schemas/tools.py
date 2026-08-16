"""
PARIKA API - Tool Schemas
"""

from __future__ import annotations

from .common import ApiModel


class ToolSummary(ApiModel):
    id: str
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = ()
    enabled: bool


class ToolsListResponse(ApiModel):
    tools: tuple[ToolSummary, ...] = ()
