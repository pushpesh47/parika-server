"""
Tests for PARIKA UI Context Projector.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from parika.core.ui_context.projector import UIContextProjector
from parika.core.ui_context.state import (
    UIContextState,
    SurfaceItem,
    ContextSource,
    AttentionLevel,
    UrgencyLevel,
    FocusArea,
    SurfaceTier,
)
from parika.core.ui_context.events import UIContextChanged, UI_CONTEXT_CHANGED_EVENT
from parika.core.ui_context.exceptions import UIContextNotReadyError


class TestUIContextProjector:
    """Tests for UIContextProjector."""
    
    def test_initialization(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test projector initialization."""
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
        )
        
        assert projector.is_ready()
        state = projector.get_current_state()
        assert state.version == 0
        assert state.context == "system"
        assert state.source == ContextSource.FALLBACK
    
    def test_start_stop(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test projector start/stop lifecycle."""
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
        )
        
        # Should already be started in __init__ via _initialize_fallback_state
        assert projector._subscribed is False  # Not started yet
        
        projector.start()
        assert projector._subscribed is True
        
        projector.stop()
        assert projector._subscribed is False
        assert projector._shutdown is True
        
        # Cannot start after shutdown
        with pytest.raises(Exception, match="Cannot start after shutdown"):
            projector.start()
    
    def test_get_current_state(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test getting current state."""
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
        )
        
        state = projector.get_current_state()
        assert isinstance(state, UIContextState)
        assert state.version == 0
    
    def test_shutdown_raises_not_ready(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test that getting state after shutdown raises error."""
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
        )
        
        projector.start()
        projector.stop()
        
        with pytest.raises(UIContextNotReadyError, match="Projector has been shut down"):
            projector.get_current_state()
    
    def test_event_subscriptions(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test that projector subscribes to correct events."""
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
        )
        
        projector.start()
        
        # Check that subscriptions were made
        # We can't easily inspect the event_bus internals, but we can verify
        # the subscriber was registered by checking the subscription count
        # This is a basic sanity check
        assert projector._subscribed is True
        
        projector.stop()


# Fixtures
@pytest.fixture
def event_bus(logger):
    """Create a real EventBus for testing."""
    from parika.core.event_bus.event_bus import EventBus
    return EventBus(logger)


@pytest.fixture
def logger(configuration):
    """Create a real Logger for testing."""
    from parika.core.logger.logger import Logger
    return Logger(configuration)


@pytest.fixture
def configuration():
    """Create a Configuration for testing."""
    from parika.core.configuration.configuration import Configuration
    return Configuration()


@pytest.fixture
def task_manager(event_bus, logger):
    """Create a TaskManager for testing."""
    from parika.core.capability_executor.capability_executor import CapabilityExecutor
    from parika.core.tool_manager.tool_manager import ToolManager
    from parika.core.provider_manager.provider_manager import ProviderManager
    from parika.core.task_manager.task_manager import TaskManager
    
    tool_manager = ToolManager(event_bus=event_bus, logger=logger)
    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    capability_executor = CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )
    return TaskManager(
        event_bus=event_bus,
        logger=logger,
        capability_executor=capability_executor,
    )


@pytest.fixture
def workflow_engine():
    """Create a mock WorkflowEngine for testing."""
    from parika.core.workflow_engine.workflow_engine import WorkflowEngine
    return MagicMock(spec=WorkflowEngine)


@pytest.fixture
def context_manager(event_bus, logger):
    """Create a ContextManager for testing."""
    from parika.core.context_manager.context_manager import ContextManager
    return ContextManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def state_manager(logger):
    """Create a StateManager for testing."""
    from parika.core.state_manager.state_manager import StateManager
    return StateManager(logger)


@pytest.fixture
def capability_registry(event_bus, logger):
    """Create a CapabilityRegistry for testing."""
    from parika.core.capability_registry.capability_registry import CapabilityRegistry
    return CapabilityRegistry(event_bus=event_bus, logger=logger)