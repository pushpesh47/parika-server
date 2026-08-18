"""
Tests for PARIKA UI Context State Models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from parika.core.ui_context.state import (
    UIContextState,
    SurfaceItem,
    ContextSource,
    AttentionLevel,
    UrgencyLevel,
    FocusArea,
    SurfaceTier,
)


class TestSurfaceItem:
    """Tests for SurfaceItem."""
    
    def test_create_valid_surface_item(self) -> None:
        """Test creating a valid surface item."""
        surface = SurfaceItem(
            capability_id="weather.current",
            label="Current Conditions",
            tier=SurfaceTier.PRIMARY,
            metadata=MappingProxyType({"unit": "celsius"}),
        )
        
        assert surface.capability_id == "weather.current"
        assert surface.label == "Current Conditions"
        assert surface.tier == SurfaceTier.PRIMARY
        assert surface.metadata["unit"] == "celsius"
    
    def test_empty_capability_id_raises(self) -> None:
        """Test that empty capability_id raises ValueError."""
        with pytest.raises(ValueError, match="capability_id cannot be empty"):
            SurfaceItem(
                capability_id="",
                label="Test",
                tier=SurfaceTier.PRIMARY,
            )
    
    def test_empty_label_raises(self) -> None:
        """Test that empty label raises ValueError."""
        with pytest.raises(ValueError, match="label cannot be empty"):
            SurfaceItem(
                capability_id="test.capability",
                label="",
                tier=SurfaceTier.PRIMARY,
            )
    
    def test_invalid_tier_raises(self) -> None:
        """Test that invalid tier raises TypeError."""
        with pytest.raises(TypeError, match="tier must be a SurfaceTier"):
            SurfaceItem(
                capability_id="test.capability",
                label="Test",
                tier="primary",  # type: ignore
            )


class TestUIContextState:
    """Tests for UIContextState."""
    
    def test_create_valid_state(self) -> None:
        """Test creating a valid UI context state."""
        surfaces = (
            SurfaceItem(
                capability_id="weather.current",
                label="Current Conditions",
                tier=SurfaceTier.PRIMARY,
            ),
        )
        
        state = UIContextState(
            version=1,
            context="weather",
            confidence=0.95,
            source=ContextSource.TASK,
            attention=AttentionLevel.PRIMARY,
            urgency=UrgencyLevel.NORMAL,
            focus=FocusArea.CURRENT_CONDITIONS,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({"task_id": "abc123"}),
        )
        
        assert state.version == 1
        assert state.context == "weather"
        assert state.confidence == 0.95
        assert state.source == ContextSource.TASK
        assert state.attention == AttentionLevel.PRIMARY
        assert state.urgency == UrgencyLevel.NORMAL
        assert state.focus == FocusArea.CURRENT_CONDITIONS
        assert len(state.surfaces) == 1
        assert state.metadata["task_id"] == "abc123"
    
    def test_confidence_bounds(self) -> None:
        """Test confidence must be between 0.0 and 1.0."""
        surfaces = ()
        
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            UIContextState(
                version=0,
                context="test",
                confidence=1.5,
                source=ContextSource.FALLBACK,
                attention=AttentionLevel.AMBIENT,
                urgency=UrgencyLevel.NORMAL,
                focus=FocusArea.GENERAL,
                surfaces=surfaces,
                timestamp=datetime.now(UTC),
            )
        
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            UIContextState(
                version=0,
                context="test",
                confidence=-0.1,
                source=ContextSource.FALLBACK,
                attention=AttentionLevel.AMBIENT,
                urgency=UrgencyLevel.NORMAL,
                focus=FocusArea.GENERAL,
                surfaces=surfaces,
                timestamp=datetime.now(UTC),
            )
    
    def test_version_non_negative(self) -> None:
        """Test version must be non-negative."""
        surfaces = ()
        
        with pytest.raises(ValueError, match="version must be non-negative"):
            UIContextState(
                version=-1,
                context="test",
                confidence=0.5,
                source=ContextSource.FALLBACK,
                attention=AttentionLevel.AMBIENT,
                urgency=UrgencyLevel.NORMAL,
                focus=FocusArea.GENERAL,
                surfaces=surfaces,
                timestamp=datetime.now(UTC),
            )
    
    def test_empty_context_raises(self) -> None:
        """Test that empty context raises ValueError."""
        surfaces = ()
        
        with pytest.raises(ValueError, match="context cannot be empty"):
            UIContextState(
                version=0,
                context="",
                confidence=0.5,
                source=ContextSource.FALLBACK,
                attention=AttentionLevel.AMBIENT,
                urgency=UrgencyLevel.NORMAL,
                focus=FocusArea.GENERAL,
                surfaces=surfaces,
                timestamp=datetime.now(UTC),
            )
    
    def test_immutability(self) -> None:
        """Test that state is immutable."""
        surfaces = (
            SurfaceItem(
                capability_id="weather.current",
                label="Current Conditions",
                tier=SurfaceTier.PRIMARY,
            ),
        )
        
        state = UIContextState(
            version=1,
            context="weather",
            confidence=0.95,
            source=ContextSource.TASK,
            attention=AttentionLevel.PRIMARY,
            urgency=UrgencyLevel.NORMAL,
            focus=FocusArea.CURRENT_CONDITIONS,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
        )
        
        # dataclass with frozen=True should prevent modification
        with pytest.raises(Exception):
            state.version = 2  # type: ignore