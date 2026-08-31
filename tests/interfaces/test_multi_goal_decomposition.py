"""
Integration test for multi-goal decomposition.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

import pytest
from unittest.mock import Mock

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.configuration.configuration import Configuration
from parika.interfaces.ai_context.goal_decomposer import create_goal_decomposer
from parika.interfaces.chat_capability import decompose_and_build_goals
from parika.interfaces.runtime import ParikaRuntime, build_default_runtime


class TestMultiGoalDecomposition:
    """Test multi-goal decomposition in isolation."""

    def setup_method(self) -> None:
        """Set up test runtime."""
        self.config = Configuration()
        self.config.load()
        self.logger = Logger(self.config)
        self.event_bus = EventBus(self.logger)
        
        self.capability_registry = CapabilityRegistry(self.event_bus, self.logger)
        self.capability_resolver = CapabilityResolver(
            capability_registry=self.capability_registry,
            logger=self.logger,
        )
        
        self.agent_registry = AgentRegistry(self.event_bus, self.logger)
        self.agent_resolver = AgentResolver(
            agent_registry=self.agent_registry,
            capability_registry=self.capability_registry,
            logger=self.logger,
        )
        
        self.resource_manager = ResourceManager(configuration=self.config, logger=self.logger)
        self.policy_engine = PolicyEngine(event_bus=self.event_bus, logger=self.logger)
        self.provider_manager = ProviderManager(event_bus=self.event_bus, logger=self.logger)
        self.tool_manager = ToolManager(event_bus=self.event_bus, logger=self.logger)
        
        self.planner = Planner(
            capability_resolver=self.capability_resolver,
            resource_manager=self.resource_manager,
            policy_engine=self.policy_engine,
            provider_manager=self.provider_manager,
            tool_manager=self.tool_manager,
            logger=self.logger,
            configuration=self.config,
        )
        
        self.capability_executor = CapabilityExecutor(
            event_bus=self.event_bus,
            logger=self.logger,
            tool_manager=self.tool_manager,
            provider_manager=self.provider_manager,
        )
        
        self.task_manager = TaskManager(
            event_bus=self.event_bus,
            logger=self.logger,
            capability_executor=self.capability_executor,
        )
        
        self.agent_orchestrator = AgentOrchestrator(
            planner=self.planner,
            task_manager=self.task_manager,
            agent_registry=self.agent_registry,
            agent_resolver=self.agent_resolver,
            capability_registry=self.capability_registry,
            logger=self.logger,
        )
        
        self.brain = Brain(
            planner=self.planner,
            task_manager=self.task_manager,
            logger=self.logger,
            event_bus=self.event_bus,
            agent_orchestrator=self.agent_orchestrator,
        )
        
        self._register_test_capabilities()
        self._register_test_agents()

    def _register_test_capabilities(self) -> None:
        """Register test capabilities."""
        caps = [
            ("chat.respond", "Chat Respond", CapabilityCategory.LLM),
            ("weather.current", "Weather Current", CapabilityCategory.TOOL),
            ("weather.forecast", "Weather Forecast", CapabilityCategory.TOOL),
            ("currency.convert", "Currency Convert", CapabilityCategory.TOOL),
            ("web.search", "Web Search", CapabilityCategory.TOOL),
        ]
        for cap_id, name, category in caps:
            self.capability_registry.register(CapabilityDefinition(
                id=cap_id,
                name=name,
                description=f"Test {name}",
                category=category,
                tags=frozenset({"test"}),
            ))

    def _register_test_agents(self) -> None:
        """Register test agents."""
        # General agent for chat
        self.agent_registry.register(AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
            preferred_capabilities=frozenset({"chat.respond"}),
            allowed_capabilities=frozenset({"chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.LLM}),
            allowed_categories=frozenset({CapabilityCategory.LLM}),
        ))
        
        # Weather agent
        self.agent_registry.register(AgentProfile(
            id="agent.weather",
            name="Weather Agent",
            specialization=AgentSpecialization.SYSTEM,
            preferred_capabilities=frozenset({"weather.current", "weather.forecast"}),
            allowed_capabilities=frozenset({"weather.current", "weather.forecast"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL}),
        ))
        
        # Currency agent
        self.agent_registry.register(AgentProfile(
            id="agent.currency",
            name="Currency Agent",
            specialization=AgentSpecialization.SYSTEM,
            preferred_capabilities=frozenset({"currency.convert"}),
            allowed_capabilities=frozenset({"currency.convert"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL}),
        ))
        
        # Research agent
        self.agent_registry.register(AgentProfile(
            id="agent.research",
            name="Research Agent",
            specialization=AgentSpecialization.RESEARCH,
            preferred_capabilities=frozenset({"web.search"}),
            allowed_capabilities=frozenset({"web.search"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL}),
        ))

    def test_decompose_and_execute_weather_request(self) -> None:
        """Test decomposing and executing a weather request."""
        # This test uses a mock brain response since we don't have real providers
        # In real integration tests, the full runtime with providers is used
        
        decomposer = create_goal_decomposer(
            capability_registry=self.capability_registry,
            provider_manager=self.provider_manager,
            configuration=self.config,
        )
        
        # The decomposer will try to use the LLM for decomposition
        # Since we don't have a real provider, it will fallback
        # This tests the fallback path
        result = decomposer.decompose("What is the weather in Patna?")
        
        # Fallback produces single chat.respond goal
        assert len(result.goals) >= 1
        assert any(g.capability_id == "chat.respond" for g in result.goals)

    def test_decompose_complex_multi_domain_request(self) -> None:
        """Test that the decomposer can parse complex multi-domain responses."""
        # This test verifies the parsing logic by testing the _parse_decomposition
        # method directly with a known JSON response
        from parika.interfaces.ai_context.goal_decomposer import GoalDecomposer
        import json
        
        # Create a minimal decomposer
        decomposer = GoalDecomposer(
            capability_registry=self.capability_registry,
            provider_manager=self.provider_manager,
            configuration=self.config,
        )
        
        # Test the parsing directly
        raw_response = """```json
{
    "goals": [
        {"id": "g1", "capability_id": "weather.current", "inputs": {"location": "Patna"}, "depends_on": []},
        {"id": "g2", "capability_id": "weather.forecast", "inputs": {"location": "Patna"}, "depends_on": []},
        {"id": "g3", "capability_id": "currency.convert", "inputs": {"from": "USD", "to": "INR", "amount": 1}, "depends_on": []},
        {"id": "g4", "capability_id": "web.search", "inputs": {"query": "Jharkhand protest"}, "depends_on": []},
        {"id": "g5", "capability_id": "chat.respond", "inputs": {"message": "Summarize everything"}, "depends_on": ["g1", "g2", "g3", "g4"]}
    ]
}
```"""
        
        available = frozenset([
            "chat.respond", "weather.current", "weather.forecast", 
            "currency.convert", "web.search"
        ])
        
        goals = decomposer._parse_decomposition(raw_response, available, "test message")
        
        assert len(goals) == 5
        cap_ids = [g.capability_id for g in goals]
        assert "weather.current" in cap_ids
        assert "weather.forecast" in cap_ids
        assert "currency.convert" in cap_ids
        assert "web.search" in cap_ids
        assert "chat.respond" in cap_ids
        
        # Verify dependencies
        chat_goal = next(g for g in goals if g.capability_id == "chat.respond")
        assert "g1" in chat_goal.depends_on
        assert "g2" in chat_goal.depends_on
        assert "g3" in chat_goal.depends_on
        assert "g4" in chat_goal.depends_on

    def test_agent_assignment_for_decomposed_goals(self) -> None:
        """Test that decomposed goals get assigned to correct agents."""
        from parika.core.planner.goal import Goal
        
        # Create goals as if they came from decomposition
        goals = (
            Goal(id="g1", capability_id="weather.current", inputs={"location": "Patna"}),
            Goal(id="g2", capability_id="currency.convert", inputs={"from": "USD", "to": "INR", "amount": 1}),
            Goal(id="g3", capability_id="web.search", inputs={"query": "test"}),
            Goal(id="g4", capability_id="chat.respond", inputs={"message": "Summary"}),
        )
        
        request = BrainRequest(goals=goals)
        
        # Assign agents through orchestrator
        agent_goals = self.agent_orchestrator.assign_agents_to_goals(request.goals)
        request = BrainRequest(goals=tuple(a.goal for a in agent_goals))
        
        # Verify agent metadata
        goal_map = {goal.id: goal for goal in request.goals}
        assert goal_map["g1"].metadata["agent_id"] == "agent.weather"
        assert goal_map["g2"].metadata["agent_id"] == "agent.currency"
        assert goal_map["g3"].metadata["agent_id"] == "agent.research"
        assert goal_map["g4"].metadata["agent_id"] == "agent.general"
        
        # Verify specializations
        assert goal_map["g1"].metadata["agent_specialization"] == "system"
        assert goal_map["g2"].metadata["agent_specialization"] == "system"
        assert goal_map["g3"].metadata["agent_specialization"] == "research"
        assert goal_map["g4"].metadata["agent_specialization"] == "general"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
