"""
Tests for PARIKA UI Context Events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from parika.core.ui_context.events import UIContextChanged, UI_CONTEXT_CHANGED_EVENT
from parika.core.ui_context.state import UIContextState, SurfaceItem, ContextSource, AttentionLevel, UrgencyLevel, FocusArea, SurfaceTier


class TestUIContextChanged:
    """Tests for UIContextChanged event."""
    
    def test_create_valid_event(self) -> None:
        """Test creating a valid UI context changed event."""
        event = UIContextChanged(
            version=2,
            previous_version=1,
            changed_fields=frozenset({"context", "focus"}),
            source_event="task.started",
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({"task_id": "abc123"}),
        )
        
        assert event.version == 2
        assert event.previous_version == 1
        assert event.changed_fields == frozenset({"context", "focus"})
        assert event.source_event == "task.started"
        assert event.metadata["task_id"] == "abc123"
    
    def test_version_must_increase(self) -> None:
        """Test that version must be greater than previous_version."""
        with pytest.raises(ValueError, match="version must be greater than previous_version"):
            UIContextChanged(
                version=1,
                previous_version=2,
                changed_fields=frozenset({"context"}),
            )
    
    def test_version_non_negative(self) -> None:
        """Test that versions must be non-negative."""
        with pytest.raises(ValueError, match="version must be non-negative"):
            UIContextChanged(
                version=-1,
                previous_version=0,
                changed_fields=frozenset({"context"}),
            )
        
        with pytest.raises(ValueError, match="previous_version must be non-negative"):
            UIContextChanged(
                version=1,
                previous_version=-1,
                changed_fields=frozenset({"context"}),
            )
    
    def test_event_name_constant(self) -> None:
        """Test that event name constant is correct."""
        assert UI_CONTEXT_CHANGED_EVENT == "ui.context.changed"