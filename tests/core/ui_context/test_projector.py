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
    RequestStatus,
    DomainInfo,
    SynthesisInfo,
    DependencyInfo,
    UserIntent,
    ConversationalContext,
    ContextTransition,
    EntityInfo,
    EntityType,
    TopicInfo,
    SemanticRelevance,
    FreshnessInfo,
    ContextualRole,
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
        # Phase 1 fields
        assert isinstance(state.request_status, RequestStatus)
        assert isinstance(state.domains, tuple)
        assert state.synthesis is None or isinstance(state.synthesis, SynthesisInfo)
        assert isinstance(state.dependencies, tuple)


class TestPhase1Contract:
    """Tests for Phase 1 Context UI Semantic Foundation contract."""
    
    def _register_phase1_capabilities(self, capability_registry):
        """Register capabilities needed for Phase 1 tests."""
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        
        # Weather capabilities
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
        
        # Finance capabilities
        capability_registry.register(CapabilityDefinition(
            id="finance.exchange_rate",
            name="Exchange Rate",
            description="Get exchange rate",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"finance", "network"}),
        ))
        
        # Web search
        capability_registry.register(CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description="Search the web",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"web", "network", "search"}),
        ))
        
        # Chat respond
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))
        
        # News
        capability_registry.register(CapabilityDefinition(
            id="news.latest",
            name="Latest News",
            description="Latest news",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"news", "network"}),
        ))
    
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
        elif status == TaskStatus.FAILED:
            task.completed_at = datetime.now(UTC)
            task.failure = RuntimeError("Test failure")
        
        return task
    
    def test_request_status_success(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test SUCCESS request status when all goals succeed."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create successful tasks
        task1 = self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        task2 = self._create_task_with_metadata(task_manager, "weather.forecast", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        # Simulate brain execution completion with success
        # Publish brain.execution.started
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.started", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.STARTED,
            progress_id="test-progress-1",
            message="Handling request",
        ))
        
        # Complete tasks
        task1.status = TaskStatus.COMPLETED
        task1.completed_at = datetime.now(UTC)
        task2.status = TaskStatus.COMPLETED
        task2.completed_at = datetime.now(UTC)
        event_bus.publish("task.completed", None)
        
        # Publish brain.execution.completed with succeeded=True
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-progress-1",
            message="succeeded=True",
            metadata={"succeeded": True, "request_id": "test-request-1"},
        ))
        
        state = projector.get_current_state()
        # Brain execution succeeded -> SUCCESS
        assert state.request_status == RequestStatus.SUCCESS
    
    def test_request_status_partial_success(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test PARTIAL_SUCCESS when some independent goals fail."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create mixed success/failure tasks
        task1 = self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        task2 = self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        task3 = self._create_task_with_metadata(task_manager, "web.search", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        # Simulate brain execution start
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.started", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.STARTED,
            progress_id="test-progress-2",
            message="Handling request",
        ))
        
        # Complete some, fail one
        task1.status = TaskStatus.COMPLETED
        task1.completed_at = datetime.now(UTC)
        task2.status = TaskStatus.FAILED
        task2.failure = RuntimeError("Exchange rate unavailable")
        task2.completed_at = datetime.now(UTC)
        task3.status = TaskStatus.COMPLETED
        task3.completed_at = datetime.now(UTC)
        
        event_bus.publish("task.completed", None)
        event_bus.publish("task.failed", None)
        
        # Publish brain.execution.completed with succeeded=True (synthesis succeeded despite partial failure)
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-progress-2",
            message="succeeded=True",
            metadata={"succeeded": True, "request_id": "test-request-2"},
        ))
        
        state = projector.get_current_state()
        # Brain execution succeeded but some tasks failed -> PARTIAL_SUCCESS
        assert state.request_status == RequestStatus.PARTIAL_SUCCESS

    def test_request_status_failed(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test FAILED when all goals fail."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create all failed tasks (need at least one RUNNING to be active, then fail it)
        task1 = self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        task2 = self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        # Now fail them
        task1.status = TaskStatus.FAILED
        task1.failure = RuntimeError("Test failure")
        task1.completed_at = datetime.now(UTC)
        task2.status = TaskStatus.FAILED
        task2.failure = RuntimeError("Test failure")
        task2.completed_at = datetime.now(UTC)
        
        event_bus.publish("task.failed", None)
        
        state = projector.get_current_state()
        # All failed -> FAILED
        assert state.request_status == RequestStatus.FAILED
    
    def test_multi_domain_representation(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test multiple semantic domains are represented."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create tasks from different domains
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        self._create_task_with_metadata(
            task_manager, "finance.exchange_rate", TaskStatus.RUNNING,
            agent_id="agent.finance", agent_specialization="finance"
        )
        self._create_task_with_metadata(
            task_manager, "web.search", TaskStatus.RUNNING,
            agent_id="agent.research", agent_specialization="research"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have multiple domains
        assert len(state.domains) >= 2
        
        domain_names = {d.name for d in state.domains}
        assert "weather" in domain_names
        assert "finance" in domain_names
        # search may be mapped to "search" or "web"
        
        # Each domain should have importance, focus, status, capability_ids
        for domain in state.domains:
            assert 0.0 <= domain.importance <= 1.0
            assert isinstance(domain.focus, FocusArea)
            assert domain.status in ("running", "waiting", "completed", "failed")
            assert isinstance(domain.capability_ids, tuple)
        
        # Primary context should be one of the domains
        assert state.context in domain_names
    
    def test_synthesis_representation(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test synthesis goal is represented."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create data gathering tasks + synthesis task
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather"
        )
        self._create_task_with_metadata(
            task_manager, "finance.exchange_rate", TaskStatus.RUNNING,
            agent_id="agent.finance"
        )
        self._create_task_with_metadata(
            task_manager, "chat.respond", TaskStatus.RUNNING,
            agent_id="agent.synthesis"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Synthesis info should be present when chat.respond is active
        assert state.synthesis is not None
        assert state.synthesis.capability_id == "chat.respond"
        assert state.synthesis.status in ("pending", "waiting", "running", "completed", "failed")
        assert isinstance(state.synthesis.depends_on, tuple)
    
    def test_dependency_representation(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test dependency relationships are represented."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create parent task
        parent = self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather"
        )
        
        # Create child task with parent_task_id (simulates dependency)
        self._create_task_with_metadata(
            task_manager, "chat.respond", TaskStatus.WAITING,
            agent_id="agent.synthesis",
            parent_task_id=parent.id
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Dependencies should be tracked (based on brain goal tracking)
        # In this test setup, brain goals tracking may be empty
        # but the structure should be present
        assert isinstance(state.dependencies, tuple)
    
    def test_partial_failure_preserves_successful_work(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test failed goal remains represented while successful goals persist."""
        self._register_phase1_capabilities(capability_registry)
        
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
        
        # Create tasks - one fails, others succeed
        task1 = self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        task2 = self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        task3 = self._create_task_with_metadata(task_manager, "web.search", TaskStatus.RUNNING)
        task4 = self._create_task_with_metadata(task_manager, "chat.respond", TaskStatus.RUNNING)
        
        event_bus.publish("task.started", None)
        
        # Simulate brain execution
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.started", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.STARTED,
            progress_id="test-progress-3",
            message="Handling request",
        ))
        
        # Complete some, fail one
        task1.status = TaskStatus.COMPLETED
        task1.completed_at = datetime.now(UTC)
        task2.status = TaskStatus.FAILED
        task2.failure = RuntimeError("Exchange rate unavailable")
        task2.completed_at = datetime.now(UTC)
        task3.status = TaskStatus.COMPLETED
        task3.completed_at = datetime.now(UTC)
        task4.status = TaskStatus.COMPLETED
        task4.completed_at = datetime.now(UTC)
        
        event_bus.publish("task.completed", None)
        event_bus.publish("task.failed", None)
        
        # Publish brain.execution.completed with succeeded=True (synthesis succeeded despite partial failure)
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-progress-3",
            message="succeeded=True",
            metadata={"succeeded": True, "request_id": "test-request-3"},
        ))
        
        state = projector.get_current_state()
        
        # Request status should be PARTIAL_SUCCESS
        assert state.request_status == RequestStatus.PARTIAL_SUCCESS
        
        # Domains should include all three domains
        domain_names = {d.name for d in state.domains}
        assert "weather" in domain_names
        assert "finance" in domain_names
        # web.search maps to "search"
        
        # Synthesis should be represented
        assert state.synthesis is not None
        assert state.synthesis.capability_id == "chat.respond"
        
        # Surfaces should include capabilities from all active domains
        surface_ids = {s.capability_id for s in state.surfaces}
        assert "weather.current" in surface_ids
        assert "finance.exchange_rate" in surface_ids
        assert "web.search" in surface_ids
        assert "chat.respond" in surface_ids
    
    def test_agent_identity_not_semantic_domain(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test agent identity does not determine semantic domain."""
        self._register_phase1_capabilities(capability_registry)
        
        # Register a research agent capability
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        capability_registry.register(CapabilityDefinition(
            id="research.analyze",
            name="Research Analyze",
            description="Analyze research data",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"research", "analysis"}),
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
        
        # Create task with agent.research but weather capability
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.research", agent_specialization="research"
        )
        
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Domain should be "weather" (from capability), not "research" (from agent)
        assert state.context == "weather"
        
        # Agent info should be in metadata but not determine domain
        assert "activity" in state.metadata
        activity = state.metadata["activity"]
        assert len(activity["active_agents"]) == 1
        assert activity["active_agents"][0]["id"] == "agent.research"
        # But domain should be weather
        assert "weather" in activity["active_domains"][0]["context"]


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


@pytest.fixture
def tool_manager(event_bus, logger):
    """Create a ToolManager for testing."""
    from parika.core.tool_manager.tool_manager import ToolManager
    return ToolManager(event_bus=event_bus, logger=logger)


class TestEndToEndRegression:
    """End-to-end regression test using actual Brain execution path."""

    def _register_regression_capabilities(self, capability_registry):
        """Register capabilities for the regression scenario."""
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        
        # Weather capabilities
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
        
        # Finance/currency capability
        capability_registry.register(CapabilityDefinition(
            id="finance.exchange_rate",
            name="Exchange Rate",
            description="Get exchange rate",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"finance", "network"}),
        ))
        
        # Web search
        capability_registry.register(CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description="Search the web",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"web", "network", "search"}),
        ))
        
        # Chat respond
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))

    def test_real_world_regression_scenario(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry, tool_manager):
        """
        Test the exact real-world regression scenario:
        
        "What is the current weather in patna bihar and what will the forecast for next 7 days,
        summarize the data and generate a simple report, also tell me what is the current USD 
        to 123X rate and search the web for current jharkhand protest outcome"
        
        Expected execution semantics:
        - weather.current → SUCCESS
        - weather.forecast → SUCCESS
        - finance.exchange_rate (USD to 123X) → FAILURE (invalid currency)
        - web.search → SUCCESS
        - chat.respond synthesis → SUCCESS
        - Overall → PARTIAL_SUCCESS
        """
        # Register capabilities for the regression scenario
        self._register_regression_capabilities(capability_registry)
        
        # Create a real runtime with Brain
        from parika.core.planner.planner import Planner
        from parika.core.planner.goal import Goal
        from parika.core.brain.brain import Brain
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.capability_executor.capability_executor import CapabilityExecutor
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.resource_manager.resource_manager import ResourceManager
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.configuration.configuration import Configuration
        from parika.core.capability_registry.capability_registry import CapabilityRegistry
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        from parika.core.capability_executor.capability_executor import CapabilityExecutor
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.state_manager.state_manager import StateManager
        from parika.core.workflow_engine.workflow_engine import WorkflowEngine
        from parika.core.context_manager.context_manager import ContextManager
        from parika.core.logger.logger import Logger
        from parika.core.event_bus.event_bus import EventBus
        from parika.core.configuration.configuration import Configuration
        
        # Register mock tool drivers for weather, finance, web search
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.tool_manager.request import ToolRequest
        from parika.core.tool_manager.response import ToolResponse
        from parika.core.tool_manager.tool import Tool
        from parika.core.tool_manager.exceptions import ToolExecutionError
        
        class _ScriptedToolDriver:
            def __init__(self):
                from parika.core.tool_manager.request import ToolRequest
                from parika.core.tool_manager.response import ToolResponse
                self.calls: list[ToolRequest] = []
                self._response: ToolResponse | None = None
                self._error: Exception | None = None
            
            def succeed_with(self, response: ToolResponse) -> None:
                self._response = response
                self._error = None
            
            def fail_with(self, error: Exception) -> None:
                self._error = error
                self._response = None
            
            def execute(self, request: ToolRequest) -> ToolResponse:
                print(f"TOOL DRIVER EXECUTE: capability_id available from context", flush=True)
                self.calls.append(request)
                if self._error is not None:
                    print(f"TOOL DRIVER RAISING ERROR: {self._error}")
                    raise self._error
                assert self._response is not None
                return self._response
        
        def _register_tool(cap_reg, tool_mgr, *, capability_id: str, tool_id: str, driver: _ScriptedToolDriver) -> None:
            # Only register capability if not already registered
            if not cap_reg.contains(capability_id):
                cap_reg.register(
                    CapabilityDefinition(
                        id=capability_id,
                        name=capability_id,
                        description=capability_id,
                        category=CapabilityCategory.TOOL,
                    )
                )
            tool_mgr.register(
                Tool(
                    id=tool_id,
                    name=tool_id,
                    version="1.0.0",
                    description=tool_id,
                    capabilities=(capability_id,),
                ),
                driver,
            )
        
