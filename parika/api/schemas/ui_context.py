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
    FocusArea,
    SurfaceItem,
    SurfaceTier,
    UIContextState,
    UrgencyLevel,
)


class SurfaceItemSchema(ApiModel):
    """Wire-format surface item."""
    
    capability_id: str
    label: str
    tier: SurfaceTier
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        )