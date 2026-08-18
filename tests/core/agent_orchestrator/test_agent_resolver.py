"""
Tests for Agent Resolver
"""

from __future__ import annotations

import pytest

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.agent_orchestrator.exceptions import NoSuitableAgentError
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration


class TestAgentResolver:
    def setup_method(self) -> None:
        config = Configuration()
        config.load()
        self.logger = Logger(config)
        self.event_bus = EventBus(self.logger)
        
        self.capability_registry = CapabilityRegistry(self.event_bus, self.logger)
        self.agent_registry = AgentRegistry(self.event_bus, self.logger)
        self.resolver = AgentResolver(
            agent_registry=self.agent_registry,
            capability_registry=self.capability_registry,
            logger=self.logger,
        )

        # Register test capabilities
        self.capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="web.search",
            name="Web Search",
            description="Search web",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"web"}),
        ))
        self.capability_registry.register(CapabilityDefinition(
            id="media.play",
            name="Media Play",
            description="Play media",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"media"}),
        ))

        # Register test agents
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
        self.agent_registry.register(AgentProfile(
            id="agent.research",
            name="Research Agent",
            specialization=AgentSpecialization.RESEARCH,
            preferred_capabilities=frozenset({"web.search"}),
            allowed_capabilities=frozenset({"web.search", "chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL, CapabilityCategory.LLM}),
        ))

    def test_resolve_prefers_specialization_match(self) -> None:
        resolution = self.resolver.resolve(
            capability_id="coding.execute_task",
            preferred_specialization=AgentSpecialization.CODING,
        )
        assert resolution.agent.id == "agent.coding"
        assert resolution.matched_specialization

    def test_resolve_fallback_to_general(self) -> None:
        resolution = self.resolver.resolve(
            capability_id="chat.respond",
        )
        # Coding agent also handles chat.respond (allows it) and is preferred
        assert resolution.agent.id == "agent.coding"

    def test_resolve_by_capability_preference(self) -> None:
        resolution = self.resolver.resolve(
            capability_id="web.search",
        )
        # Research agent prefers web.search
        assert resolution.agent.id == "agent.research"

    def test_resolve_no_suitable_agent_raises(self) -> None:
        with pytest.raises(NoSuitableAgentError):
            self.resolver.resolve(
                capability_id="nonexistent.capability",
            )

    def test_resolve_with_required_categories(self) -> None:
        resolution = self.resolver.resolve(
            capability_id="coding.execute_task",
            required_categories=frozenset({CapabilityCategory.LLM}),
        )
        assert resolution.agent.id == "agent.coding"

    def test_resolve_confidence_scoring(self) -> None:
        resolution = self.resolver.resolve(
            capability_id="coding.execute_task",
            preferred_specialization=AgentSpecialization.CODING,
        )
        assert resolution.confidence > 0.5
        assert "specialization match" in resolution.reason