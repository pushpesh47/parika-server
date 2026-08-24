"""
PARIKA UI Context Package.

Provides semantic UI context projection for the Web Client.
Server-side semantic context only - no visual rendering logic.
"""

from .events import UIContextChanged, UI_CONTEXT_CHANGED_EVENT
from .exceptions import UIContextError, UIContextNotReadyError, UIContextProjectionError
from .projector import UIContextProjector
from .state import (
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

__all__ = [
    "UIContextProjector",
    "UIContextState",
    "UIContextChanged",
    "UI_CONTEXT_CHANGED_EVENT",
    "UIContextError",
    "UIContextNotReadyError",
    "UIContextProjectionError",
    "ContextSource",
    "AttentionLevel",
    "UrgencyLevel",
    "RequestStatus",
    "FocusArea",
    "SurfaceTier",
    "SurfaceItem",
    "DomainInfo",
    "SynthesisInfo",
    "DependencyInfo",
]