"""
End-to-end integration tests for the configurable Routing Strategy
(`[routing_model]`, see `docs/architecture
/Model_Selection_Framework.md` §14): a Goal marked as the routing
Goal (`Goal.metadata[ROUTING_GOAL_METADATA_KEY]`, set only by
`interfaces/ai_context/goal_builder.build_chat_goal()`) must be
selected via `select_fixed_routing_model()` when `mode = "fixed"`,
must fall back to the unmodified, existing
`select_provider_model()` pipeline whenever the fixed model is
missing/unavailable, and must never affect worker model selection
(Goals without that marker).

Mirrors `test_routing_recommendation_integration.py`'s fixture shape:
exercises the real, unmodified `Planner`, `CapabilityResolver`,
`ResourceManager`, `PolicyEngine`, `ProviderManager`, and
`ToolManager`.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.goal import ROUTING_GOAL_METADATA_KEY, Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.state_manager.states import ProviderState
from parika.core.tool_manager.tool_manager import ToolManager

_ROUTING_CAPABILITY_ID = "chat.respond"
_WORKER_CAPABILITY_ID = "vision.provider_describe_image"
_PROVIDER_ID = "provider.ollama"


class _FakeProviderDriver(ProviderDriver):
    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: Any) -> Any:
        raise NotImplementedError


class _DummyProviderRequest(ProviderRequest):
    pass


def _build_request(
    resolution: CapabilityResolution, model: ProviderModel
) -> ProviderRequest:
    return _DummyProviderRequest()


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()` (same shape
    as `test_config.py`'s own `_FakeConfiguration`), used to drive
    `[routing_model]` deterministically without real TOML files.
    """

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=Logger(Configuration()))


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def capability_registry(
    event_bus: EventBus, logger: Logger
) -> CapabilityRegistry:
    registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
    registry.register(
        CapabilityDefinition(
            id=_ROUTING_CAPABILITY_ID,
            name="Chat Respond",
            description="Respond to a chat turn.",
            category=CapabilityCategory.LLM,
        )
    )
    registry.register(
        CapabilityDefinition(
            id=_WORKER_CAPABILITY_ID,
            name="Vision Describe",
            description="Describe an image (worker Goal).",
            category=CapabilityCategory.LLM,
        )
    )
    return registry


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    manager = ProviderManager(event_bus=event_bus, logger=logger)
    manager.register(
        Provider(
            id=_PROVIDER_ID,
            name="Ollama",
            state=ProviderState.CONNECTED,
            # "model-a" loses the deterministic tie-break
            # (`selector._select_best()`'s `max()` over
            # `(total_score, provider_id, model_id)`) against
            # "model-b" when both score identically -- exactly like
            # `test_routing_recommendation_integration.py`'s own
            # baseline. This is deliberately used below to prove a
            # fixed routing model is used *regardless* of scoring.
            models=(
                ProviderModel(
                    id="model-a",
                    name="model-a",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
                ProviderModel(
                    id="model-b",
                    name="model-b",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
            ),  # type: ignore[arg-type]
        ),
        _FakeProviderDriver(),
    )
    return manager


def _make_planner(
    *,
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
    event_bus: EventBus,
    logger: Logger,
    configuration: object | None = None,
) -> Planner:
    return Planner(
        capability_resolver=CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        ),
        resource_manager=ResourceManager(
            configuration=Configuration(),
            logger=logger,
        ),
        policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
        provider_manager=provider_manager,
        tool_manager=ToolManager(event_bus=event_bus, logger=logger),
        logger=logger,
        configuration=configuration,  # type: ignore[arg-type]
    )


def _routing_goal(*, goal_id: str = "routing-goal") -> Goal:
    return Goal(
        id=goal_id,
        capability_id=_ROUTING_CAPABILITY_ID,
        provider_request_builder=_build_request,
        metadata={ROUTING_GOAL_METADATA_KEY: True},
    )


def _worker_goal(*, goal_id: str = "worker-goal") -> Goal:
    return Goal(
        id=goal_id,
        capability_id=_WORKER_CAPABILITY_ID,
        provider_request_builder=_build_request,
        metadata={},
    )


class TestAutoModeIsUnchanged:
    def test_default_configuration_none_behaves_like_before(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=None,
        )

        plan = planner.plan([_routing_goal()])

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-b"

    def test_explicit_auto_mode_behaves_like_before(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        configuration = _FakeConfiguration({"routing_model.mode": "auto"})

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        plan = planner.plan([_routing_goal()])

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-b"


class TestFixedModeSelectsThePinnedRoutingModel:
    def test_fixed_model_overrides_the_scoring_outcome(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        # "model-a" would lose the tie-break under "auto" (see
        # `TestAutoModeIsUnchanged`); pinning it via "fixed" must
        # still select it.
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        plan = planner.plan([_routing_goal()])

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-a"

    def test_fixed_thinking_false_disables_reasoning(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
                "routing_model.fixed_thinking": False,
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        plan = planner.plan([_routing_goal()])

        backend_request = plan.steps[0].execution_request.backend_request
        assert isinstance(backend_request, ProviderRequest)
        assert backend_request.options.reasoning is False

    def test_fixed_thinking_true_enables_reasoning(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
                "routing_model.fixed_thinking": True,
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        plan = planner.plan([_routing_goal()])

        backend_request = plan.steps[0].execution_request.backend_request
        assert isinstance(backend_request, ProviderRequest)
        assert backend_request.options.reasoning is True


class TestFixedModeFallsBackToAutoWhenUnavailable:
    def test_missing_fixed_model_falls_back_to_auto_and_warns(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "does-not-exist:latest",
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        with caplog.at_level(
            logging.WARNING, logger="parika.core.planner.planner"
        ):
            plan = planner.plan([_routing_goal()])

        model = plan.steps[0].execution_request.target.model
        # Falls back to the exact same "auto" outcome as the
        # backward-compatibility baseline above.
        assert model is not None and model.id == "model-b"
        assert any(
            "falling back to automatic routing model selection"
            in record.message
            for record in caplog.records
        )

    def test_disabled_provider_falls_back_to_auto(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
        provider_manager.register(
            Provider(
                id=_PROVIDER_ID,
                name="Ollama",
                state=ProviderState.CONNECTED,
                enabled=False,
                models=(
                    ProviderModel(
                        id="model-a",
                        name="model-a",
                        capabilities=frozenset(
                            {ModelCapability.TEXT_GENERATION}
                        ),
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        # No enabled candidate exists at all (auto also has nothing to
        # fall back to), so Planner still raises exactly like today,
        # never silently succeeding with a disabled provider.
        from parika.core.planner.exceptions import NoAvailableProviderModelError

        with pytest.raises(NoAvailableProviderModelError):
            planner.plan([_routing_goal()])


class TestWorkerSelectionRemainsUnaffected:
    def test_worker_goal_ignores_fixed_routing_configuration(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        plan = planner.plan([_routing_goal(), _worker_goal()])

        by_goal = {step.goal_id: step for step in plan.steps}

        routing_model = by_goal["routing-goal"].execution_request.target.model
        worker_model = by_goal["worker-goal"].execution_request.target.model

        assert routing_model is not None and routing_model.id == "model-a"
        # The worker Goal carries no ROUTING_GOAL_METADATA_KEY, so it
        # is completely unaffected by "fixed" mode and still resolves
        # through the unmodified "auto" scoring pipeline -- the exact
        # same "model-b" tie-break outcome as before this feature
        # existed.
        assert worker_model is not None and worker_model.id == "model-b"


class TestBackwardCompatibility:
    def test_goal_without_routing_marker_is_never_treated_as_routing(
        self,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        # Even in "fixed" mode, a Goal targeting the chat capability
        # id but never marked with ROUTING_GOAL_METADATA_KEY (e.g. a
        # caller that has not adopted the marker) must fall through to
        # unmodified "auto" selection -- the marker, not the
        # capability id, is what Planner reads.
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "model-a",
            }
        )

        planner = _make_planner(
            capability_registry=capability_registry,
            provider_manager=provider_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        unmarked_goal = Goal(
            id="unmarked-goal",
            capability_id=_ROUTING_CAPABILITY_ID,
            provider_request_builder=_build_request,
        )

        plan = planner.plan([unmarked_goal])

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-b"
