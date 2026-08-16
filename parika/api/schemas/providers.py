"""
PARIKA API - Provider Schemas
"""

from __future__ import annotations

from .common import ApiModel


class ProviderModelSummary(ApiModel):
    id: str
    capabilities: tuple[str, ...] = ()


class ProviderSummary(ApiModel):
    id: str
    name: str
    enabled: bool
    state: str
    available: bool | None = None
    models: tuple[ProviderModelSummary, ...] = ()


class ProvidersListResponse(ApiModel):
    providers: tuple[ProviderSummary, ...] = ()
