"""
Tests for Agent Registry
"""

from __future__ import annotations

import pytest

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.agent_orchestrator.exceptions import AgentAlreadyRegisteredError, AgentNotFoundError
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration


class TestAgentRegistry:
    def setup_method(self) -> None:
        config = Configuration()
        config.load()
        self.logger = Logger(config)
        self.event_bus = EventBus(self.logger)
        self.registry = AgentRegistry(self.event_bus, self.logger)

    def test_register_agent(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        self.registry.register(profile)
        assert self.registry.contains("test.agent")

    def test_register_duplicate_raises(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        self.registry.register(profile)
        with pytest.raises(AgentAlreadyRegisteredError):
            self.registry.register(profile)

    def test_unregister_agent(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        self.registry.register(profile)
        self.registry.unregister("test.agent")
        assert not self.registry.contains("test.agent")

    def test_unregister_missing_raises(self) -> None:
        with pytest.raises(AgentNotFoundError):
            self.registry.unregister("nonexistent")

    def test_get_agent(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        self.registry.register(profile)
        retrieved = self.registry.get("test.agent")
        assert retrieved.id == "test.agent"
        assert retrieved.name == "Test Agent"

    def test_get_missing_raises(self) -> None:
        with pytest.raises(AgentNotFoundError):
            self.registry.get("nonexistent")

    def test_get_all(self) -> None:
        profile1 = AgentProfile(
            id="agent.1",
            name="Agent 1",
            specialization=AgentSpecialization.GENERAL,
        )
        profile2 = AgentProfile(
            id="agent.2",
            name="Agent 2",
            specialization=AgentSpecialization.CODING,
        )
        self.registry.register(profile1)
        self.registry.register(profile2)
        all_agents = self.registry.get_all()
        assert len(all_agents) == 2

    def test_get_by_specialization(self) -> None:
        profile1 = AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        profile2 = AgentProfile(
            id="agent.coding",
            name="Coding Agent",
            specialization=AgentSpecialization.CODING,
        )
        self.registry.register(profile1)
        self.registry.register(profile2)
        coding_agents = self.registry.get_by_specialization(AgentSpecialization.CODING)
        assert len(coding_agents) == 1
        assert coding_agents[0].id == "agent.coding"

    def test_find_by_capability(self) -> None:
        profile1 = AgentProfile(
            id="agent.coding",
            name="Coding Agent",
            specialization=AgentSpecialization.CODING,
            allowed_capabilities=frozenset({"coding.execute_task"}),
        )
        profile2 = AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
            allowed_capabilities=frozenset({"chat.respond"}),
        )
        self.registry.register(profile1)
        self.registry.register(profile2)
        found = self.registry.find(capability_id="coding.execute_task")
        assert len(found) == 1
        assert found[0].id == "agent.coding"