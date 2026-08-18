"""
PARIKA UI Context Events.

Immutable event payloads published through the existing EventBus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from .state import UIContextState


@dataclass(frozen=True, slots=True, kw_only=True)
class UIContextChanged:
    """
    Published when the semantic UI context changes.
    
    Uses existing PARIKA event naming convention: ui.context.changed
    """
    
    version: int
    """New semantic version"""
    
    previous_version: int
    """Previous semantic version"""
    
    changed_fields: frozenset[str]
    """Set of field names that changed semantically"""
    
    source_event: str | None = None
    """Name of the Core event that triggered this change, if any"""
    
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    """UTC timestamp of this event"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Additional event metadata"""

    def __post_init__(self) -> None:
        """Validate event after initialization."""
        if type(self.version) is not int:
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        
        if type(self.previous_version) is not int:
            raise TypeError("previous_version must be an integer")
        if self.previous_version < 0:
            raise ValueError("previous_version must be non-negative")
        
        if self.version <= self.previous_version:
            raise ValueError("version must be greater than previous_version")
        
        if type(self.changed_fields) is not frozenset:
            raise TypeError("changed_fields must be a frozenset")
        for field_name in self.changed_fields:
            if type(field_name) is not str:
                raise TypeError("each changed_field must be a string")
        
        if self.source_event is not None and type(self.source_event) is not str:
            raise TypeError("source_event must be a string or None")
        
        if type(self.timestamp) is not datetime:
            raise TypeError("timestamp must be a datetime")
        
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


# Event name constant for EventBus subscription/publishing
UI_CONTEXT_CHANGED_EVENT = "ui.context.changed"