"""
PARIKA API - Capability Schemas
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import ApiModel


class CapabilitySummary(ApiModel):
    id: str
    name: str
    description: str
    category: str
    enabled: bool


class CapabilitiesListResponse(ApiModel):
    capabilities: tuple[CapabilitySummary, ...] = ()


class CapabilityExecuteRequestBody(ApiModel):
    """
    Request body for the generic compatibility/fallback endpoint
    `POST /api/v1/capabilities/{id}/execute` (see
    `docs/guides/Running.md` section 12.3).

    Prefer a dedicated domain-specific endpoint when one exists for
    this capability; this endpoint exists so that no capability is
    ever unreachable while its dedicated endpoint is still being
    built.
    """

    arguments: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class CapabilityExecuteResponse(ApiModel):
    capability_id: str
    result: Any = None
    attributes: dict[str, Any] = Field(default_factory=dict)
