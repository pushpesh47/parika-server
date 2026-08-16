"""
Unit tests for `parika.core.planner.model_selection.rules`.
"""

from __future__ import annotations

from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    ReasoningLevel,
    Requirement,
)
from parika.core.planner.model_selection.rules import (
    ContextWindowRule,
    CostRule,
    LatencyRule,
    ReasoningRule,
    ToolCallingRule,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel


def _provider(**overrides: object) -> Provider:
    return Provider(id="provider.test", name="Test Provider", **overrides)  # type: ignore[arg-type]


def _model(**overrides: object) -> ProviderModel:
    defaults: dict[str, object] = {"id": "model-a", "name": "Model A"}
    defaults.update(overrides)
    return ProviderModel(**defaults)  # type: ignore[arg-type]


def _requirements(**overrides: object) -> ExecutionRequirements:
    defaults: dict[str, object] = {"capability": ModelCapability.TEXT_GENERATION}
    defaults.update(overrides)
    return ExecutionRequirements(**defaults)  # type: ignore[arg-type]


class TestLatencyRule:
    def test_prefers_lower_latency_relative_to_pool(self) -> None:
        rule = LatencyRule()
        config = ModelSelectionConfig()
        fast = _model(id="fast", metadata={"estimated_latency_ms": 100.0})
        slow = _model(id="slow", metadata={"estimated_latency_ms": 900.0})
        provider = _provider()
        pool = [(provider, fast), (provider, slow)]

        fast_outcome = rule.evaluate(
            provider=provider,
            model=fast,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )
        slow_outcome = rule.evaluate(
            provider=provider,
            model=slow,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )

        assert fast_outcome.contribution > slow_outcome.contribution
        assert fast_outcome.raw_score == 1.0
        assert slow_outcome.raw_score == 0.0

    def test_neutral_when_no_candidate_reports_latency(self) -> None:
        rule = LatencyRule()
        config = ModelSelectionConfig()
        model = _model()
        provider = _provider()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5


class TestReasoningRule:
    def test_complex_favors_reasoning_capable_models(self) -> None:
        rule = ReasoningRule()
        config = ModelSelectionConfig()
        provider = _provider()
        reasoning_model = _model(
            capabilities=frozenset({ModelCapability.REASONING})
        )
        plain_model = _model(id="plain")

        reasoning_outcome = rule.evaluate(
            provider=provider,
            model=reasoning_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.COMPLEX),
            config=config,
            candidate_pool=[],
        )
        plain_outcome = rule.evaluate(
            provider=provider,
            model=plain_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.COMPLEX),
            config=config,
            candidate_pool=[],
        )

        assert reasoning_outcome.contribution > plain_outcome.contribution

    def test_simple_favors_non_reasoning_models(self) -> None:
        rule = ReasoningRule()
        config = ModelSelectionConfig()
        provider = _provider()
        reasoning_model = _model(
            capabilities=frozenset({ModelCapability.REASONING})
        )
        plain_model = _model(id="plain")

        reasoning_outcome = rule.evaluate(
            provider=provider,
            model=reasoning_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.SIMPLE),
            config=config,
            candidate_pool=[],
        )
        plain_outcome = rule.evaluate(
            provider=provider,
            model=plain_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.SIMPLE),
            config=config,
            candidate_pool=[],
        )

        assert plain_outcome.contribution > reasoning_outcome.contribution

    def test_normal_mildly_favors_non_reasoning_models(self) -> None:
        rule = ReasoningRule()
        config = ModelSelectionConfig()
        provider = _provider()
        reasoning_model = _model(
            capabilities=frozenset({ModelCapability.REASONING})
        )
        plain_model = _model(id="plain")

        reasoning_outcome = rule.evaluate(
            provider=provider,
            model=reasoning_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.NORMAL),
            config=config,
            candidate_pool=[],
        )
        plain_outcome = rule.evaluate(
            provider=provider,
            model=plain_model,
            requirements=_requirements(reasoning_level=ReasoningLevel.NORMAL),
            config=config,
            candidate_pool=[],
        )

        # Not excluded, only mildly disadvantaged.
        assert plain_outcome.contribution > reasoning_outcome.contribution
        assert reasoning_outcome.contribution > 0


class TestToolCallingRule:
    def test_not_needed_gives_no_bonus_either_way(self) -> None:
        rule = ToolCallingRule()
        config = ModelSelectionConfig()
        provider = _provider()
        with_tools = _model(
            execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING})
        )
        without_tools = _model(id="no-tools")

        with_outcome = rule.evaluate(
            provider=provider,
            model=with_tools,
            requirements=_requirements(tool_calling=Requirement.NOT_NEEDED),
            config=config,
            candidate_pool=[],
        )
        without_outcome = rule.evaluate(
            provider=provider,
            model=without_tools,
            requirements=_requirements(tool_calling=Requirement.NOT_NEEDED),
            config=config,
            candidate_pool=[],
        )

        assert with_outcome.contribution == without_outcome.contribution

    def test_preferred_rewards_tool_calling_support(self) -> None:
        rule = ToolCallingRule()
        config = ModelSelectionConfig()
        provider = _provider()
        with_tools = _model(
            execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING})
        )
        without_tools = _model(id="no-tools")

        with_outcome = rule.evaluate(
            provider=provider,
            model=with_tools,
            requirements=_requirements(tool_calling=Requirement.PREFERRED),
            config=config,
            candidate_pool=[],
        )
        without_outcome = rule.evaluate(
            provider=provider,
            model=without_tools,
            requirements=_requirements(tool_calling=Requirement.PREFERRED),
            config=config,
            candidate_pool=[],
        )

        assert with_outcome.contribution > without_outcome.contribution


class TestContextWindowRule:
    def test_prefers_larger_context_window(self) -> None:
        rule = ContextWindowRule()
        config = ModelSelectionConfig()
        provider = _provider()
        small = _model(id="small", limits=ModelLimits(context_window=4096))
        large = _model(id="large", limits=ModelLimits(context_window=128000))
        pool = [(provider, small), (provider, large)]

        small_outcome = rule.evaluate(
            provider=provider,
            model=small,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )
        large_outcome = rule.evaluate(
            provider=provider,
            model=large,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )

        assert large_outcome.contribution > small_outcome.contribution


class TestCostRule:
    def test_unreported_cost_scores_as_free(self) -> None:
        rule = CostRule()
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 1.0

    def test_prefers_lower_reported_cost(self) -> None:
        rule = CostRule()
        config = ModelSelectionConfig()
        provider = _provider()
        cheap = _model(id="cheap", metadata={"cost_per_1k_tokens": 0.001})
        expensive = _model(
            id="expensive", metadata={"cost_per_1k_tokens": 0.05}
        )
        pool = [(provider, cheap), (provider, expensive)]

        cheap_outcome = rule.evaluate(
            provider=provider,
            model=cheap,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )
        expensive_outcome = rule.evaluate(
            provider=provider,
            model=expensive,
            requirements=_requirements(),
            config=config,
            candidate_pool=pool,
        )

        assert cheap_outcome.contribution > expensive_outcome.contribution

