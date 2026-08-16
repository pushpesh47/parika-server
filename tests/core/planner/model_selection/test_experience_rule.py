"""
Unit tests for `parika.core.planner.model_selection.rules.ExperienceRule`.
"""

from __future__ import annotations

from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.requirements import ExecutionRequirements
from parika.core.planner.model_selection.rules import ExperienceRule
from parika.core.provider_manager.model_capability import ModelCapability
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


class _FakeExperienceSource:
    def __init__(self, rate: float | None = None, *, raises: bool = False) -> None:
        self.rate = rate
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    def aggregate_outcome_rate(
        self, *, capability_id: str, provider_id: str | None = None, model_id: str | None = None
    ) -> float | None:
        self.calls.append(
            {"capability_id": capability_id, "provider_id": provider_id, "model_id": model_id}
        )

        if self.raises:
            raise RuntimeError("backend unavailable")

        return self.rate


class TestExperienceRule:
    def test_neutral_when_no_source_configured(self) -> None:
        rule = ExperienceRule(None)
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(capability_id="web.search"),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5

    def test_neutral_when_capability_id_missing(self) -> None:
        source = _FakeExperienceSource(rate=0.9)
        rule = ExperienceRule(source)
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(),  # capability_id defaults to ""
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5
        assert source.calls == []

    def test_uses_reported_rate(self) -> None:
        source = _FakeExperienceSource(rate=0.8)
        rule = ExperienceRule(source)
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(capability_id="web.search"),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.8
        assert source.calls == [
            {"capability_id": "web.search", "provider_id": "provider.test", "model_id": "model-a"}
        ]

    def test_neutral_when_no_data_reported(self) -> None:
        source = _FakeExperienceSource(rate=None)
        rule = ExperienceRule(source)
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(capability_id="web.search"),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5

    def test_degrades_gracefully_when_source_raises(self) -> None:
        source = _FakeExperienceSource(raises=True)
        rule = ExperienceRule(source)
        config = ModelSelectionConfig()
        provider = _provider()
        model = _model()

        outcome = rule.evaluate(
            provider=provider,
            model=model,
            requirements=_requirements(capability_id="web.search"),
            config=config,
            candidate_pool=[(provider, model)],
        )

        assert outcome.raw_score == 0.5

    def test_default_weight_is_zero(self) -> None:
        config = ModelSelectionConfig()

        assert config.weight_for("experience") == 0.0

    def test_default_weight_can_be_configured(self) -> None:
        config = ModelSelectionConfig(weights={"experience": 15.0})

        assert config.weight_for("experience") == 15.0