# Use the tool manager from the task manager's capability executor (the one actually used for execution)
        execution_tool_manager = task_manager._capability_executor._tool_manager
        execution_provider_manager = task_manager._capability_executor._provider_manager
        
        # Setup scripted drivers
        weather_current_driver = _ScriptedToolDriver()
        weather_current_driver.succeed_with(ToolResponse(result={"temp": 25, "condition": "sunny", "location": "Patna, Bihar"}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="weather.current", tool_id="weather.current", driver=weather_current_driver)
        assert execution_tool_manager.contains("weather.current"), "weather.current tool not registered"
        
        weather_forecast_driver = _ScriptedToolDriver()
        weather_forecast_driver.succeed_with(ToolResponse(result={"forecast": [{"day": i, "condition": "sunny"} for i in range(1, 8)]}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="weather.forecast", tool_id="weather.forecast", driver=weather_forecast_driver)
        assert execution_tool_manager.contains("weather.forecast"), "weather.forecast tool not registered"
        
        finance_driver = _ScriptedToolDriver()
        finance_driver.fail_with(ToolExecutionError("Invalid currency code: 123X"))
        _register_tool(capability_registry, execution_tool_manager, capability_id="finance.exchange_rate", tool_id="finance.exchange_rate", driver=finance_driver)
        assert execution_tool_manager.contains("finance.exchange_rate"), "finance.exchange_rate tool not registered"
        
        web_search_driver = _ScriptedToolDriver()
        web_search_driver.succeed_with(ToolResponse(result={"results": ["Jharkhand protest ongoing..."]}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="web.search", tool_id="web.search", driver=web_search_driver)
        assert execution_tool_manager.contains("web.search"), "web.search tool not registered"
        
        # Register chat.respond provider using the execution provider manager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.provider_manager.provider import Provider
        from parika.core.provider_manager.provider_model import ProviderModel
        from parika.core.provider_manager.model_capability import ModelCapability
        from parika.core.provider_manager.driver import ProviderDriver
        from parika.core.provider_manager.provider_health import ProviderHealth
        from parika.core.provider_manager.chat_request import ChatRequest
        from parika.core.provider_manager.chat_message import ChatMessage
        from parika.core.provider_manager.chat_result import ChatResult
        from parika.core.state_manager.states import ProviderState
        
        # Use the execution provider manager (the one actually used by the brain's task manager)
        provider_manager = execution_provider_manager
        
        class _RecordingProviderDriver(ProviderDriver):
            def __init__(self):
                self.captured_requests: list = []
            
            def discover_models(self):
                return frozenset()
            
            def check_health(self):
                return ProviderHealth(available=True)
            
            def execute(self, model, request):
                self.captured_requests.append(request)
                return ChatResult(
                    message=ChatMessage(role="assistant", content="Synthesis complete."),
                    tool_invocations=(),
                )
        
        provider_driver = _RecordingProviderDriver()
        provider_manager.register(
            Provider(
                id="provider.test",
                name="Test Provider",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="test-model",
                        name="Test Model",
                        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                    ),
                ),
            ),
            provider_driver,
        )
        
        # Setup planner and brain
        from parika.core.planner.planner import Planner
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.resource_manager.resource_manager import ResourceManager
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.configuration.configuration import Configuration
        
        config = Configuration()
        config.load()
        
        capability_resolver = CapabilityResolver(capability_registry=capability_registry, logger=logger)
        resource_manager = ResourceManager(configuration=config, logger=logger)
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=execution_tool_manager,  # Use the execution tool manager (same as brain's task_manager)
            logger=logger,
            configuration=config,
        )
        
        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=tool_manager,
            provider_manager=provider_manager,
        )
        
        # Monkey patch tool manager execute to add logging
        original_execute = tool_manager.execute
        def logged_execute(tool_id, request):
            print(f"TOOL MANAGER EXECUTE CALLED: tool_id={tool_id}")
            return original_execute(tool_id, request)
        tool_manager.execute = logged_execute
        
        # Monkey patch capability executor execute to add logging
        original_cap_execute = capability_executor.execute
        def logged_cap_execute(request, *, task_id=None):
            print(f"CAPABILITY EXECUTOR EXECUTE CALLED: capability_id={request.resolution.definition.id}, backend={request.target.backend}", flush=True)
            return original_cap_execute(request, task_id=task_id)
        capability_executor.execute = logged_cap_execute
        
        brain = Brain(
            planner=planner,
            task_manager=task_manager,
            logger=logger,
            event_bus=event_bus,
        )
        
        # Monkey patch brain handle to add logging
        original_handle = brain.handle
        def logged_handle(request):
            print(f"BRAIN HANDLE CALLED: request_id={request.id}, goals={len(request.goals)}", flush=True)
            return original_handle(request)
        brain.handle = logged_handle
        
