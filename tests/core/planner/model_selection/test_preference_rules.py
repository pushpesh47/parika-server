"""
Unit tests for `parika.core.planner.model_selection.preference_rules`.
"""

from __future__ import annotations

from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.preference_rules import (
    HealthierProviderPreferenceRule,
    LocalDeploymentPreferenceRule,
    StreamingPreferenceRule,
)
from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState


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


class TestLocalDeploymentPreferenceRule:
    def test_bonus_requires_metadata_and_preference(self) -> None:
        rule = LocalDeploymentPreferenceRule()
        provider = _provider()
        local_model = _model(metadata={"deployment_type": "local"})
        cloud_model = _model(id="cloud", metadata={"deployment_type": "cloud"})

        enabled_config = ModelSelectionConfig(
            preferences={"prefer_local": True}
        )
        disabled_config = ModelSelectionConfig(
            preferences={"prefer_local": False}
        )

        assert (
            rule.evaluate(
                provider=provider,
                model=local_model,
                requirements=_requirements(),
                config=enabled_config,
                candidate_pool=[],
            ).contribution
            > 0
        )
        assert (
            rule.evaluate(
                provider=provider,
                model=cloud_model,
                requirements=_requirements(),
                config=enabled_config,
                candidate_pool=[],
            ).contribution
            == 0
        )
        assert (
            rule.evaluate(
                provider=provider,
                model=local_model,
                requirements=_requirements(),
                config=disabled_config,
                candidate_pool=[],
            ).contribution
            == 0
        )


class TestStreamingPreferenceRule:
    def test_bonus_requires_requirement_and_support(self) -> None:
        rule = StreamingPreferenceRule()
        config = ModelSelectionConfig(preferences={"prefer_streaming": True})
        provider = _provider()
        streaming_model = _model(
            execution_features=frozenset({ModelExecutionFeature.STREAMING})
        )

        bonus = rule.evaluate(
            provider=provider,
            model=streaming_model,
            requirements=_requirements(streaming_required=True),
            config=config,
            candidate_pool=[],
        ).contribution
        no_bonus = rule.evaluate(
            provider=provider,
            model=streaming_model,
            requirements=_requirements(streaming_required=False),
            config=config,
            candidate_pool=[],
        ).contribution

        assert bonus > 0
        assert no_bonus == 0


class TestHealthierProviderPreferenceRule:
    def test_bonus_requires_connected_state(self) -> None:
        rule = HealthierProviderPreferenceRule()
        config = ModelSelectionConfig(
            preferences={"prefer_healthier_provider": True}
        )
        connected = _provider(state=ProviderState.CONNECTED)
        disconnected = _provider(state=ProviderState.DISCONNECTED)
        model = _model()

        connected_bonus = rule.evaluate(
            provider=connected,
            model=model,
            requirements=_requirements(),
            config=config,
            candidate_pool=[],
        ).contribution
        disconnected_bonus = rule.evaluate(
            provider=disconnected,
            model=model,
            requirements=_requirements(),
            config=config,
            candidate_pool=[],
        ).contribution

        assert connected_bonus > 0
        assert disconnected_bonus == 0
