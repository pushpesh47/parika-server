"""
PARIKA Planner - Preference-Based Scoring Rules

Defines the built-in `ScoringRule` implementations backing
`[model_selection.preferences]`: small, flat bonuses (rather than
weighted, normalized sub-scores) contributed when a boolean preference
is enabled and satisfied. Kept in a separate module from
`rules.py`'s weighted scoring dimensions purely to keep each file
focused (see `PARIKA_Core_Coding_Standards.md` - File Size
Guidelines); every rule here still implements the exact same
`ScoringRule` interface, and `selector.py` never distinguishes between
the two kinds.
"""

from __future__ import annotations

from collections.abc import Sequence

from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState

from .config import ModelSelectionConfig
from .requirements import ExecutionRequirements
from .rules import Candidate, RuleOutcome, ScoringRule


class LocalDeploymentPreferenceRule(ScoringRule):
    """
    Bonus for models reported as running locally, when
    `prefer_local` is enabled.

    Reads the well-known `deployment_type` key from
    `ProviderModel.metadata` (expected value: `"local"` or
    `"cloud"`); contributes nothing when unreported.
    """

    id = "prefer_local"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        is_local = model.metadata.get("deployment_type") == "local"
        bonus = (
            config.preference_bonus_magnitude
            if config.prefers(self.id) and is_local
            else 0.0
        )

        return RuleOutcome(
            rule_id=self.id,
            contribution=bonus,
            note=f"deployment_type={model.metadata.get('deployment_type')}",
        )


class StreamingPreferenceRule(ScoringRule):
    """
    Bonus for streaming-capable models when the Goal requires or
    prefers streaming and `prefer_streaming` is enabled.
    """

    id = "prefer_streaming"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        supports_streaming = (
            ModelExecutionFeature.STREAMING in model.execution_features
        )
        bonus = (
            config.preference_bonus_magnitude
            if config.prefers(self.id)
            and requirements.streaming_required
            and supports_streaming
            else 0.0
        )

        return RuleOutcome(
            rule_id=self.id,
            contribution=bonus,
            note=f"supports_streaming={supports_streaming}",
        )


class HealthierProviderPreferenceRule(ScoringRule):
    """
    Bonus for a Provider currently in the CONNECTED state, when
    `prefer_healthier_provider` is enabled.
    """

    id = "prefer_healthier_provider"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        is_connected = provider.state is ProviderState.CONNECTED
        bonus = (
            config.preference_bonus_magnitude
            if config.prefers(self.id) and is_connected
            else 0.0
        )

        return RuleOutcome(
            rule_id=self.id,
            contribution=bonus,
            note=f"provider_state={provider.state.value}",
        )


DEFAULT_PREFERENCE_RULES: tuple[ScoringRule, ...] = (
    LocalDeploymentPreferenceRule(),
    StreamingPreferenceRule(),
    HealthierProviderPreferenceRule(),
)
