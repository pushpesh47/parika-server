"""
PARIKA UI Context State Models.

Immutable semantic snapshot for server-side contextual HUD.
Contains NO visual rendering logic - only semantic meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ContextSource(StrEnum):
    """
    Source of the current semantic context.
    
    Represents WHY the current semantic context was selected.
    """
    
    CAPABILITY = "capability"
    WORKFLOW = "workflow"
    TASK = "task"
    INTERACTION = "interaction"
    SYSTEM = "system"
    FALLBACK = "fallback"


class AttentionLevel(StrEnum):
    """
    Attention level independent from semantic context.
    
    Conceptually: primary, secondary, ambient
    """
    
    PRIMARY = "primary"
    SECONDARY = "secondary"
    AMBIENT = "ambient"


class UrgencyLevel(StrEnum):
    """
    Urgency level independent from context.
    
    Conceptually: normal, elevated, critical
    """
    
    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class FocusArea(StrEnum):
    """
    Semantic sub-context focus areas.
    
    Examples:
    - weather -> forecast, current_conditions
    - expense -> monthly_summary
    - media -> playback
    - chat -> general
    """
    
    GENERAL = "general"
    FORECAST = "forecast"
    CURRENT_CONDITIONS = "current_conditions"
    MONTHLY_SUMMARY = "monthly_summary"
    PLAYBACK = "playback"
    SEARCH_RESULTS = "search_results"
    FILE_BROWSER = "file_browser"
    CODE_EDITOR = "code_editor"
    DOCUMENT_VIEWER = "document_viewer"
    IMAGE_VIEWER = "image_viewer"
    VIDEO_PLAYER = "video_player"
    VOICE_INPUT = "voice_input"
    SETTINGS = "settings"
    HELP = "help"


class SurfaceTier(StrEnum):
    """
    Semantic surface tiers.
    
    Primary: Main capabilities/information for current context
    Secondary: Supporting capabilities/information
    Ambient: Background/system information
    """
    
    PRIMARY = "primary"
    SECONDARY = "secondary"
    AMBIENT = "ambient"


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceItem:
    """
    Semantic surface item.
    
    Represents a capability or information element relevant to the current context.
    MUST remain semantic - no visual rendering instructions.
    """
    
    capability_id: str
    """Capability identifier (e.g., 'weather.current', 'weather.forecast')"""
    
    label: str
    """Human-readable label for the surface"""
    
    tier: SurfaceTier
    """Semantic tier: primary, secondary, or ambient"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Optional semantic metadata"""

    def __post_init__(self) -> None:
        """Validate surface item after initialization."""
        if not self.capability_id.strip():
            raise ValueError("capability_id cannot be empty")
        if not self.label.strip():
            raise ValueError("label cannot be empty")
        if type(self.tier) is not SurfaceTier:
            raise TypeError("tier must be a SurfaceTier")
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UIContextState:
    """
    Immutable semantic UI context snapshot.
    
    Server-side semantic state only - NO visual rendering logic.
    The Web Client interprets this state using PARIKA Visual Grammar.
    
    Attributes:
        version: Monotonically increasing semantic version
        context: Current semantic domain (e.g., 'weather', 'expense', 'chat')
        confidence: Context confidence (0.0 to 1.0)
        source: Why this context was selected
        attention: Current attention level (primary/secondary/ambient)
        urgency: Current urgency level (normal/elevated/critical)
        focus: Current semantic sub-context focus
        surfaces: Semantic capabilities/information organized by tier
        timestamp: UTC timestamp of this snapshot
        metadata: Additional semantic metadata
    """
    
    version: int
    """Monotonically increasing semantic version"""
    
    context: str
    """Current semantic domain"""
    
    confidence: float
    """Context confidence (0.0 <= confidence <= 1.0)"""
    
    source: ContextSource
    """Source of the current semantic context"""
    
    attention: AttentionLevel
    """Current attention level"""
    
    urgency: UrgencyLevel
    """Current urgency level"""
    
    focus: FocusArea
    """Current semantic sub-context focus"""
    
    surfaces: tuple[SurfaceItem, ...]
    """Semantic capabilities/information organized by tier"""
    
    timestamp: datetime
    """UTC timestamp of this snapshot"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Additional semantic metadata"""

    def __post_init__(self) -> None:
        """Validate UI context state after initialization."""
        if type(self.version) is not int:
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        
        if type(self.context) is not str:
            raise TypeError("context must be a string")
        if not self.context.strip():
            raise ValueError("context cannot be empty")
        
        if type(self.confidence) is not float:
            raise TypeError("confidence must be a float")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        
        if type(self.source) is not ContextSource:
            raise TypeError("source must be a ContextSource")
        
        if type(self.attention) is not AttentionLevel:
            raise TypeError("attention must be an AttentionLevel")
        
        if type(self.urgency) is not UrgencyLevel:
            raise TypeError("urgency must be an UrgencyLevel")
        
        if type(self.focus) is not FocusArea:
            raise TypeError("focus must be a FocusArea")
        
        if type(self.surfaces) is not tuple:
            raise TypeError("surfaces must be a tuple")
        for surface in self.surfaces:
            if type(surface) is not SurfaceItem:
                raise TypeError("each surface must be a SurfaceItem")
        
        if type(self.timestamp) is not datetime:
            raise TypeError("timestamp must be a datetime")
        
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )