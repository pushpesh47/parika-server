"""
Tests for Agent Orchestrator
"""

from __future__ import annotations

import pytest

from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
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


class TestAgentOrchestrator:
    def setup_method(self) -> None:
        config = Configuration()
        config.load()
        self.logger = Logger(config)
        self.event_bus = EventBus(self.logger)

        self.capability_registry = CapabilityRegistry(self.event_bus, self.logger)
        self.capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding"}),
        ))

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

        self.brain = Brain(
            planner=self.planner,
            task_manager=self.task_manager,
            logger=self.logger,
            event_bus=self.event_bus,
        )

        self.agent_orchestrator = AgentOrchestrator(
            planner=self.planner,
            task_manager=self.task_manager,
            agent_registry=self.agent_registry,
            agent_resolver=self.agent_resolver,
            capability_registry=self.capability_registry,
            logger=self.logger,
        )

        # Register agents
        self.agent_registry.register(AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
            allowed_capabilities=frozenset({"chat.respond"}),
            allowed_categories=frozenset({CapabilityCategory.LLM}),
        ))
        self.agent_registry.register(AgentProfile(
            id="agent.coding",
            name="Coding Agent",
            specialization=AgentSpecialization.CODING,
            preferred_capabilities=frozenset({"coding.execute_task"}),
            allowed_capabilities=frozenset({"coding.execute_task", "chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.LLM}),
            allowed_categories=frozenset({CapabilityCategory.LLM}),
        ))

    def test_assign_agents_to_goals(self) -> None:
        from parika.core.planner.goal import Goal
        from uuid import uuid4

        goals = (
            Goal(
                id="g1",
                capability_id="chat.respond",
                inputs={"message": "Hello"},
            ),
            Goal(
                id="g2",
                capability_id="coding.execute_task",
                inputs={"instruction": "Write code"},
            ),
        )

        assignments = self.agent_orchestrator.assign_agents_to_goals(goals)
        
        assert len(assignments) == 2
        # Coding agent is preferred for chat.respond too (allows it)
        # So both might go to coding agent - check that assignments work
        assert assignments[0].goal.capability_id == "chat.respond"
        assert assignments[1].goal.capability_id == "coding.execute_task"
        # Both should have agent metadata attached
        assert "agent_id" in assignments[0].goal.metadata
        assert "agent_id" in assignments[1].goal.metadata

    def test_get_agent_for_capability(self) -> None:
        resolution = self.agent_orchestrator.get_agent_for_capability("coding.execute_task")
        assert resolution.agent.id == "agent.coding"
        
        resolution = self.agent_orchestrator.get_agent_for_capability("chat.respond")
        # Coding agent also handles chat.respond (allows it)
        assert resolution.agent.id == "agent.coding"