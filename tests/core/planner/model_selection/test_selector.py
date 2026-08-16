"""
Unit tests for `parika.core.planner.model_selection.selector`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    ReasoningLevel,
    Requirement,
    ThinkingMode,
)
from parika.core.planner.model_selection import DEFAULT_SCORING_RULES
from parika.core.planner.model_selection.selector import (
    apply_context_budget,
    read_estimated_prompt_tokens,
    select_provider_model,
)
from parika.core.provider_manager.context_budget import RuntimeContextBudget
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest

_LOGGER = logging.getLogger("test.model_selection.selector")


def _requirements(**overrides: object) -> ExecutionRequirements:
    defaults: dict[str, object] = {"capability": ModelCapability.TEXT_GENERATION}
    defaults.update(overrides)
    return ExecutionRequirements(**defaults)  # type: ignore[arg-type]


class TestNoCandidates:
    def test_no_providers_registered(self) -> None:
        result = select_provider_model(
            providers=[],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert not result.succeeded
        assert result.evaluated_candidates == ()

    def test_only_incompatible_candidates(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset({ModelCapability.EMBEDDING}),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(
                capability=ModelCapability.TEXT_GENERATION
            ),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert not result.succeeded
        assert len(result.evaluated_candidates) == 1
        assert result.evaluated_candidates[0].accepted is False


class TestTransparency:
    def test_evaluated_candidates_include_rejected_and_accepted(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="compatible",
                    name="Compatible",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
                ProviderModel(
                    id="incompatible",
                    name="Incompatible",
                    capabilities=frozenset({ModelCapability.EMBEDDING}),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        by_id = {
            evaluation.model_id: evaluation
            for evaluation in result.evaluated_candidates
        }

        assert by_id["compatible"].accepted is True
        assert by_id["incompatible"].accepted is False
        assert by_id["incompatible"].rejection_reason is not None

    def test_disabled_provider_is_reported_not_silently_dropped(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            enabled=False,
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert len(result.evaluated_candidates) == 1
        assert result.evaluated_candidates[0].rejection_reason == (
            "provider is disabled"
        )


class TestDeterministicSelection:
    def test_highest_score_wins(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            health=ProviderHealth(available=True),
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
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert result.succeeded
        assert result.selected_model.id == "fast"

    def test_ties_are_broken_deterministically(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="model-b",
                    name="B",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
                ProviderModel(
                    id="model-a",
                    name="A",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),  # type: ignore[arg-type]
        )

        result_1 = select_provider_model(
            providers=[provider],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )
        result_2 = select_provider_model(
            providers=[provider],
            requirements=_requirements(),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert result_1.selected_model.id == result_2.selected_model.id


class TestThinkingModeResolution:
    def test_simple_resolves_to_reasoning_disabled(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(reasoning_level=ReasoningLevel.SIMPLE),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert result.thinking_mode is ThinkingMode.OFF
        assert result.reasoning_enabled is False

    def test_complex_resolves_to_reasoning_enabled(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(
                reasoning_level=ReasoningLevel.COMPLEX
            ),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert result.thinking_mode is ThinkingMode.ON
        assert result.reasoning_enabled is True

    def test_normal_resolves_to_no_explicit_preference(self) -> None:
        provider = Provider(
            id="provider.a",
            name="A",
            models=(
                ProviderModel(
                    id="m1",
                    name="M1",
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION}
                    ),
                ),
            ),  # type: ignore[arg-type]
        )

        result = select_provider_model(
            providers=[provider],
            requirements=_requirements(reasoning_level=ReasoningLevel.NORMAL),
            config=ModelSelectionConfig(),
            rules=DEFAULT_SCORING_RULES,
            logger=_LOGGER,
        )

        assert result.thinking_mode is ThinkingMode.AUTO
        assert result.reasoning_enabled is None

        # Even without an explicit RequestOptions.reasoning override,
        # thinking mode is still reported for transparency.
        assert result.succeeded


@dataclass(frozen=True, slots=True)
class _FakeChatRequest(ProviderRequest):
    prompt: str = ""


class TestApplyContextBudget:
    def test_sets_context_window_tokens_on_real_request(self) -> None:
        request = apply_context_budget(
            _FakeChatRequest(prompt="hi"),
            RuntimeContextBudget(
                effective_context_window=4096,
                reserved_for_response=1024,
                safety_reserve=256,
            ),
        )

        assert isinstance(request, _FakeChatRequest)
        assert request.options.context_window_tokens == 4096
        assert request.prompt == "hi"

    def test_none_budget_leaves_request_untouched(self) -> None:
        original = _FakeChatRequest(prompt="hi")

        request = apply_context_budget(original, None)

        assert request is original

    def test_non_provider_request_is_left_untouched(self) -> None:
        result = apply_context_budget(
            "not a provider request",
            RuntimeContextBudget(
                effective_context_window=4096,
                reserved_for_response=1024,
                safety_reserve=256,
            ),
        )

        assert result == "not a provider request"


class TestReadEstimatedPromptTokens:
    """
    Planner never measures a prompt itself; it only ever reads the
    token estimate AI Context Engineering's Prompt Engineering
    responsibility already supplied on a built `ProviderRequest`'s
    generic `options.estimated_prompt_tokens` field.
    """

    def test_reads_the_value_already_supplied_on_a_real_request(self) -> None:
        request = _FakeChatRequest(
            options=RequestOptions(estimated_prompt_tokens=12345),
            prompt="hi",
        )

        assert read_estimated_prompt_tokens(request) == 12345

    def test_returns_none_when_no_estimate_was_ever_supplied(self) -> None:
        request = _FakeChatRequest(prompt="hi")

        assert read_estimated_prompt_tokens(request) is None

    def test_returns_none_for_a_non_provider_request(self) -> None:
        assert read_estimated_prompt_tokens("not a provider request") is None
