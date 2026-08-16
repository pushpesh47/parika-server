"""
Unit tests for
`parika.core.planner.model_selection.rules.RoutingRecommendationRule`.
"""

from __future__ import annotations

from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.requirements import ExecutionRequirements
from parika.core.planner.model_selection.rules import (
    RoutingRecommendationRule,
    _parse_candidate_model_hints,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel


def _provider(provider_id: str = "provider.test") -> Provider:
    return Provider(id=provider_id, name="Test Provider")


def _model(model_id: str = "model-a") -> ProviderModel:
    return ProviderModel(id=model_id, name=model_id)


def _requirements(**overrides: object) -> ExecutionRequirements:
    defaults: dict[str, object] = {"capability": ModelCapability.TEXT_GENERATION}
    defaults.update(overrides)
    return ExecutionRequirements(**defaults)  # type: ignore[arg-type]


class TestParseCandidateModelHints:
    def test_returns_empty_tuple_for_missing_value(self) -> None:
        assert _parse_candidate_model_hints(None) == ()

    def test_returns_empty_tuple_for_non_list_value(self) -> None:
        assert _parse_candidate_model_hints({"not": "a list"}) == ()

    def test_skips_non_mapping_entries(self) -> None:
        assert _parse_candidate_model_hints(["not-a-dict", 42]) == ()

    def test_skips_entries_missing_provider_or_model_id(self) -> None:
        raw = [
            {"model_id": "model-a"},
            {"provider_id": "provider.test"},
            {"provider_id": "", "model_id": "model-a"},
        ]

        assert _parse_candidate_model_hints(raw) == ()

    def test_parses_well_formed_entries(self) -> None:
        raw = [
            {"provider_id": "provider.test", "model_id": "model-a", "confidence": 0.9},
        ]

        hints = _parse_candidate_model_hints(raw)

        assert len(hints) == 1
        assert hints[0].provider_id == "provider.test"
        assert hints[0].model_id == "model-a"
        assert hints[0].confidence == 0.9

    def test_defaults_confidence_to_one(self) -> None:
        raw = [{"provider_id": "provider.test", "model_id": "model-a"}]

        hints = _parse_candidate_model_hints(raw)

        assert hints[0].confidence == 1.0

    def test_clamps_confidence_to_unit_interval(self) -> None:
        raw = [
            {"provider_id": "provider.test", "model_id": "model-a", "confidence": 5.0},
            {"provider_id": "provider.test", "model_id": "model-b", "confidence": -3.0},
        ]

        hints = _parse_candidate_model_hints(raw)

        assert hints[0].confidence == 1.0
        assert hints[1].confidence == 0.0

    def test_ignores_non_numeric_confidence(self) -> None:
        raw = [
            {
                "provider_id": "provider.test",
                "model_id": "model-a",
                "confidence": "high",
            }
        ]

        hints = _parse_candidate_model_hints(raw)

        assert hints[0].confidence == 1.0

    def test_rejects_boolean_confidence(self) -> None:
        # bool is a subclass of int in Python; a stray `True`/`False`
        # must never silently become confidence 1.0/0.0 through that.
        raw = [{"provider_id": "provider.test", "model_id": "model-a", "confidence": True}]

        hints = _parse_candidate_model_hints(raw)

        assert hints[0].confidence == 1.0  # falls back to the default, not `1.0` from `True`


class TestRoutingRecommendationRule:
    def test_neutral_when_no_hint_supplied(self) -> None:
        rule = RoutingRecommendationRule()
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

        assert outcome.raw_score == 0.5

    def test_neutral_when_hint_does_not_match_this_candidate(self) -> None:
        rule = RoutingRecommendationRule()
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(
                metadata={
                    "candidate_models": [
                        {"provider_id": "provider.other", "model_id": "model-z", "confidence": 1.0}
                    ]
                }
            ),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5

    def test_uses_recommended_confidence_for_matching_candidate(self) -> None:
        rule = RoutingRecommendationRule()
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(
                metadata={
                    "candidate_models": [
                        {
                            "provider_id": provider.id,
                            "model_id": model.id,
                            "confidence": 0.85,
                        }
                    ]
                }
            ),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.85

    def test_only_matching_candidate_is_rewarded_among_several(self) -> None:
        rule = RoutingRecommendationRule()
        config = ModelSelectionConfig()
        provider = _provider()
        recommended = _model("model-a")
        other = _model("model-b")

        requirements = _requirements(
            metadata={
                "candidate_models": [
                    {"provider_id": provider.id, "model_id": "model-a", "confidence": 0.95}
                ]
            }
        )
        pool = [(provider, recommended), (provider, other)]

        recommended_outcome = rule.evaluate(
            provider=provider,
            model=recommended,
            requirements=requirements,
            config=config,
            candidate_pool=pool,
        )
        other_outcome = rule.evaluate(
            provider=provider,
            model=other,
            requirements=requirements,
            config=config,
            candidate_pool=pool,
        )

        assert recommended_outcome.raw_score == 0.95
        assert other_outcome.raw_score == 0.5

    def test_malformed_metadata_degrades_to_neutral(self) -> None:
        rule = RoutingRecommendationRule()
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(metadata={"candidate_models": "not-a-list"}),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5

    def test_default_weight_is_twenty(self) -> None:
        config = ModelSelectionConfig()

        assert config.weight_for("routing_recommendation") == 20.0

    def test_default_weight_can_be_configured(self) -> None:
        config = ModelSelectionConfig(weights={"routing_recommendation": 0.0})

        assert config.weight_for("routing_recommendation") == 0.0

    def test_backward_compatible_when_requirements_carry_no_hint(self) -> None:
        # A request built exactly as it was before this feature
        # existed (no `metadata` override at all) must score
        # identically to the documented "no recommendation" neutral
        # case -- this is the explicit backward-compatibility
        # guarantee for this rule.
        rule = RoutingRecommendationRule()
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=ExecutionRequirements(capability=ModelCapability.TEXT_GENERATION),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5
        assert outcome.contribution == 0.5 * config.weight_for("routing_recommendation")
