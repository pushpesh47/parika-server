"""
Unit tests for Planner.

These tests exercise Planner against the real frozen components it
depends on (CapabilityResolver, ResourceManager, PolicyEngine,
ProviderManager, ToolManager) so that the integration contract is
verified, not just Planner in isolation. Logger and EventBus are
replaced with lightweight test doubles to avoid file/console side
effects.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.capability_executor.execution_backend import (
    ExecutionBackend,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.capability_resolver.exceptions import (
    CapabilityDisabledError,
)
from parika.core.capability_registry.exceptions import (
    CapabilityNotFoundError,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.exceptions import (
    CyclicDependencyError,
    DuplicateGoalIdError,
    GoalDeniedByPolicyError,
    InvalidGoalError,
    MissingProviderRequestBuilderError,
    NoAvailableProviderModelError,
    NoAvailableToolError,
    UnknownGoalDependencyError,
)
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.policy_engine.policy_rule import PolicyRule
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.state_manager.states import ProviderState
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager


class _FakeToolDriver:
    def execute(self, request: ToolRequest) -> ToolResponse:
        return ToolResponse(outputs={"ok": True})


class _FakeProviderDriver(ProviderDriver):
    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: Any) -> Any:
        raise NotImplementedError


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=Logger(Configuration()))


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def capability_resolver(
    capability_registry: CapabilityRegistry,
    logger: Logger,
) -> CapabilityResolver:
    return CapabilityResolver(
        capability_registry=capability_registry,
        logger=logger,
    )


@pytest.fixture
def resource_manager(logger: Logger) -> ResourceManager:
    return ResourceManager(
        configuration=Configuration(),
        logger=logger,
    )


@pytest.fixture
def policy_engine(event_bus: EventBus, logger: Logger) -> PolicyEngine:
    return PolicyEngine(event_bus=event_bus, logger=logger)


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    return ProviderManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def planner(
    capability_resolver: CapabilityResolver,
    resource_manager: ResourceManager,
    policy_engine: PolicyEngine,
    provider_manager: ProviderManager,
    tool_manager: ToolManager,
    logger: Logger,
) -> Planner:
    return Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
    )


def _register_tool_capability(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    *,
    capability_id: str = "web.search",
    tool_id: str = "tool.web_search",
    enabled: bool = True,
) -> None:
    capability_registry.register(
        CapabilityDefinition(
            id=capability_id,
            name="Web Search",
            description="Search the web.",
            category=CapabilityCategory.TOOL,
        )
    )
    tool_manager.register(
        Tool(
            id=tool_id,
            name="Web Search Tool",
            version="1.0.0",
            description="Searches the web.",
            capabilities=(capability_id,),
            enabled=enabled,
        ),
        _FakeToolDriver(),
    )


def _register_llm_capability(
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
    *,
    capability_id: str = "chat.generate",
    provider_id: str = "provider.ollama",
    model_id: str = "llama3",
) -> None:
    capability_registry.register(
        CapabilityDefinition(
            id=capability_id,
            name="Chat Generation",
            description="Generate a chat response.",
            category=CapabilityCategory.LLM,
        )
    )
    provider_manager.register(
        Provider(
            id=provider_id,
            name="Ollama",
            state=ProviderState.CONNECTED,
            # NOTE: ProviderModel's default `metadata` field uses a
            # plain dict, which is unhashable, so real ProviderModel
            # instances cannot be placed in a frozenset. Provider.models
            # is not runtime-validated, so a tuple is used here instead.
models=(
                    ProviderModel(
                        id="local_speech_tts",
                        name="Kokoro",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_TO_SPEECH}
                        ),
                    ),
                ),  # type: ignore[arg-type]
        ),
        _FakeProviderDriver(),
    )


# ---------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------


class TestValidation:
    def test_rejects_empty_goals(self, planner: Planner) -> None:
        with pytest.raises(InvalidGoalError):
            planner.plan([])

    def test_rejects_non_goal_items(self, planner: Planner) -> None:
        with pytest.raises(InvalidGoalError):
            planner.plan([object()])  # type: ignore[list-item]

    def test_rejects_duplicate_goal_ids(self, planner: Planner) -> None:
        goals = [
            Goal(id="g1", capability_id="web.search"),
            Goal(id="g1", capability_id="web.search"),
        ]

        with pytest.raises(DuplicateGoalIdError):
            planner.plan(goals)

    def test_rejects_unknown_dependency(self, planner: Planner) -> None:
        goals = [
            Goal(id="g1", capability_id="web.search", depends_on=("missing",))
        ]

        with pytest.raises(UnknownGoalDependencyError):
            planner.plan(goals)

    def test_rejects_cyclic_dependency(self, planner: Planner) -> None:
        goals = [
            Goal(id="a", capability_id="web.search", depends_on=("b",)),
            Goal(id="b", capability_id="web.search", depends_on=("a",)),
        ]

        with pytest.raises(CyclicDependencyError):
            planner.plan(goals)


# ---------------------------------------------------------------------
# Capability resolution propagation
# ---------------------------------------------------------------------


class TestCapabilityResolution:
    def test_propagates_capability_not_found(self, planner: Planner) -> None:
        goals = [Goal(id="g1", capability_id="unknown.capability")]

        with pytest.raises(CapabilityNotFoundError):
            planner.plan(goals)

    def test_propagates_capability_disabled(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="disabled.capability",
                name="Disabled",
                description="Disabled capability.",
                category=CapabilityCategory.TOOL,
                enabled=False,
            )
        )

        goals = [Goal(id="g1", capability_id="disabled.capability")]

        with pytest.raises(CapabilityDisabledError):
            planner.plan(goals)


# ---------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------


class TestDependencyOrdering:
    def test_orders_steps_by_dependency(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        goals = [
            Goal(id="child", capability_id="web.search", depends_on=("parent",)),
            Goal(id="parent", capability_id="web.search"),
        ]

        plan = planner.plan(goals)

        assert [step.goal_id for step in plan.steps] == ["parent", "child"]

    def test_independent_goals_preserve_deterministic_order(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        goals = [
            Goal(id="b", capability_id="web.search"),
            Goal(id="a", capability_id="web.search"),
        ]

        plan = planner.plan(goals)

        assert [step.goal_id for step in plan.steps] == ["a", "b"]


# ---------------------------------------------------------------------
# TOOL execution strategy
# ---------------------------------------------------------------------


class TestToolStrategy:
    def test_selects_matching_enabled_tool(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        goals = [
            Goal(
                id="g1",
                capability_id="web.search",
                inputs={"query": "parika architecture"},
            )
        ]

        plan = planner.plan(goals)

        assert len(plan.steps) == 1
        step = plan.steps[0]
        request = step.execution_request

        assert request.target.backend is ExecutionBackend.TOOL
        assert request.target.identifier == "tool.web_search"
        assert isinstance(request.backend_request, ToolRequest)
        assert request.backend_request.arguments["query"] == (
            "parika architecture"
        )

    def test_raises_when_no_tool_implements_capability(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="web.search",
                name="Web Search",
                description="Search the web.",
                category=CapabilityCategory.TOOL,
            )
        )

        goals = [Goal(id="g1", capability_id="web.search")]

        with pytest.raises(NoAvailableToolError):
            planner.plan(goals)

    def test_disabled_tool_is_not_a_candidate(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(
            capability_registry, tool_manager, enabled=False
        )

        goals = [Goal(id="g1", capability_id="web.search")]

        with pytest.raises(NoAvailableToolError):
            planner.plan(goals)


# ---------------------------------------------------------------------
# PROVIDER execution strategy
# ---------------------------------------------------------------------


class TestProviderStrategy:
    def test_selects_matching_provider_model(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        _register_llm_capability(capability_registry, provider_manager)

        built_requests: list[Any] = []

        def _builder(resolution: Any, model: ProviderModel) -> Any:
            built_requests.append(model)
            return "built-request"

        goals = [
            Goal(
                id="g1",
                capability_id="chat.generate",
                provider_request_builder=_builder,
            )
        ]

        plan = planner.plan(goals)

        step = plan.steps[0]
        request = step.execution_request

        assert request.target.backend is ExecutionBackend.PROVIDER
        assert request.target.identifier == "provider.ollama"
        assert request.target.model is not None
        assert request.target.model.id == "llama3"
        assert request.backend_request == "built-request"
        assert built_requests == [request.target.model]

    def test_raises_when_missing_provider_request_builder(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        _register_llm_capability(capability_registry, provider_manager)

        goals = [Goal(id="g1", capability_id="chat.generate")]

        with pytest.raises(MissingProviderRequestBuilderError):
            planner.plan(goals)

    def test_raises_when_no_provider_model_matches(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="chat.generate",
                name="Chat Generation",
                description="Generate a chat response.",
                category=CapabilityCategory.LLM,
            )
        )

        goals = [
            Goal(
                id="g1",
                capability_id="chat.generate",
                provider_request_builder=lambda resolution, model: None,
            )
        ]

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan(goals)

    def test_raises_for_category_without_provider_mapping(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="memory.recall",
                name="Memory Recall",
                description="Recall memory.",
                category=CapabilityCategory.MEMORY,
            )
        )

        goals = [Goal(id="g1", capability_id="memory.recall")]

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan(goals)

    def test_disabled_provider_is_not_a_candidate(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="chat.generate",
                name="Chat Generation",
                description="Generate a chat response.",
                category=CapabilityCategory.LLM,
            )
        )
        provider_manager.register(
            Provider(
                id="provider.local_speech",
                name="Local Speech",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="local_speech_tts",
                        name="Kokoro",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_TO_SPEECH}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        goals = [
            Goal(
                id="g1",
                capability_id="chat.generate",
                provider_request_builder=lambda resolution, model: None,
            )
        ]

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan(goals)


# ---------------------------------------------------------------------
# Policy enforcement
# ---------------------------------------------------------------------


class TestPolicyEnforcement:
    def test_denies_goal_when_policy_rule_matches_deny(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        deny_rule = PolicyRule(
            id="deny-all",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: True,
            reason="Blocked for testing.",
        )

        goals = [
            Goal(
                id="g1",
                capability_id="web.search",
                policy_rules=(deny_rule,),
            )
        ]

        with pytest.raises(GoalDeniedByPolicyError):
            planner.plan(goals)

    def test_allows_goal_when_no_policy_rules_supplied(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        goals = [Goal(id="g1", capability_id="web.search")]

        plan = planner.plan(goals)

        assert len(plan.steps) == 1

    def test_allow_rule_permits_goal(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        allow_rule = PolicyRule(
            id="allow-all",
            effect=PolicyEffect.ALLOW,
            predicate=lambda ctx: True,
        )

        goals = [
            Goal(
                id="g1",
                capability_id="web.search",
                policy_rules=(allow_rule,),
            )
        ]

        plan = planner.plan(goals)

        assert len(plan.steps) == 1

    def test_policy_context_includes_resource_snapshot(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        _register_tool_capability(capability_registry, tool_manager)

        observed_contexts: list[Any] = []

        def _capture(context: Any) -> bool:
            observed_contexts.append(context)
            return False

        rule = PolicyRule(
            id="observe",
            effect=PolicyEffect.DENY,
            predicate=_capture,
        )

        goals = [
            Goal(id="g1", capability_id="web.search", policy_rules=(rule,))
        ]

        planner.plan(goals)

        assert len(observed_contexts) == 1
        assert "resource_snapshot" in observed_contexts[0]
        assert observed_contexts[0]["capability_id"] == "web.search"


# ---------------------------------------------------------------------
# SPEECH vs. TEXT_TO_SPEECH category independence (Voice capability)
#
# Regression coverage for a genuine gap discovered while implementing
# the Voice capability: before `CapabilityCategory.TEXT_TO_SPEECH`
# existed, every SPEECH-family category derived the single hard
# `ModelCapability.SPEECH_TO_TEXT` requirement (`CATEGORY_TO_MODEL_
# CAPABILITY` in `planner.py`), which would have incorrectly required
# any text-to-speech-only Provider model to also advertise
# `SPEECH_TO_TEXT` just to be selectable at all. `TEXT_TO_SPEECH` is a
# distinct category (mapping to `ModelCapability.TEXT_TO_SPEECH`),
# exactly mirroring `IMAGE_GENERATION`/`VIDEO_GENERATION` already
# being distinct from `VISION`.
# ---------------------------------------------------------------------


class TestTextToSpeechCategoryIsIndependentFromSpeech:
    def test_text_to_speech_only_model_satisfies_a_text_to_speech_goal(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="voice.provider_text_to_speech",
                name="Text to Speech",
                description="Synthesize speech.",
                category=CapabilityCategory.TEXT_TO_SPEECH,
            )
        )
        provider_manager.register(
            Provider(
                id="provider.local_speech",
                name="Local Speech",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="local_speech_tts",
                        name="Kokoro",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_TO_SPEECH}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        goals = [
            Goal(
                id="g1",
                capability_id="voice.provider_text_to_speech",
                provider_request_builder=lambda resolution, model: "built",
            )
        ]

        plan = planner.plan(goals)

        assert plan.steps[0].execution_request.target.model.id == "local_speech_tts"

    def test_speech_to_text_only_model_does_not_satisfy_a_text_to_speech_goal(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="voice.provider_text_to_speech",
                name="Text to Speech",
                description="Synthesize speech.",
                category=CapabilityCategory.TEXT_TO_SPEECH,
            )
        )
        provider_manager.register(
            Provider(
                id="provider.local_speech",
                name="Local Speech",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="local_speech_stt",
                        name="faster-whisper",
                        capabilities=frozenset(
                            {ModelCapability.SPEECH_TO_TEXT}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        goals = [
            Goal(
                id="g1",
                capability_id="voice.provider_text_to_speech",
                provider_request_builder=lambda resolution, model: "built",
            )
        ]

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan(goals)

    def test_text_to_speech_only_model_does_not_satisfy_a_speech_to_text_goal(
        self,
        planner: Planner,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        capability_registry.register(
            CapabilityDefinition(
                id="voice.provider_speech_to_text",
                name="Speech to Text",
                description="Transcribe audio.",
                category=CapabilityCategory.SPEECH,
            )
        )
        provider_manager.register(
            Provider(
                id="provider.local_speech",
                name="Local Speech",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="local_speech_tts",
                        name="Kokoro",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_TO_SPEECH}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        goals = [
            Goal(
                id="g1",
                capability_id="voice.provider_speech_to_text",
                provider_request_builder=lambda resolution, model: "built",
            )
        ]

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan(goals)