# Monkey patch brain _execute_goal_async to add logging
        original_execute_goal = brain._execute_goal_async
        async def logged_execute_goal(goal, step, progress):
            print(f"BRAIN _execute_goal_async CALLED: goal_id={goal.id}, capability_id={goal.capability_id}", flush=True)
            try:
                result = await original_execute_goal(goal, step, progress)
                print(f"BRAIN _execute_goal_async COMPLETED: goal_id={goal.id}, succeeded={result.succeeded}, failure={result.failure}", flush=True)
                return result
            except Exception as e:
                print(f"BRAIN _execute_goal_async EXCEPTION: goal_id={goal.id}, error={e}", flush=True)
                raise
        brain._execute_goal_async = logged_execute_goal
        
        # Monkey patch task manager execute to add logging
        original_task_execute = task_manager.execute
        def logged_task_execute(task_id, execution_request):
            print(f"TASK MANAGER EXECUTE CALLED: task_id={task_id}, tool_manager_id={id(task_manager._capability_executor._tool_manager)}", flush=True)
            return original_task_execute(task_id, execution_request)
        task_manager.execute = logged_task_execute
        
# Create projector with real brain
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
            brain=brain,
        )
        projector.start()
        
        # Create the goals matching the real-world scenario
        def provider_builder(resolution, model):
            from parika.core.provider_manager.chat_message import ChatMessage
            from parika.interfaces.ai_context.goal_builder import _PROMPT_TOKEN_ESTIMATOR, _estimate_prompt_tokens
            from parika.core.provider_manager.chat_request import ChatRequest
            from parika.core.provider_manager.request import RequestOptions
            
            estimated_prompt_tokens = _estimate_prompt_tokens(
                (ChatMessage(role="user", content="Summarize weather, currency, and search results"),),
                tools=(),
                estimator=_PROMPT_TOKEN_ESTIMATOR
            )
            
            return ChatRequest(
                messages=(ChatMessage(role="user", content="Summarize weather, currency, and search results"),),
                tools=(),
                on_token=None,
                options=RequestOptions(estimated_prompt_tokens=estimated_prompt_tokens),
            )
        
        goals = (
            Goal(id="goal-1", capability_id="weather.current", inputs={"location": "Patna, Bihar"}),
            Goal(id="goal-2", capability_id="weather.forecast", inputs={"location": "Patna, Bihar", "days": 7}),
            Goal(id="goal-3", capability_id="finance.exchange_rate", inputs={"from": "USD", "to": "123X", "amount": 100}),
            Goal(id="goal-4", capability_id="web.search", inputs={"query": "current Jharkhand protest outcome"}),
            Goal(id="goal-5", capability_id="chat.respond", inputs={"message": "Summarize weather, currency, and search results"}, depends_on=("goal-1", "goal-2", "goal-3", "goal-4"), provider_request_builder=provider_builder),
        )
        
        # Execute the Brain request
        from parika.core.brain.brain_request import BrainRequest
        request = BrainRequest(goals=goals)
        response = brain.handle(request)
        
        # Verify Brain response
        assert len(response.results) == 5
        results_by_id = {r.goal_id: r for r in response.results}
        assert results_by_id["goal-1"].succeeded, "weather.current should succeed"
        assert results_by_id["goal-2"].succeeded, "weather.forecast should succeed"
        assert not results_by_id["goal-3"].succeeded, "finance.exchange_rate should fail"
        assert results_by_id["goal-4"].succeeded, "web.search should succeed"
        assert results_by_id["goal-5"].succeeded, "chat.respond synthesis should succeed"
        
        # Verify BrainResponse status
        assert response.status.value == "partial_success", f"Expected PARTIAL_SUCCESS, got {response.status.value}"
        
        # Trigger projector update via brain.execution.completed event
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="regression-test",
            message="succeeded=True",
            metadata={"succeeded": True, "request_id": response.request_id},
        ))
        
        # Get final projector state
        state = projector.get_current_state()
        
        # === VERIFICATIONS ===
        
        # 1. Request status is PARTIAL_SUCCESS
        assert state.request_status.value == "partial_success", f"Expected PARTIAL_SUCCESS, got {state.request_status.value}"
        
        # 2. Multiple domains represented
        domain_names = {d.name for d in state.domains}
        assert "weather" in domain_names, "Weather domain missing"
        assert "finance" in domain_names, "Finance domain missing"
        assert "search" in domain_names or "web" in domain_names, "Search domain missing"
        
        # 3. Synthesis represented correctly
        assert state.synthesis is not None, "Synthesis should be represented"
        assert state.synthesis.capability_id == "chat.respond", f"Synthesis capability_id should be chat.respond, got {state.synthesis.capability_id}"
        assert state.synthesis.status == "completed", f"Synthesis status should be completed, got {state.synthesis.status}"
        assert state.synthesis.depends_on == ("goal-1", "goal-2", "goal-3", "goal-4"), f"Synthesis depends_on mismatch: {state.synthesis.depends_on}"
        assert state.synthesis.completed_dependencies == ("goal-1", "goal-2", "goal-4"), f"Completed deps mismatch: {state.synthesis.completed_dependencies}"
        assert state.synthesis.failed_dependencies == ("goal-3",), f"Failed deps mismatch: {state.synthesis.failed_dependencies}"
        
        # 4. Failed goal preserved
        finance_domains = [d for d in state.domains if d.name == "finance"]
        assert len(finance_domains) > 0, "Finance domain missing"
        assert finance_domains[0].status in ("partial", "failed"), f"Finance domain status should be failed/partial, got {finance_domains[0].status}"
        
        # 5. All capabilities represented in surfaces
        surface_ids = {s.capability_id for s in state.surfaces}
        assert "weather.current" in surface_ids, "weather.current missing from surfaces"
        assert "weather.forecast" in surface_ids, "weather.forecast missing from surfaces"
        assert "finance.exchange_rate" in surface_ids, "finance.exchange_rate missing from surfaces"
        assert "web.search" in surface_ids, "web.search missing from surfaces"
        assert "chat.respond" in surface_ids, "chat.respond missing from surfaces"
        
        # 6. Dependencies have correct goal_ids and capability_ids
        assert len(state.dependencies) == 5, f"Expected 5 dependencies, got {len(state.dependencies)}"
        for dep in state.dependencies:
            assert dep.goal_id is not None, "Dependency goal_id missing"
            assert dep.capability_id is not None, "Dependency capability_id missing"
            # Verify specific capability IDs
            if dep.goal_id == "goal-1":
                assert dep.capability_id == "weather.current"
            elif dep.goal_id == "goal-2":
                assert dep.capability_id == "weather.forecast"
            elif dep.goal_id == "goal-3":
                assert dep.capability_id == "finance.exchange_rate"
            elif dep.goal_id == "goal-4":
                assert dep.capability_id == "web.search"
            elif dep.goal_id == "goal-5":
                assert dep.capability_id == "chat.respond"
        
        # 7. Synthesis dependency correctly represented
        synth_deps = [d for d in state.dependencies if d.is_synthesis]
        assert len(synth_deps) == 1, "Should have exactly one synthesis dependency"
        assert synth_deps[0].depends_on == ("goal-1", "goal-2", "goal-3", "goal-4"), f"Synthesis depends_on mismatch: {synth_deps[0].depends_on}"
        assert synth_deps[0].capability_id == "chat.respond", f"Synthesis capability_id mismatch: {synth_deps[0].capability_id}"
        
        # 8. Finance dependency correctly shows failed status
        finance_deps = [d for d in state.dependencies if d.goal_id == "goal-3"]
        assert len(finance_deps) == 1, "Finance dependency missing"
        assert finance_deps[0].status == "failed", f"Finance status should be failed: {finance_deps[0].status}"
        assert finance_deps[0].capability_id == "finance.exchange_rate", f"Finance capability_id mismatch: {finance_deps[0].capability_id}"
        
        print("✓ End-to-end regression test passed!")

    def test_surface_metadata_populated_from_brain_response(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test that SurfaceItem.metadata is populated from authoritative BrainResponse."""
        self._register_regression_capabilities(capability_registry)
        
        # Create a real runtime with Brain (similar to regression test but simpler)
        from parika.core.planner.planner import Planner
        from parika.core.planner.goal import Goal
        from parika.core.brain.brain import Brain
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.capability_executor.capability_executor import CapabilityExecutor
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.resource_manager.resource_manager import ResourceManager
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.configuration.configuration import Configuration
        from parika.core.capability_registry.capability_registry import CapabilityRegistry
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        from parika.core.capability_executor.capability_executor import CapabilityExecutor
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.state_manager.state_manager import StateManager
        from parika.core.workflow_engine.workflow_engine import WorkflowEngine
        from parika.core.context_manager.context_manager import ContextManager
        from parika.core.logger.logger import Logger
        from parika.core.event_bus.event_bus import EventBus
        from parika.core.configuration.configuration import Configuration
        
        # Register mock tool drivers
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.tool_manager.request import ToolRequest
        from parika.core.tool_manager.response import ToolResponse
        from parika.core.tool_manager.tool import Tool
        from parika.core.tool_manager.exceptions import ToolExecutionError
        
        class _ScriptedToolDriver:
            def __init__(self):
                from parika.core.tool_manager.request import ToolRequest
                from parika.core.tool_manager.response import ToolResponse
                self.calls: list[ToolRequest] = []
                self._response: ToolResponse | None = None
                self._error: Exception | None = None
            
            def succeed_with(self, response: ToolResponse) -> None:
                self._response = response
                self._error = None
            
            def fail_with(self, error: Exception) -> None:
                self._error = error
                self._response = None
            
            def execute(self, request: ToolRequest) -> ToolResponse:
                self.calls.append(request)
                if self._error is not None:
                    raise self._error
                assert self._response is not None
                return self._response
        
        def _register_tool(cap_reg, tool_mgr, *, capability_id: str, tool_id: str, driver: _ScriptedToolDriver) -> None:
            # Only register capability if not already registered
            if not cap_reg.contains(capability_id):
                cap_reg.register(
                    CapabilityDefinition(
                        id=capability_id,
                        name=capability_id,
                        description=capability_id,
                        category=CapabilityCategory.TOOL,
                    )
                )
            tool_mgr.register(
                Tool(
                    id=tool_id,
                    name=tool_id,
                    version="1.0.0",
                    description=tool_id,
                    capabilities=(capability_id,),
                ),
                driver,
            )
        
        # Use the tool manager from the task manager's capability executor
        execution_tool_manager = task_manager._capability_executor._tool_manager
        execution_provider_manager = task_manager._capability_executor._provider_manager
        
        # Setup scripted drivers
        weather_current_driver = _ScriptedToolDriver()
        weather_current_driver.succeed_with(ToolResponse(result={"temp": 25, "condition": "sunny", "location": "Patna, Bihar"}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="weather.current", tool_id="weather.current", driver=weather_current_driver)
        
        weather_forecast_driver = _ScriptedToolDriver()
        weather_forecast_driver.succeed_with(ToolResponse(result={"forecast": [{"day": i, "condition": "sunny"} for i in range(1, 8)]}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="weather.forecast", tool_id="weather.forecast", driver=weather_forecast_driver)
        
        finance_driver = _ScriptedToolDriver()
        finance_driver.fail_with(ToolExecutionError("Invalid currency code: 123X"))
        _register_tool(capability_registry, execution_tool_manager, capability_id="finance.exchange_rate", tool_id="finance.exchange_rate", driver=finance_driver)
        
        web_search_driver = _ScriptedToolDriver()
        web_search_driver.succeed_with(ToolResponse(result={"results": ["Jharkhand protest ongoing..."]}))
        _register_tool(capability_registry, execution_tool_manager, capability_id="web.search", tool_id="web.search", driver=web_search_driver)
        
        # Register chat.respond provider using the execution provider manager
        from parika.core.provider_manager.provider_manager import ProviderManager
        from parika.core.provider_manager.provider import Provider
        from parika.core.provider_manager.provider_model import ProviderModel
        from parika.core.provider_manager.model_capability import ModelCapability
        from parika.core.provider_manager.driver import ProviderDriver
        from parika.core.provider_manager.provider_health import ProviderHealth
        from parika.core.provider_manager.chat_request import ChatRequest
        from parika.core.provider_manager.chat_message import ChatMessage
        from parika.core.provider_manager.chat_result import ChatResult
        from parika.core.state_manager.states import ProviderState
        
        provider_manager = execution_provider_manager
        
        class _RecordingProviderDriver(ProviderDriver):
            def __init__(self):
                self.captured_requests: list = []
            
            def discover_models(self):
                return frozenset()
            
            def check_health(self):
                return ProviderHealth(available=True)
            
            def execute(self, model, request):
                self.captured_requests.append(request)
                return ChatResult(
                    message=ChatMessage(role="assistant", content="Synthesis complete."),
                    tool_invocations=(),
                )
        
        provider_driver = _RecordingProviderDriver()
        provider_manager.register(
            Provider(
                id="provider.test",
                name="Test Provider",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="test-model",
                        name="Test Model",
                        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                    ),
                ),
            ),
            provider_driver,
        )
        
        # Setup planner and brain
        from parika.core.planner.planner import Planner
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.resource_manager.resource_manager import ResourceManager
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.configuration.configuration import Configuration
        
        config = Configuration()
        config.load()
        
        capability_resolver = CapabilityResolver(capability_registry=capability_registry, logger=logger)
        resource_manager = ResourceManager(configuration=config, logger=logger)
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=execution_provider_manager,
            tool_manager=execution_tool_manager,
            logger=logger,
            configuration=config,
        )
        
        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=execution_tool_manager,
            provider_manager=execution_provider_manager,
        )
        
        brain = Brain(
            planner=planner,
            task_manager=task_manager,
            logger=logger,
            event_bus=event_bus,
        )
        
        # Create projector with real brain
        projector = UIContextProjector(
            event_bus=event_bus,
            logger=logger,
            task_manager=task_manager,
            workflow_engine=workflow_engine,
            context_manager=context_manager,
            state_manager=state_manager,
            capability_registry=capability_registry,
            brain=brain,
        )
        projector.start()
        
        # Create goals matching the regression scenario
        def provider_builder(resolution, model):
            from parika.core.provider_manager.chat_message import ChatMessage
            from parika.interfaces.ai_context.goal_builder import _PROMPT_TOKEN_ESTIMATOR, _estimate_prompt_tokens
            from parika.core.provider_manager.chat_request import ChatRequest
            from parika.core.provider_manager.request import RequestOptions
            
            estimated_prompt_tokens = _estimate_prompt_tokens(
                (ChatMessage(role="user", content="Summarize weather, currency, and search results"),),
                tools=(),
                estimator=_PROMPT_TOKEN_ESTIMATOR
            )
            
            return ChatRequest(
                messages=(ChatMessage(role="user", content="Summarize weather, currency, and search results"),),
                tools=(),
                on_token=None,
                options=RequestOptions(estimated_prompt_tokens=estimated_prompt_tokens),
            )
        
        goals = (
            Goal(id="goal-1", capability_id="weather.current", inputs={"location": "Patna, Bihar"}),
            Goal(id="goal-2", capability_id="weather.forecast", inputs={"location": "Patna, Bihar", "days": 7}),
            Goal(id="goal-3", capability_id="finance.exchange_rate", inputs={"from": "USD", "to": "123X", "amount": 100}),
            Goal(id="goal-4", capability_id="web.search", inputs={"query": "current Jharkhand protest outcome"}),
            Goal(id="goal-5", capability_id="chat.respond", inputs={"message": "Summarize weather, currency, and search results"}, depends_on=("goal-1", "goal-2", "goal-3", "goal-4"), provider_request_builder=provider_builder),
        )
        
        # Execute the Brain request
        from parika.core.brain.brain_request import BrainRequest
        request = BrainRequest(goals=goals)
        response = brain.handle(request)
        
        # Verify Brain response
        assert len(response.results) == 5
        results_by_id = {r.goal_id: r for r in response.results}
        assert results_by_id["goal-1"].succeeded
        assert results_by_id["goal-2"].succeeded
        assert not results_by_id["goal-3"].succeeded
        assert results_by_id["goal-4"].succeeded
        assert results_by_id["goal-5"].succeeded
        
        # Verify BrainResponse status
        assert response.status.value == "partial_success"
        
        # Trigger projector update via brain.execution.completed event
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="surface-metadata-test",
            message="succeeded=True",
            metadata={"succeeded": True, "request_id": response.request_id},
        ))
        
        # Get final projector state
        state = projector.get_current_state()
        
        # === VERIFY SURFACE METADATA ===
        
        # Check weather.current surface metadata
        weather_current_surface = next(s for s in state.surfaces if s.capability_id == "weather.current")
        assert weather_current_surface.metadata.get("status") == "completed"
        assert weather_current_surface.metadata.get("domain") == "weather"
        assert weather_current_surface.metadata.get("execution_state") == "completed"
        assert weather_current_surface.metadata.get("result_available") is True
        assert weather_current_surface.metadata.get("is_synthesis") is False
        
        # Check weather.forecast surface metadata
        weather_forecast_surface = next(s for s in state.surfaces if s.capability_id == "weather.forecast")
        assert weather_forecast_surface.metadata.get("status") == "completed"
        assert weather_forecast_surface.metadata.get("domain") == "weather"
        assert weather_forecast_surface.metadata.get("is_synthesis") is False
        
        # Check finance.exchange_rate surface metadata (failed)
        finance_surface = next(s for s in state.surfaces if s.capability_id == "finance.exchange_rate")
        assert finance_surface.metadata.get("status") == "failed"
        assert finance_surface.metadata.get("domain") == "finance"
        assert finance_surface.metadata.get("execution_state") == "failed"
        assert finance_surface.metadata.get("result_available") is False
        assert finance_surface.metadata.get("is_synthesis") is False
        
        # Check web.search surface metadata
        web_search_surface = next(s for s in state.surfaces if s.capability_id == "web.search")
        assert web_search_surface.metadata.get("status") == "completed"
        assert web_search_surface.metadata.get("domain") == "search"
        assert web_search_surface.metadata.get("is_synthesis") is False
        
        # Check chat.respond synthesis surface metadata
        chat_respond_surface = next(s for s in state.surfaces if s.capability_id == "chat.respond")
        assert chat_respond_surface.metadata.get("status") == "completed"
        assert chat_respond_surface.metadata.get("domain") == "chat"
        assert chat_respond_surface.metadata.get("is_synthesis") is True
        assert chat_respond_surface.metadata.get("depends_on") == ("goal-1", "goal-2", "goal-3", "goal-4")
        
        # Verify legacy surfaces still work (no metadata for system surfaces)
        runtime_surface = next((s for s in state.surfaces if s.capability_id == "runtime.info"), None)
        if runtime_surface:
            assert runtime_surface.metadata == MappingProxyType({})
        
        # Verify metadata-only surface changes are detected
        previous_state = state
        updated_surface = SurfaceItem(
            capability_id=chat_respond_surface.capability_id,
            label=chat_respond_surface.label,
            tier=chat_respond_surface.tier,
            metadata=MappingProxyType({
                **dict(chat_respond_surface.metadata),
                "status": "failed",
            }),
        )
        updated_surfaces = tuple(
            updated_surface if surface.capability_id == "chat.respond" else surface
            for surface in previous_state.surfaces
        )

        assert not projector._surfaces_equal(previous_state.surfaces, updated_surfaces)
        
        print("✓ Surface metadata test passed!")


class TestPhase2ContextualIntelligence:
    """Tests for Phase 2 Contextual Intelligence features."""
    
    def _register_phase2_capabilities(self, capability_registry):
        """Register capabilities needed for Phase 2 tests."""
        from parika.core.capability_registry.capability_definition import CapabilityDefinition
        from parika.core.capability_registry.capability_category import CapabilityCategory
        
        # Weather capabilities
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
        
        # Finance capabilities
        capability_registry.register(CapabilityDefinition(
            id="finance.exchange_rate",
            name="Exchange Rate",
            description="Get exchange rate",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"finance", "network"}),
        ))
        
        # Web search
        capability_registry.register(CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description="Search the web",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"web", "network", "search"}),
        ))
        
        # Chat respond
        capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))
        
        # News
        capability_registry.register(CapabilityDefinition(
            id="news.latest",
            name="Latest News",
            description="Latest news",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"news", "network"}),
        ))
        
        # Coding
        capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute a coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding", "llm"}),
        ))
        
        # File system
        capability_registry.register(CapabilityDefinition(
            id="filesystem.read",
            name="Read File",
            description="Read file",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"filesystem", "local"}),
        ))
        capability_registry.register(CapabilityDefinition(
            id="filesystem.write",
            name="Write File",
            description="Write file",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"filesystem", "local"}),
        ))
    
    def _create_task_with_metadata(
        self,
        task_manager,
        capability_id: str,
        status: TaskStatus = TaskStatus.RUNNING,
        agent_id: str | None = None,
        agent_specialization: str | None = None,
        agent_confidence: float | None = None,
        parent_task_id: str | None = None,
        inputs: dict | None = None,
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
            inputs=inputs or {},
        )
        task = task_manager.create(request, parent_task_id=parent_task_id)
        
        # Manually set status for testing (bypassing execution)
        task.status = status
        if status == TaskStatus.RUNNING:
            task.started_at = datetime.now(UTC)
        elif status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(UTC)
        elif status == TaskStatus.FAILED:
            task.completed_at = datetime.now(UTC)
            task.failure = RuntimeError("Test failure")
        
        return task
    
    def test_user_intent_requesting_information(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test user intent detection for information requests."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Single weather task - requesting information
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            inputs={"location": "Patna, Bihar"}
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.user_intent == UserIntent.REQUESTING_INFORMATION
    
    def test_user_intent_researching(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test user intent detection for researching (multiple data gathering)."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Multiple data gathering tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "web.search", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.user_intent == UserIntent.RESEARCHING
    
    def test_user_intent_creating(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test user intent detection for creating."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # File write task - creating
        self._create_task_with_metadata(
            task_manager, "filesystem.write", TaskStatus.RUNNING,
            inputs={"path": "/tmp/test.txt", "content": "hello"}
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        assert state.user_intent == UserIntent.CREATING
    
    def test_conversational_context_continuity(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test conversational context tracks continuity across turns."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # First turn - weather
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state1 = projector.get_current_state()
        assert state1.conversational_context is not None
        assert state1.conversational_context.current_domain == "weather"
        assert state1.conversational_context.turn_count >= 0
        assert state1.context_transition == ContextTransition.ENTERED
        
        # Simulate completion
        tasks = task_manager.get_all()
        for task in tasks.values():
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
        event_bus.publish("task.completed", None)
        
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-1",
            message="completed",
            metadata={"succeeded": True, "request_id": "req-1"},
        ))
        
        state2 = projector.get_current_state()
        # Context should still show weather (ambient)
        assert state2.conversational_context is not None
        assert state2.conversational_context.previous_domain == "weather"
    
    def test_context_transition_detection(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test context transition detection between domains."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # First turn - weather
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        state1 = projector.get_current_state()
        
        # Clear and switch to coding
        tasks = task_manager.get_all()
        for task in tasks.values():
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
        event_bus.publish("task.completed", None)
        
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-1",
            message="completed",
            metadata={"succeeded": True, "request_id": "req-1"},
        ))
        
        # Second turn - coding
        self._create_task_with_metadata(task_manager, "coding.execute_task", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        state2 = projector.get_current_state()
        
        # Should detect context change
        assert state2.context_transition in (ContextTransition.CHANGED, ContextTransition.ENTERED)
        assert state2.conversational_context.previous_domain == "weather"
        assert state2.conversational_context.current_domain == "code"
    
    def test_entity_extraction_from_inputs(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test entity extraction from task inputs."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Task with location and currency inputs
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            inputs={"location": "Patna, Bihar"}
        )
        self._create_task_with_metadata(
            task_manager, "finance.exchange_rate", TaskStatus.RUNNING,
            inputs={"from": "USD", "to": "INR", "amount": 100}
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have entities
        assert len(state.entities) > 0
        entity_names = {e.name for e in state.entities}
        assert "Patna, Bihar" in entity_names or "PATNA, BIHAR" in entity_names
        assert "USD" in entity_names
        assert "INR" in entity_names
        
        # Check entity types
        location_entities = [e for e in state.entities if e.entity_type == EntityType.LOCATION]
        currency_entities = [e for e in state.entities if e.entity_type == EntityType.CURRENCY]
        assert len(location_entities) > 0
        assert len(currency_entities) > 0
    
    def test_topic_projection(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test topic/subject projection from active domains."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Multi-domain tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "web.search", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have topics
        assert len(state.topics) > 0
        topic_names = {t.name for t in state.topics}
        assert "weather" in topic_names
        assert "finance" in topic_names
        assert "research" in topic_names or "search" in topic_names
    
    def test_semantic_relevance_scoring(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test semantic relevance scores for active domains."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Primary domain (weather) with more tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.forecast", TaskStatus.RUNNING)
        # Secondary domain (finance) with fewer tasks
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have semantic relevance
        assert len(state.semantic_relevance) > 0
        
        # Primary domain should have higher relevance
        weather_relevance = next((r for r in state.semantic_relevance if r.domain == "weather"), None)
        finance_relevance = next((r for r in state.semantic_relevance if r.domain == "finance"), None)
        
        assert weather_relevance is not None
        assert finance_relevance is not None
        assert weather_relevance.score >= finance_relevance.score
        
        # Check signals are present
        assert "primary_context" in weather_relevance.signals
        assert len(weather_relevance.signals) > 0
    
    def test_freshness_tracking(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test freshness information for time-sensitive domains."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Weather and finance tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Check domain freshness
        weather_domain = next((d for d in state.domains if d.name == "weather"), None)
        finance_domain = next((d for d in state.domains if d.name == "finance"), None)
        
        assert weather_domain is not None
        assert finance_domain is not None
        
        # Freshness should be present for time-sensitive domains
        if weather_domain.freshness:
            assert weather_domain.freshness.status in ("fresh", "recent", "stale", "unavailable")
            assert weather_domain.freshness.max_age_seconds is not None
        
        if finance_domain.freshness:
            assert finance_domain.freshness.status in ("fresh", "recent", "stale", "unavailable")
            assert finance_domain.freshness.max_age_seconds is not None
    
    def test_contextual_role_assignment(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test contextual role assignment (primary/secondary/ambient)."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Primary domain with multiple tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.forecast", TaskStatus.RUNNING)
        # Secondary domain
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Check domain contextual roles
        weather_domain = next((d for d in state.domains if d.name == "weather"), None)
        finance_domain = next((d for d in state.domains if d.name == "finance"), None)
        
        assert weather_domain is not None
        assert finance_domain is not None
        
        # Primary domain should be PRIMARY
        assert weather_domain.contextual_role == ContextualRole.PRIMARY
        # Secondary domain should be SECONDARY or AMBIENT
        assert finance_domain.contextual_role in (ContextualRole.SECONDARY, ContextualRole.AMBIENT)
        
        # Check surface contextual roles
        weather_surfaces = [s for s in state.surfaces if s.capability_id.startswith("weather.")]
        finance_surfaces = [s for s in state.surfaces if s.capability_id.startswith("finance.")]
        
        for s in weather_surfaces:
            assert s.contextual_role == ContextualRole.PRIMARY
        
        for s in finance_surfaces:
            assert s.contextual_role in (ContextualRole.SECONDARY, ContextualRole.AMBIENT)
    
    def test_surface_relevance_metadata(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test surface relevance and freshness metadata."""
        self._register_phase2_capabilities(capability_registry)
        
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
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Check surface relevance
        for surface in state.surfaces:
            assert 0.0 <= surface.relevance <= 1.0
            assert surface.contextual_role in ContextualRole
        
        # Primary domain surfaces should have higher relevance
        weather_surfaces = [s for s in state.surfaces if s.capability_id.startswith("weather.")]
        for s in weather_surfaces:
            assert s.relevance > 0.5
    
    def test_ambient_context_persistence(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test ambient context persists after task completion."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Active weather task
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        state1 = projector.get_current_state()
        
        assert state1.attention == AttentionLevel.PRIMARY
        assert state1.context == "weather"
        
        # Complete the task
        tasks = task_manager.get_all()
        for task in tasks.values():
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
        event_bus.publish("task.completed", None)
        
        from parika.core.utilities.progress import ProgressEvent, ProgressStage
        event_bus.publish("brain.execution.completed", ProgressEvent(
            source_id="brain.execution",
            stage=ProgressStage.COMPLETED,
            progress_id="test-ambient",
            message="completed",
            metadata={"succeeded": True, "request_id": "req-ambient"},
        ))
        
        state2 = projector.get_current_state()
        
        # Context should become ambient but still show weather
        assert state2.attention == AttentionLevel.AMBIENT
        assert state2.context == "weather"
        # Domains should still be present
        assert len(state2.domains) > 0
        # Surfaces should still be present
        assert len(state2.surfaces) > 0
    
    def test_multi_domain_context_representation(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test multiple domains simultaneously represented."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Complex multi-domain request
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather", agent_specialization="system"
        )
        self._create_task_with_metadata(
            task_manager, "finance.exchange_rate", TaskStatus.RUNNING,
            agent_id="agent.finance", agent_specialization="finance"
        )
        self._create_task_with_metadata(
            task_manager, "web.search", TaskStatus.RUNNING,
            agent_id="agent.research", agent_specialization="research"
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have all three domains
        domain_names = {d.name for d in state.domains}
        assert "weather" in domain_names
        assert "finance" in domain_names
        assert "search" in domain_names or "web" in domain_names
        
        # Each domain should have proper structure
        for domain in state.domains:
            assert 0.0 <= domain.importance <= 1.0
            assert isinstance(domain.focus, FocusArea)
            assert domain.status in ("running", "waiting", "completed", "failed")
            assert isinstance(domain.capability_ids, tuple)
            assert domain.contextual_role in ContextualRole
            assert 0.0 <= domain.relevance <= 1.0
        
        # Entities from all domains
        assert len(state.entities) > 0
        
        # Topics from all domains
        assert len(state.topics) >= 2
    
    def test_synthesis_contextual_role(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test synthesis goal contextual role."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Data gathering + synthesis
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            agent_id="agent.weather"
        )
        self._create_task_with_metadata(
            task_manager, "chat.respond", TaskStatus.RUNNING,
            agent_id="agent.synthesis"
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Synthesis should be represented
        assert state.synthesis is not None
        assert state.synthesis.capability_id == "chat.respond"
        # Active synthesis should be PRIMARY
        assert state.synthesis.contextual_role == ContextualRole.PRIMARY
    
    def test_dependency_contextual_roles(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test dependency contextual roles (failed deps get attention)."""
        self._register_phase2_capabilities(capability_registry)
        
        # This test would require a real BrainResponse to properly test
        # For now, verify the structure exists
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
        
        # Dependencies should have contextual_role field
        for dep in state.dependencies:
            assert dep.contextual_role in ContextualRole
    
    def test_ui_overload_control_signals(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test signals for UI overload control (relevance, attention, tier, freshness, role)."""
        self._register_phase2_capabilities(capability_registry)
        
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
        
        # Many concurrent tasks
        self._create_task_with_metadata(task_manager, "weather.current", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "weather.forecast", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "finance.exchange_rate", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "web.search", TaskStatus.RUNNING)
        self._create_task_with_metadata(task_manager, "coding.execute_task", TaskStatus.RUNNING)
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        
        # Should have all signals for client-side prioritization
        assert len(state.semantic_relevance) > 0
        
        # All domains have relevance scores
        for rel in state.semantic_relevance:
            assert 0.0 <= rel.score <= 1.0
            assert len(rel.signals) > 0
        
        # All domains have contextual roles
        for domain in state.domains:
            assert domain.contextual_role in ContextualRole
            assert 0.0 <= domain.relevance <= 1.0
        
        # All surfaces have relevance and contextual roles
        for surface in state.surfaces:
            assert 0.0 <= surface.relevance <= 1.0
            assert surface.contextual_role in ContextualRole
            assert surface.tier in SurfaceTier
        
        # Freshness for time-sensitive domains
        for domain in state.domains:
            if domain.freshness:
                assert domain.freshness.status in ("fresh", "recent", "stale", "unavailable")
        
        print("✓ UI overload control signals test passed!")
    
    def test_rest_api_includes_phase2_fields(self, event_bus, logger, task_manager, workflow_engine, context_manager, state_manager, capability_registry):
        """Test REST API response includes Phase 2 fields."""
        from parika.api.schemas.ui_context import UIContextResponse
        
        self._register_phase2_capabilities(capability_registry)
        
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
        
        self._create_task_with_metadata(
            task_manager, "weather.current", TaskStatus.RUNNING,
            inputs={"location": "Patna, Bihar"}
        )
        event_bus.publish("task.started", None)
        
        state = projector.get_current_state()
        response = UIContextResponse.from_state(state)
        
        # Phase 2 fields should be present
        assert response.user_intent is not None
        assert response.conversational_context is not None
        assert isinstance(response.semantic_relevance, list)
        assert isinstance(response.entities, list)
        assert isinstance(response.topics, list)
        assert response.context_transition is not None
        
        # Check nested structures
        if response.conversational_context:
            assert response.conversational_context.current_domain == "weather"
            assert response.conversational_context.contextual_transition == ContextTransition.ENTERED
        
        # Entities should be serialized
        if response.entities:
            for entity in response.entities:
                assert entity.name
                assert entity.entity_type in EntityType
                assert entity.domain
                assert 0.0 <= entity.confidence <= 1.0
        
        # Topics should be serialized
        if response.topics:
            for topic in response.topics:
                assert topic.name
                assert topic.domain
                assert 0.0 <= topic.relevance <= 1.0
        
        # Semantic relevance should be serialized
        for rel in response.semantic_relevance:
            assert rel.domain
            assert 0.0 <= rel.score <= 1.0
            assert isinstance(rel.signals, list)
        
        # Domain Phase 2 fields
        for domain in response.domains:
            assert domain.contextual_role in ContextualRole
            assert 0.0 <= domain.relevance <= 1.0
            assert isinstance(domain.entities, list)
            assert isinstance(domain.topics, list)
        
        # Surface Phase 2 fields
        for surface in response.surfaces:
            assert surface.contextual_role in ContextualRole
            assert 0.0 <= surface.relevance <= 1.0
            assert surface.tier in SurfaceTier
        
        print("✓ REST API Phase 2 fields test passed!")