"""
Integration test for multi-goal multi-agent execution.

Tests that Brain with AgentOrchestrator can handle multiple goals
assigned to different agents in a single request.
"""

from __future__ import annotations

import pytest

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


class TestMultiAgentIntegration:
    """Integration test for multi-goal multi-agent execution."""

    def setup_method(self) -> None:
        config = Configuration()
        config.load()
        self.logger = Logger(config)
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

        self.resource_manager = ResourceManager(configuration=config, logger=self.logger)
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
            configuration=config,
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

    def _register_test_capabilities(self) -> None:
        """Register test capabilities."""
        # Weather capabilities (TOOL)
        self.capability_registry.register(CapabilityDefinition(
            id="weather.current",
            name="Weather Current",
            description="Get current weather",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"weather", "network"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="weather.forecast",
            name="Weather Forecast",
            description="Get weather forecast",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"weather", "network"}),
        ))

        # Currency capabilities (TOOL)
        self.capability_registry.register(CapabilityDefinition(
            id="currency.exchange_rate",
            name="Currency Exchange Rate",
            description="Get exchange rate",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"currency", "network"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="currency.convert",
            name="Currency Convert",
            description="Convert currency",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"currency", "network"}),
        ))

        # Chat capability (LLM)
        self.capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
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
            specialization=AgentSpecialization.SYSTEM,  # Using SYSTEM for weather
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
            preferred_capabilities=frozenset({"currency.exchange_rate", "currency.convert"}),
            allowed_capabilities=frozenset({"currency.exchange_rate", "currency.convert"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL}),
        ))

    def test_multi_goal_different_agents(self) -> None:
        """Test that multiple goals in one request can be assigned to different agents."""
        self._register_test_capabilities()
        self._register_test_agents()

        # Create a BrainRequest with multiple goals targeting different capabilities
        from parika.core.planner.goal import Goal

        request = BrainRequest(
            goals=(
                Goal(id="g1", capability_id="weather.current"),
                Goal(id="g2", capability_id="currency.exchange_rate"),
                Goal(id="g3", capability_id="chat.respond"),
            )
        )

        # Assign agents through orchestrator (what Brain.handle() does)
        if self.agent_orchestrator is not None:
            agent_goals = self.agent_orchestrator.assign_agents_to_goals(request.goals)
            # Extract goals with agent metadata
            request = BrainRequest(goals=tuple(a.goal for a in agent_goals))

        # Verify agent metadata was attached
        for goal in request.goals:
            assert "agent_id" in goal.metadata
            assert "agent_specialization" in goal.metadata

        # Verify different agents were assigned
        agent_ids = [goal.metadata["agent_id"] for goal in request.goals]
        assert len(set(agent_ids)) >= 2  # At least 2 different agents

        # Verify specific assignments
        goal_map = {goal.id: goal for goal in request.goals}
        assert goal_map["g1"].metadata["agent_id"] == "agent.weather"
        assert goal_map["g2"].metadata["agent_id"] == "agent.currency"
        assert goal_map["g3"].metadata["agent_id"] == "agent.general"

    def test_goal_dependency_ordering_preserved(self) -> None:
        """Test that agent assignment doesn't break goal dependency ordering."""
        self._register_test_capabilities()
        self._register_test_agents()

        from parika.core.planner.goal import Goal

        # Goal B depends on Goal A
        request = BrainRequest(
            goals=(
                Goal(id="g1", capability_id="weather.current"),
                Goal(id="g2", capability_id="currency.exchange_rate", depends_on=("g1",)),
            )
        )

        if self.agent_orchestrator is not None:
            agent_goals = self.agent_orchestrator.assign_agents_to_goals(request.goals)
            request = BrainRequest(goals=tuple(a.goal for a in agent_goals))

        # Dependencies should be preserved
        goal_map = {goal.id: goal for goal in request.goals}
        assert goal_map["g2"].depends_on == ("g1",)

        # Both goals should have agent metadata
        assert "agent_id" in goal_map["g1"].metadata
        assert "agent_id" in goal_map["g2"].metadata

    def test_single_goal_still_works(self) -> None:
        """Test that single-goal requests still work normally."""
        self._register_test_capabilities()
        self._register_test_agents()

        from parika.core.planner.goal import Goal

        request = BrainRequest(
            goals=(Goal(id="g1", capability_id="chat.respond"),)
        )

        if self.agent_orchestrator is not None:
            agent_goals = self.agent_orchestrator.assign_agents_to_goals(request.goals)
            request = BrainRequest(goals=tuple(a.goal for a in agent_goals))

        assert len(request.goals) == 1
        assert request.goals[0].metadata["agent_id"] == "agent.general"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])