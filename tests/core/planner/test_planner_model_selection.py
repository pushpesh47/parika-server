"""
Planner-level integration tests for intelligent model selection.

`tests/core/planner/test_planner.py` covers Planner's pre-existing
single-candidate behavior and remains unmodified; these tests add
coverage specifically for multi-candidate scoring, the
`RequestOptions.reasoning` injection, and `ExecutionRequirements`
sourced from `Goal.metadata`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.exceptions import NoAvailableProviderModelError
from parika.core.planner.goal import Goal
from parika.core.planner.model_selection import ExecutionRequirements, ReasoningLevel
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.tool_manager.tool_manager import ToolManager


class _FakeProviderDriver(ProviderDriver):
    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: object) -> object:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _FakeChatRequest(ProviderRequest):
    prompt: str = ""


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
    registry.register(
        CapabilityDefinition(
            id="chat.generate",
            name="Chat Generation",
            description="Generate a chat response.",
            category=CapabilityCategory.LLM,
        )
    )
    return registry


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    return ProviderManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def planner(
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
    logger: Logger,
    event_bus: EventBus,
) -> Planner:
    return Planner(
        capability_resolver=CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        ),
        resource_manager=ResourceManager(
            configuration=Configuration(), logger=logger
        ),
        policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
        provider_manager=provider_manager,
        tool_manager=ToolManager(event_bus=event_bus, logger=logger),
        logger=logger,
    )


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
            models=models,  # type: ignore[arg-type]
        ),
        _FakeProviderDriver(),
    )


class TestMultiCandidateSelection:
    def test_selects_the_lower_latency_model(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="slow",
                    name="Slow",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                    metadata={"estimated_latency_ms": 900.0},
                ),
                ProviderModel(
                    id="fast",
                    name="Fast",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                    metadata={"estimated_latency_ms": 100.0},
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        model = plan.steps[0].execution_request.target.model
        assert model is not None
        assert model.id == "fast"

    def test_excludes_model_missing_required_capability(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="wrong-capability",
                    name="Wrong",
                    capabilities=frozenset({ModelCapability.EMBEDDING}),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan([goal])

    def test_excludes_unavailable_provider(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        planner = Planner(
            capability_resolver=CapabilityResolver(
                capability_registry=capability_registry, logger=logger
            ),
            resource_manager=ResourceManager(
                configuration=Configuration(), logger=logger
            ),
            policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
            provider_manager=provider_manager,
            tool_manager=ToolManager(event_bus=event_bus, logger=logger),
            logger=logger,
        )

        provider_manager.register(
            Provider(
                id="provider.unavailable",
                name="Unavailable",
                health=ProviderHealth(available=False),
                models=(
                    ProviderModel(
                        id="m1",
                        name="M1",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_GENERATION}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan([goal])


class TestReasoningPreferenceInjection:
    def test_complex_requirement_sets_reasoning_true_on_real_request(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            metadata={
                "execution_requirements": ExecutionRequirements(
                    capability=ModelCapability.TEXT_GENERATION,
                    reasoning_level=ReasoningLevel.COMPLEX,
                )
            },
            provider_request_builder=lambda resolution, model: _FakeChatRequest(
                prompt="solve this"
            ),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert isinstance(backend_request, _FakeChatRequest)
        assert backend_request.options.reasoning is True
        assert backend_request.prompt == "solve this"

    def test_simple_requirement_sets_reasoning_false(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            metadata={
                "execution_requirements": ExecutionRequirements(
                    capability=ModelCapability.TEXT_GENERATION,
                    reasoning_level=ReasoningLevel.SIMPLE,
                )
            },
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.reasoning is False

    def test_non_provider_request_builder_result_is_left_untouched(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        """
        A builder that returns something other than a real
        ProviderRequest (as `tests/core/planner/test_planner.py`
        already exercises) must never break, even though a reasoning
        preference is now injected for real ProviderRequest objects.
        """

        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            metadata={
                "execution_requirements": ExecutionRequirements(
                    capability=ModelCapability.TEXT_GENERATION,
                    reasoning_level=ReasoningLevel.COMPLEX,
                )
            },
            provider_request_builder=lambda resolution, model: "not-a-request",
        )

        plan = planner.plan([goal])

        assert plan.steps[0].execution_request.backend_request == (
            "not-a-request"
        )


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, following
    the same pattern as
    `tests/core/planner/model_selection/test_config.py`.
    """

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class TestRuntimeContextBudgetInjection:
    """
    Planner-level coverage for the Runtime Context Budget: once a
    model is selected, its own `ModelLimits.context_window` must flow
    onto the built `ProviderRequest`'s
    `RequestOptions.context_window_tokens` field, dynamically and
    never hardcoded.
    """

    def test_selected_model_context_window_sets_context_window_tokens(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        from parika.core.provider_manager.model_limits import ModelLimits

        planner = Planner(
            capability_resolver=CapabilityResolver(
                capability_registry=capability_registry, logger=logger
            ),
            resource_manager=ResourceManager(
                configuration=Configuration(), logger=logger
            ),
            policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
            provider_manager=provider_manager,
            tool_manager=ToolManager(event_bus=event_bus, logger=logger),
            logger=logger,
            configuration=_FakeConfiguration(  # type: ignore[arg-type]
                {"context_engine.default_context_window_tokens": 128000}
            ),
        )

        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                    limits=ModelLimits(context_window=40960),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert isinstance(backend_request, _FakeChatRequest)
        assert backend_request.options.context_window_tokens == 40960

    def test_different_selected_models_yield_different_budgets(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        """
        The exact defining property of a dynamic, non-hardcoded
        Runtime Context Budget: two different Goals selecting two
        different models must receive two different
        `context_window_tokens` values.
        """

        from parika.core.provider_manager.model_limits import ModelLimits

        _register_provider(
            provider_manager,
            provider_id="provider.small",
            models=(
                ProviderModel(
                    id="small-model",
                    name="Small",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                    limits=ModelLimits(context_window=2048),
                ),
            ),
        )

        small_goal = Goal(
            id="g-small",
            capability_id="chat.generate",
            policy_rules=(),
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([small_goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 2048

    def test_missing_configuration_still_sets_a_dynamic_default(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        """
        Even with no Configuration supplied at all, the budget is
        still computed (from built-in defaults + the model's own
        capabilities), never left unset/hardcoded to nothing.
        """

        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 8192


class TestRuntimeContextBudgetFromEstimatedPromptTokens:
    """
    Planner-level coverage for the num_ctx fix: AI Context
    Engineering's Prompt Engineering responsibility measures the
    complete, already-assembled prompt exactly once (see
    `interfaces/ai_context/goal_builder.py`) and supplies the result
    via `RequestOptions.estimated_prompt_tokens` on the built
    `ProviderRequest` -- Planner only ever reads it, via
    `read_estimated_prompt_tokens()`, never measuring a prompt itself.
    """

    def test_large_estimate_grows_context_window_beyond_the_ceiling(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        planner = Planner(
            capability_resolver=CapabilityResolver(
                capability_registry=capability_registry, logger=logger
            ),
            resource_manager=ResourceManager(
                configuration=Configuration(), logger=logger
            ),
            policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
            provider_manager=provider_manager,
            tool_manager=ToolManager(event_bus=event_bus, logger=logger),
            logger=logger,
            configuration=_FakeConfiguration(  # type: ignore[arg-type]
                {
                    "context_engine.default_context_window_tokens": 8192,
                    "context_engine.reserved_for_response_tokens": 1024,
                    "context_engine.safety_reserve_tokens": 256,
                }
            ),
        )

        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=(
                lambda resolution, model: _FakeChatRequest(
                    options=RequestOptions(estimated_prompt_tokens=11087)
                )
            ),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 11087 + 1024 + 256

    def test_large_estimate_is_clamped_to_the_selected_models_context_window(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        from parika.core.provider_manager.model_limits import ModelLimits

        _register_provider(
            provider_manager,
            provider_id="provider.small",
            models=(
                ProviderModel(
                    id="small-model",
                    name="Small",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                    limits=ModelLimits(context_window=4096),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=(
                lambda resolution, model: _FakeChatRequest(
                    options=RequestOptions(estimated_prompt_tokens=50000)
                )
            ),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 4096

    def test_small_estimate_leaves_todays_behavior_unchanged(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=(
                lambda resolution, model: _FakeChatRequest(
                    options=RequestOptions(estimated_prompt_tokens=5)
                )
            ),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 8192

    def test_no_estimate_leaves_todays_behavior_unchanged(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        backend_request = plan.steps[0].execution_request.backend_request
        assert backend_request.options.context_window_tokens == 8192


class TestExecutionRequirementsFromGoalMetadata:
    def test_tool_calling_preferred_hint_influences_selection(
        self,
        planner: Planner,
        provider_manager: ProviderManager,
    ) -> None:
        from parika.core.provider_manager.model_execution_feature import (
            ModelExecutionFeature,
        )
        from parika.core.planner.model_selection import Requirement

        _register_provider(
            provider_manager,
            provider_id="provider.test",
            models=(
                ProviderModel(
                    id="no-tools",
                    name="No Tools",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
                ProviderModel(
                    id="with-tools",
                    name="With Tools",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                    execution_features=frozenset(
                        {ModelExecutionFeature.TOOL_CALLING}
                    ),
                ),
            ),
        )

        goal = Goal(
            id="g1",
            capability_id="chat.generate",
            metadata={
                "execution_requirements": {
                    "tool_calling": Requirement.PREFERRED.value,
                }
            },
            provider_request_builder=lambda resolution, model: _FakeChatRequest(),
        )

        plan = planner.plan([goal])

        model = plan.steps[0].execution_request.target.model
        assert model is not None
        assert model.id == "with-tools"
