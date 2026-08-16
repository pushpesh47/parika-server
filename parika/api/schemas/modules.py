"""
PARIKA API - Module Schemas
"""

from __future__ import annotations

from .common import ApiModel


class ModuleSummary(ApiModel):
    id: str
    version: str
    state: str


class ModulesListResponse(ApiModel):
    modules: tuple[ModuleSummary, ...] = ()


class ModuleActionResponse(ApiModel):
    module_id: str
    state: str
