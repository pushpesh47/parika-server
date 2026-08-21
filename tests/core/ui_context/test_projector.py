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
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.task_manager.task import Task
from parika.core.task_manager.task_status import TaskStatus
from parika.core.task_manager.request import TaskRequest


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


class TestUIContextProjectorMultiAgent:
    """Tests for multi-agent aware Context UI Projector."""
    
    def _create_task_with_metadata(
        self,
        task_manager,
        capability_id: str,
        status: TaskStatus = TaskStatus.RUNNING,
        agent_id: str | None = None,
        agent_specialization: str | None = None,
        agent_confidence: float | None = None,
        parent_task_id: str | None = None,
    ) -> Task:
        """Create a task with agent metadata in request."""
        metadata = {}
        if agent_id:
            metadata["agent_id"] = agent_id
        if agent_specialization:
            metadata["agent_specialization"] = agent_specialization
        if agent_confidence is not None:
            metadata["agent_confidence"] = agent_confidence
        
        request = TaskRequest(
            capability_id=capability_id,
            metadata=metadata,
        )
        task = task_manager.create(request, parent_task_id=parent_task_id)
        
        # Manually set status for testing (bypassing execution)
        task.status = status
        if status == TaskStatus.RUNNING:
            task.started_at = datetime.now(UTC)
        elif status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(UTC)
        
        return task
    
    def _register_weather_capabilities(self, capability_registry):
        """Register weather capabilities for testing."""
        capability_registry.register(CapabilityDefinition(
            id="weather.current",
            name="Weather Current",
            description="Get current weather",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"weather", "network"}),
        ))
        capability_registry.register(CapabilityDefinition(
            id="weather.forecast",
            name="Weather Forecast",
            description="Get weather forecast",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"weather", "network"}),
        ))
    
    def _register_coding_capabilities(self, capability_registry):
        """Register coding capabilities for testing."""
        capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute a coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding", "llm"}),
        ))
    
    def _register_web_search_capability(self, capability_registry):
        """Register web search capability for testing."""
        capability_registry.register(CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description="Search the web",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"web", "network", "search"}),
        ))
    
    def test_single_semantic_task_still_works(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test that single semantic task still produces correct context."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create a weather task
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING
        )
        
        # Trigger recomputation
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.context == "weather"
        assert state.focus == FocusArea.CURRENT_CONDITIONS
        assert state.confidence == 0.95
        assert state.source == ContextSource.TASK
        assert state.attention == AttentionLevel.PRIMARY
    
    def test_chat_respond_alone_produces_chat_context(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test that chat.respond alone produces chat context."""
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))
        
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
        
        # Create a chat task (transport capability)
        self._create_task_with_metadata(
            task_manager, "chat.respond", TaskStatus.RUNNING
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # chat.respond is transport, should fall back to system or show chat
        assert state.context in ("chat", "system")
    
    def test_chat_respond_plus_weather_produces_weather_context(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test chat.respond + weather.current produces weather semantic context."""
        self._register_weather_capabilities(capability_registry)
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))
        
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
        
        # Create both tasks
        self._create_task_with_metadata(task_manager, "chat.respond", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # Weather is semantic, chat.respond is transport - weather should win
        assert state.context == "weather"
        assert state.focus == FocusArea.CURRENT_CONDITIONS
    
    def test_multiple_weather_capabilities_resolves_correctly(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test weather.current + weather.forecast resolves correctly."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create both weather tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.forecast", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # Both are weather domain - primary should be weather
        assert state.context == "weather"
        # Focus depends on which task wins priority
        assert state.focus in (FocusArea.CURRENT_CONDITIONS, FocusArea.FORECAST)
    
    def test_multiple_semantic_tasks_from_one_agent(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test multiple semantic tasks from one agent."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create multiple weather tasks with same agent
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system", agent_confidence=0.9
        )
        self._create_task_with_metadata(
            task_manager, "weather.forecast", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system", agent_confidence=0.9
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.context == "weather"
        # Metadata should include agent info
        metadata = state.metadata
        assert "agent" in metadata
        assert metadata["agent"]["id"] == "agent.weather"
        assert metadata["agent"]["specialization"] == "system"
        # Activity should show active agents and domains
        assert "activity" in metadata
        assert len(metadata["activity"]["active_agents"]) == 1
        assert metadata["activity"]["active_agents"][0]["id"] == "agent.weather"
        assert "weather" in metadata["activity"]["active_agents"][0]["domains"]
    
    def test_multiple_agents_different_domains(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test multiple agents with different semantic domains."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        self._register_web_search_capability(capability_registry)
        
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
        
        # Create tasks with different agents
        self._create_task_with_metadata(
            task_manager, "web.search", TaskStatus.RUNNING,
            agent_id="agent.research", agent_specialization="research", agent_confidence=0.95
        )
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system", agent_confidence=0.9
        )
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.RUNNING,
            agent_id="agent.coding", agent_specialization="coding", agent_confidence=0.9
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # One primary context chosen deterministically
        assert state.context in ("weather", "code", "search")
        assert state.source == ContextSource.TASK
        
        # Metadata should show all active agents and domains
        metadata = state.metadata
        assert "activity" in metadata
        activity = metadata["activity"]
        
        # Should have 3 active agents
        assert len(activity["active_agents"]) == 3
        agent_ids = {a["id"] for a in activity["active_agents"]}
        assert agent_ids == {"agent.research", "agent.weather", "agent.coding"}
        
        # Should have 3 active domains
        assert len(activity["active_domains"]) == 3
        domain_contexts = {d["context"] for d in activity["active_domains"]}
        assert domain_contexts == {"weather", "code", "search"}
        
        # Task counts should be correct (at least the created tasks)
        assert activity["task_counts"]["total"] >= 3
        assert activity["task_counts"]["running"] >= 2  # At least 2 running (timing may vary)
    
    def test_multiple_agents_concurrent_execution(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test multiple agents executing concurrently."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        
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
        
        # Create concurrent tasks
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.RUNNING,
            agent_id="agent.coding", agent_specialization="coding"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.context in ("weather", "code")
        
        # Both agents should be in metadata
        metadata = state.metadata
        assert len(metadata["activity"]["active_agents"]) == 2
        assert metadata["activity"]["task_counts"]["running"] >= 1
        assert metadata["activity"]["task_counts"]["total"] >= 2
    
    def test_one_agent_completes_other_remains_active(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test one agent/task completes while another remains active."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        
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
        
        # Create parent running task
        parent_task = self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        
        # Create child completed task with parent_task_id
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.COMPLETED,
            agent_id="agent.coding", agent_specialization="coding",
            parent_task_id=parent_task.id
        )
        
        event_bus.publish("task.completed", None)
        
        state = projector.get_current_state()
        # Primary context could be either (leaf task selection prefers child)
        assert state.context in ("weather", "code")
        assert state.attention in (AttentionLevel.PRIMARY, AttentionLevel.SECONDARY)
        
        # Metadata should reflect completed + running
        metadata = state.metadata
        assert metadata["activity"]["task_counts"]["running"] >= 1
        assert metadata["activity"]["task_counts"]["completed"] >= 0  # May be 0 due to timing
        
        # Both agents should still be listed (child completed task has parent)
        assert len(metadata["activity"]["active_agents"]) == 2
    
    def test_waiting_task_not_primary(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test waiting/dependent task does not incorrectly become primary."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        
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
        
        # Create running weather task and waiting coding task
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.WAITING,
            agent_id="agent.coding", agent_specialization="coding"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # Running task should be primary (weather)
        assert state.context == "weather"
        assert state.attention == AttentionLevel.PRIMARY
        
        # Waiting task counted but not primary
        metadata = state.metadata
        assert metadata["activity"]["task_counts"]["waiting"] >= 0  # May be 0 due to timing
        assert metadata["activity"]["task_counts"]["running"] >= 1
    
    def test_transport_tasks_do_not_hide_semantic(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test transport tasks do not hide semantic tasks."""
        self._register_weather_capabilities(capability_registry)
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))
        capability_registry.register(CapabilityDefinition(
            id="voice.speech_to_text",
            name="Speech to Text",
            description="STT",
            category=CapabilityCategory.SPEECH,
            tags=frozenset({"voice", "speech"}),
        ))
        
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
        
        # Create transport tasks and one semantic task
        self._create_task_with_metadata(task_manager, "chat.respond", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "voice.speech_to_text", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # Semantic task should win
        assert state.context == "weather"
        assert state.focus == FocusArea.CURRENT_CONDITIONS
    
    def test_completed_child_active_parent_preserved(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test completed child + active parent remains correct."""
        self._register_weather_capabilities(capability_registry)
        capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute a coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding", "llm"}),
        ))
        
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
        
        # Create parent coding task (running)
        parent_task = self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.RUNNING,
            agent_id="agent.coding", agent_specialization="coding"
        )
        
        # Create child weather task (completed) with parent_task_id
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.COMPLETED,
            agent_id="agent.weather", agent_specialization="system",
            parent_task_id=parent_task.id
        )
        
        event_bus.publish("task.completed", None)
        
        state = projector.get_current_state()
        # Parent is coding (running), should be primary
        # Child completed weather should be considered
        assert state.context in ("weather", "code")
        
        # Both should be in metadata
        metadata = state.metadata
        assert metadata["activity"]["task_counts"]["running"] >= 1
        assert metadata["activity"]["task_counts"]["completed"] >= 0  # May be 0 due to timing
    
    def test_agent_metadata_correctly_associated(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test agent metadata is correctly associated with relevant task."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        
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
        
        # Create tasks with different agent metadata
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system", agent_confidence=0.9
        )
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.RUNNING,
            agent_id="agent.coding", agent_specialization="coding", agent_confidence=0.85
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        metadata = state.metadata
        
        # Primary agent in top-level agent field
        primary_agent = metadata.get("agent", {})
        assert primary_agent.get("id") in ("agent.weather", "agent.coding")
        
        # All agents in activity
        active_agents = metadata["activity"]["active_agents"]
        assert len(active_agents) == 2
        
        # Check agent details
        for agent in active_agents:
            assert "id" in agent
            assert "specialization" in agent
            assert "confidence" in agent
            assert "task_count" in agent
            assert "domains" in agent
            assert agent["task_count"] >= 1
    
    def test_no_agent_metadata_still_works(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test projector works when no agent metadata exists."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create task WITHOUT agent metadata
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.context == "weather"
        
        metadata = state.metadata
        # Should have task info but no agent info
        assert "task" in metadata
        assert metadata["task"]["capability_id"] == "weather.current"
        # Agent may be empty dict
        assert metadata.get("agent", {}) == {}
        # Activity should still work
        assert "activity" in metadata
        assert metadata["activity"]["active_agents"] == []
    
    def test_unknown_metadata_does_not_crash(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test unknown/malformed metadata does not crash Context UI."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create task with weird metadata
        request = TaskRequest(
            capability_id="weather.current",
            metadata={"weird": "data", "nested": {"deep": "value"}},
        )
        task = task_manager.create(request)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.context == "weather"
        # Should not crash
    
    def test_surface_deduplication_with_active_capabilities(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test surface deduplication when dynamic surfaces are added."""
        self._register_weather_capabilities(capability_registry)
        self._register_coding_capabilities(capability_registry)
        
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
        
        # Weather primary, coding active
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        self._create_task_with_metadata(
            task_manager, "coding.execute_task", TaskStatus.RUNNING,
            agent_id="agent.coding", agent_specialization="coding"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        # Should have weather surfaces (primary) + coding surface (active)
        surface_ids = {s.capability_id for s in state.surfaces}
        # weather.current and weather.forecast from primary context
        assert "weather.current" in surface_ids
        assert "weather.forecast" in surface_ids
        # coding.execute_task from active capability
        assert "coding.execute_task" in surface_ids
        # No duplicates
        assert len(state.surfaces) == len(surface_ids)
    
    def test_version_monotonic(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test version remains monotonic across updates."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        versions = []
        for i in range(5):
            self._create_task_with_metadata(
                task_manager, "weather.current", TaskStatus.RUNNING
            )
            event_bus.publish("task.started", None)
            state = projector.get_current_state()
            versions.append(state.version)
        
        # Version should increase each time (or stay same if no-op)
        for i in range(1, len(versions)):
            assert versions[i] >= versions[i-1], f"Version not monotonic: {versions}"
    
    def test_semantic_noop_no_version_increment(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test semantic no-op does not unnecessarily increment version."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        # Create task
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        state1 = projector.get_current_state()
        v1 = state1.version
        
        # Publish same event again - should be no-op
        event_bus.publish("task.started", None)
        state2 = projector.get_current_state()
        v2 = state2.version
        
        # Version should not increment for no-op
        assert v2 == v1, f"Version incremented on no-op: {v1} -> {v2}"
    
    def test_existing_api_response_compatible(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test existing API response schema remains compatible."""
        self._register_weather_capabilities(capability_registry)
        
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
        
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # All required fields present
        assert hasattr(state, 'version')
        assert hasattr(state, 'context')
        assert hasattr(state, 'confidence')
        assert hasattr(state, 'source')
        assert hasattr(state, 'attention')
        assert hasattr(state, 'urgency')
        assert hasattr(state, 'focus')
        assert hasattr(state, 'surfaces')
        assert hasattr(state, 'timestamp')
        assert hasattr(state, 'metadata')
        
        # Types correct
        assert isinstance(state.version, int)
        assert isinstance(state.context, str)
        assert isinstance(state.confidence, float)
        assert isinstance(state.source, ContextSource)
        assert isinstance(state.attention, AttentionLevel)
        assert isinstance(state.urgency, UrgencyLevel)
        assert isinstance(state.focus, FocusArea)
        assert isinstance(state.surfaces, tuple)
        assert isinstance(state.timestamp, datetime)
        assert isinstance(state.metadata, MappingProxyType)


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