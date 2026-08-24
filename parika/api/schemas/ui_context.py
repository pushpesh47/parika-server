"""
PARIKA API - UI Context Schemas

Wire-format Pydantic schemas for the UI Context REST endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import ApiModel
from parika.core.ui_context.state import (
    AttentionLevel,
    ContextSource,
    DependencyInfo,
    DomainInfo,
    FocusArea,
    RequestStatus,
    SurfaceItem,
    SurfaceTier,
    SynthesisInfo,
    UIContextState,
    UrgencyLevel,
)


class SurfaceItemSchema(ApiModel):
    """Wire-format surface item."""
    
    capability_id: str
    label: str
    tier: SurfaceTier
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainInfoSchema(ApiModel):
    """Wire-format domain info."""
    
    name: str
    focus: FocusArea
    importance: float = Field(ge=0.0, le=1.0)
    status: str
    capability_ids: list[str]


class SynthesisInfoSchema(ApiModel):
    """Wire-format synthesis info."""
    
    goal_id: str | None = None
    capability_id: str | None = None
    status: str
    depends_on: list[str] = Field(default_factory=list)
    completed_dependencies: list[str] = Field(default_factory=list)
    failed_dependencies: list[str] = Field(default_factory=list)


class DependencyInfoSchema(ApiModel):
    """Wire-format dependency info."""
    
    goal_id: str
    capability_id: str
    depends_on: list[str] = Field(default_factory=list)
    status: str
    is_synthesis: bool


class UIContextResponse(ApiModel):
    """Wire-format UI context response."""
    
    version: int
    context: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: ContextSource
    attention: AttentionLevel
    urgency: UrgencyLevel
    focus: FocusArea
    surfaces: list[SurfaceItemSchema]
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_status: RequestStatus
    domains: list[DomainInfoSchema] = Field(default_factory=list)
    synthesis: SynthesisInfoSchema | None = None
    dependencies: list[DependencyInfoSchema] = Field(default_factory=list)
    
    @classmethod
    def from_state(cls, state: UIContextState) -> "UIContextResponse":
        """Create response from UIContextState."""
        return cls(
            version=state.version,
            context=state.context,
            confidence=state.confidence,
            source=state.source,
            attention=state.attention,
            urgency=state.urgency,
            focus=state.focus,
            surfaces=[
                SurfaceItemSchema(
                    capability_id=surface.capability_id,
                    label=surface.label,
                    tier=surface.tier,
                    metadata=dict(surface.metadata),
                )
                for surface in state.surfaces
            ],
            timestamp=state.timestamp,
            metadata=dict(state.metadata),
            request_status=state.request_status,
            domains=[
                DomainInfoSchema(
                    name=domain.name,
                    focus=domain.focus,
                    importance=domain.importance,
                    status=domain.status,
                    capability_ids=list(domain.capability_ids),
                )
                for domain in state.domains
            ],
            synthesis=(
                SynthesisInfoSchema(
                    goal_id=state.synthesis.goal_id,
                    capability_id=state.synthesis.capability_id,
                    status=state.synthesis.status,
                    depends_on=list(state.synthesis.depends_on),
                    completed_dependencies=list(state.synthesis.completed_dependencies),
                    failed_dependencies=list(state.synthesis.failed_dependencies),
                )
                if state.synthesis else None
            ),
            dependencies=[
                DependencyInfoSchema(
                    goal_id=dep.goal_id,
                    capability_id=dep.capability_id,
                    depends_on=list(dep.depends_on),
                    status=dep.status,
                    is_synthesis=dep.is_synthesis,
                )
                for dep in state.dependencies
            ],
        )