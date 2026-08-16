"""
End-to-end integration test for AI-assisted model-selection
refinement: a routing recommendation carried on `Goal.metadata
["execution_requirements"]["metadata"]["candidate_models"]` must flow,
completely unmodified, through the real `Planner` -> real
`model_selection` pipeline (`build_execution_requirements()` ->
`evaluate_hard_requirements()` -> `select_provider_model()` ->
`RoutingRecommendationRule`) and influence which of two otherwise
identically-scored candidate models Planner actually selects.

This deliberately exercises the real, unmodified `Planner`,
`CapabilityResolver`, `ResourceManager`, `PolicyEngine`,
`ProviderManager`, and `ToolManager` -- mirroring
`tests/core/planner/test_planner.py`'s own fixture shape -- so the
full integration contract is verified, not just
`RoutingRecommendationRule` in isolation (already covered by
`tests/core/planner/model_selection/test_routing_recommendation_rule.py`).
"""

from __future__ import annotations

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
from parika.core.planner.goal import Goal
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

_CAPABILITY_ID = "vision.provider_describe_image"
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


def _build_request(resolution: CapabilityResolution, model: ProviderModel) -> ProviderRequest:
    return _DummyProviderRequest()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=Logger(Configuration()))


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def capability_registry(event_bus: EventBus, logger: Logger) -> CapabilityRegistry:
    registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
    registry.register(
        CapabilityDefinition(
            id=_CAPABILITY_ID,
            name="Vision Describe",
            description="Describe an image.",
            category=CapabilityCategory.VISION,
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
            # Two models, deliberately identical on every dimension
            # every other built-in ScoringRule reads, so only
            # `RoutingRecommendationRule` can ever break the tie --
            # isolating exactly the behavior under test. `Provider
            # .models` is not runtime-validated, so a plain tuple is
            # used (`ProviderModel` is not hashable -- see
            # `test_planner.py`'s own identical note).
            models=(
                ProviderModel(
                    id="model-a",
                    name="model-a",
                    capabilities=frozenset({ModelCapability.VISION}),
                    specializations=frozenset({"vision_understanding"}),
                ),
                ProviderModel(
                    id="model-b",
                    name="model-b",
                    capabilities=frozenset({ModelCapability.VISION}),
                    specializations=frozenset({"vision_understanding"}),
                ),
            ),  # type: ignore[arg-type]
        ),
        _FakeProviderDriver(),
    )
    return manager


@pytest.fixture
def planner(
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
    event_bus: EventBus,
    logger: Logger,
) -> Planner:
    from parika.core.capability_resolver.capability_resolver import (
        CapabilityResolver,
    )

    return Planner(
        capability_resolver=CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        ),
        resource_manager=ResourceManager(configuration=Configuration(), logger=logger),
        policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
        provider_manager=provider_manager,
        tool_manager=ToolManager(event_bus=event_bus, logger=logger),
        logger=logger,
    )


def _goal(*, execution_requirements: dict[str, Any] | None = None) -> Goal:
    metadata: dict[str, Any] = {}

    if execution_requirements is not None:
        metadata["execution_requirements"] = execution_requirements

    return Goal(
        id="g1",
        capability_id=_CAPABILITY_ID,
        provider_request_builder=_build_request,
        metadata=metadata,
    )


class TestRoutingRecommendationInfluencesRealPlannerSelection:
    def test_without_a_hint_the_tie_breaks_deterministically(
        self, planner: Planner
    ) -> None:
        # Baseline (backward compatibility): with no routing
        # recommendation at all, every candidate scores identically,
        # so the existing, unmodified tie-break rule (`max()` over
        # `(total_score, provider_id, model_id)`, `selector.py
        # ._select_best()`) picks "model-b" (the lexicographically
        # larger id) -- exactly the outcome this exact scenario would
        # have produced before this feature existed.
        plan = planner.plan([_goal()])

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-b"

    def test_recommending_the_otherwise_losing_candidate_flips_the_outcome(
        self, planner: Planner
    ) -> None:
        # "model-a" loses the deterministic tie-break above; a strong
        # recommendation for it must be enough to flip the outcome.
        plan = planner.plan(
            [
                _goal(
                    execution_requirements={
                        "metadata": {
                            "candidate_models": [
                                {
                                    "provider_id": _PROVIDER_ID,
                                    "model_id": "model-a",
                                    "confidence": 1.0,
                                }
                            ]
                        }
                    }
                )
            ]
        )

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-a"

    def test_low_confidence_recommendation_is_not_enough_to_flip_the_tie(
        self, planner: Planner
    ) -> None:
        # A low-confidence recommendation for "model-a" contributes
        # less than the neutral 0.5 baseline every candidate already
        # gets, so it must not be enough to overcome "model-b"'s
        # deterministic tie-break advantage.
        plan = planner.plan(
            [
                _goal(
                    execution_requirements={
                        "metadata": {
                            "candidate_models": [
                                {
                                    "provider_id": _PROVIDER_ID,
                                    "model_id": "model-a",
                                    "confidence": 0.1,
                                }
                            ]
                        }
                    }
                )
            ]
        )

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id == "model-b"

    def test_recommending_a_hard_filtered_candidate_never_selects_it(
        self, planner: Planner, provider_manager: ProviderManager
    ) -> None:
        # A routing recommendation for a candidate that fails a hard
        # requirement (here: missing the required specialization)
        # must never be selected -- filtering.py remains the
        # unmodified, final authority; the recommendation is only
        # ever a scoring signal for candidates that already survive
        # it.
        provider_manager.register(
            Provider(
                id="provider.incompatible",
                name="Incompatible Provider",
                state=ProviderState.CONNECTED,
                models=(
                    ProviderModel(
                        id="model-c",
                        name="model-c",
                        capabilities=frozenset({ModelCapability.VISION}),
                        specializations=frozenset({"ocr"}),  # wrong specialization
                    ),
                ),  # type: ignore[arg-type]
            ),
            _FakeProviderDriver(),
        )

        plan = planner.plan(
            [
                _goal(
                    execution_requirements={
                        "required_specializations": ["vision_understanding"],
                        "metadata": {
                            "candidate_models": [
                                {
                                    "provider_id": "provider.incompatible",
                                    "model_id": "model-c",
                                    "confidence": 1.0,
                                }
                            ]
                        },
                    }
                )
            ]
        )

        model = plan.steps[0].execution_request.target.model
        assert model is not None and model.id in {"model-a", "model-b"}
