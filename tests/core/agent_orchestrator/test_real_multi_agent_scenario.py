"""
End-to-end integration test for real multi-agent work.

Tests a realistic scenario where a single request involves multiple agents
with different specializations working concurrently and with dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.tool_manager.response import ToolResponse
from parika.core.configuration.configuration import Configuration
from parika.core.planner.goal import Goal
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_limits import ModelLimits


class _FakeProviderDriver(ProviderDriver):
    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: object) -> object:
        return {"result": "mock response"}


@dataclass(frozen=True, slots=True)
class _FakeChatRequest(ProviderRequest):
    prompt: str = ""


class _ScriptedToolDriver:
    def __init__(self) -> None:
        self._result: ToolResponse | None = None
        self._error: BaseException | None = None

    def succeed_with(self, response: ToolResponse) -> None:
        self._result = response
        self._error = None

    def fail_with(self, error: BaseException) -> None:
        self._result = None
        self._error = error

    def execute(self, request) -> ToolResponse:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _register_provider(
    provider_manager: ProviderManager,
    *,
    provider_id: str,
    models: tuple[ProviderModel, ...],
) -> None:
    provider_manager.register(
        Provider(
            id=provider_id,
            name=provider_id,
            health=ProviderHealth(available=True),
            models=models,
        ),
        _FakeProviderDriver(),
    )


def _register_tool(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    *,
    capability_id: str,
    tool_id: str,
    driver: _ScriptedToolDriver,
) -> None:
    capability_registry.register(
        CapabilityDefinition(
            id=capability_id,
            name=capability_id,
            description=capability_id,
            category=CapabilityCategory.TOOL,
        )
    )
    tool_manager.register(
        Tool(
            id=tool_id,
            name=tool_id,
            version="1.0.0",
            description=tool_id,
            capabilities=(capability_id,),
        ),
        driver,
    )


@dataclass(frozen=True, slots=True)
class _FakeChatRequest(ProviderRequest):
    prompt: str = ""


class TestRealMultiAgentScenario:
    """
    Integration test for a realistic multi-agent scenario:

    User Request: "Research the latest Python async best practices and
    create a code example showing proper error handling."

    This should involve:
    1. Research Agent: web.search for "Python async best practices 2024"
    2. Coding Agent: coding.execute_task to create the example
    3. General Agent: chat.respond to synthesize the final response

    The research and coding can run concurrently (no dependency).
    The synthesis depends on both.
    """

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

        # Register provider models for LLM capabilities
        _register_provider(
            self.provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="test-model",
                    name="Test Model",
                    capabilities=frozenset({
                        ModelCapability.TEXT_GENERATION,
                        ModelCapability.CODING,
                    }),
                    limits=ModelLimits(context_window=8192),
                ),
            ),
        )

        # Register tools
        self.web_search_driver = _ScriptedToolDriver()
        self.web_search_driver.succeed_with(ToolResponse(result={"results": ["result1", "result2"]}))

        _register_tool(
            self.capability_registry,
            self.tool_manager,
            capability_id="web.search",
            tool_id="web.search",
            driver=self.web_search_driver,
        )

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
            event_bus=self.event_bus,
        )

        self.brain = Brain(
            planner=self.planner,
            task_manager=self.task_manager,
            logger=self.logger,
            event_bus=self.event_bus,
            agent_orchestrator=self.agent_orchestrator,
        )

    def _register_test_capabilities(self) -> None:
        """Register test capabilities for the scenario."""
        # Coding capabilities (web.search is already registered in setup_method)
        self.capability_registry.register(CapabilityDefinition(
            id="coding.execute_task",
            name="Coding Execute Task",
            description="Execute a coding task",
            category=CapabilityCategory.LLM,
            tags=frozenset({"coding", "llm"}),
        ))

        # Chat capability for synthesis
        self.capability_registry.register(CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Chat response",
            category=CapabilityCategory.LLM,
            tags=frozenset({"chat", "llm"}),
        ))

    def _register_test_agents(self) -> None:
        """Register test agents for the scenario."""
        # Research Agent
        self.agent_registry.register(AgentProfile(
            id="agent.research",
            name="Research Agent",
            specialization=AgentSpecialization.RESEARCH,
            preferred_capabilities=frozenset({"web.search"}),
            allowed_capabilities=frozenset({"web.search", "chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.TOOL}),
            allowed_categories=frozenset({CapabilityCategory.TOOL, CapabilityCategory.LLM}),
            delegation_policy="allow",
        ))

        # Coding Agent
        self.agent_registry.register(AgentProfile(
            id="agent.coding",
            name="Coding Agent",
            specialization=AgentSpecialization.CODING,
            preferred_capabilities=frozenset({"coding.execute_task"}),
            allowed_capabilities=frozenset({"coding.execute_task", "web.search", "chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.LLM}),
            allowed_categories=frozenset({CapabilityCategory.LLM, CapabilityCategory.TOOL}),
            delegation_policy="allow",
        ))

        # General Agent for synthesis
        self.agent_registry.register(AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
            preferred_capabilities=frozenset({"chat.respond"}),
            allowed_capabilities=frozenset({"chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.LLM}),
            allowed_categories=frozenset({CapabilityCategory.LLM}),
            delegation_policy="allow",
        ))

    def test_research_coding_synthesis_pipeline(self) -> None:
        """Test the complete research -> coding -> synthesis pipeline."""
        self._register_test_capabilities()
        self._register_test_agents()

        # Create a BrainRequest with three goals:
        # 1. Research (no dependencies)
        # 2. Coding (no dependencies)
        # 3. Synthesis (depends on both research and coding)
        request = BrainRequest(
            goals=(
                Goal(
                    id="research",
                    capability_id="web.search",
                    inputs={"query": "Python async best practices 2024 error handling"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="coding",
                    capability_id="coding.execute_task",
                    inputs={"instruction": "Create async error handling example"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="synthesis",
                    capability_id="chat.respond",
                    inputs={"prompt": "Synthesize research and code into final response"},
                    depends_on=("research", "coding"),
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
            )
        )

        # Execute the request
        response = self.brain.handle(request)

        # Verify overall success
        assert response.succeeded, f"Response failed: {response.results}"
        assert len(response.results) == 3

        # Check results by goal ID
        results_by_id = {result.goal_id: result for result in response.results}

        # Research should succeed
        research_result = results_by_id["research"]
        assert research_result.succeeded, f"Research failed: {research_result.failure}"
        assert research_result.status is not None

        # Coding should succeed
        coding_result = results_by_id["coding"]
        assert coding_result.succeeded, f"Coding failed: {coding_result.failure}"
        assert coding_result.status is not None

        # Synthesis should succeed (depends on both)
        synthesis_result = results_by_id["synthesis"]
        assert synthesis_result.succeeded, f"Synthesis failed: {synthesis_result.failure}"
        assert synthesis_result.status is not None

    def test_independent_goals_execute_concurrently(self) -> None:
        """Test that independent goals (research and coding) execute concurrently."""
        self._register_test_capabilities()
        self._register_test_agents()

        request = BrainRequest(
            goals=(
                Goal(
                    id="task1", 
                    capability_id="web.search", 
                    inputs={"query": "test1"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="task2", 
                    capability_id="coding.execute_task", 
                    inputs={"instruction": "test2"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="task3", 
                    capability_id="web.search", 
                    inputs={"query": "test3"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
            )
        )

        response = self.brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 3
        for result in response.results:
            assert result.succeeded

    def test_dependency_ordering_respected(self) -> None:
        """Test that dependent goals wait for their dependencies."""
        self._register_test_capabilities()
        self._register_test_agents()

        # Goal B depends on Goal A
        # Goal C depends on Goal B
        request = BrainRequest(
            goals=(
                Goal(
                    id="a", 
                    capability_id="web.search", 
                    inputs={"query": "step 1"},
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="b", 
                    capability_id="web.search", 
                    inputs={"query": "step 2"}, 
                    depends_on=("a",),
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
                Goal(
                    id="c", 
                    capability_id="chat.respond", 
                    inputs={"prompt": "step 3"}, 
                    depends_on=("b",),
                    provider_request_builder=lambda resolution, model: _FakeChatRequest(),
                ),
            )
        )

        response = self.brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 3
        for result in response.results:
            assert result.succeeded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])