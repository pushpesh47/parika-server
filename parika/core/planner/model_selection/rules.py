"""
PARIKA Planner - Model Selection Scoring Rules

Defines the `ScoringRule` interface and every built-in scoring rule.

Rather than accumulating an ever-growing set of standalone
`score_*()` functions that the selector must know about individually,
each scoring dimension (and each boolean preference) is a small,
independently testable `ScoringRule` implementation. `selector.py`
only ever iterates over a *sequence* of `ScoringRule` instances - it
never inspects which concrete rules are present. Adding a new scoring
dimension (for example, a future `ProviderReliabilityRule`) means
writing one new class and adding it to the rule sequence Planner is
constructed with; the selector's orchestration code never changes.

Every rule reads only from `ExecutionRequirements` (provider-
independent, supplied by Planner) and from `ProviderModel`/`Provider`
metadata (provider-reported, never hardcoded). No rule here ever
mentions a specific provider or model name.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel

from .config import ModelSelectionConfig
from .experience_source import ExperienceSource
from .requirements import ExecutionRequirements, ReasoningLevel, Requirement
import logging

logger = logging.getLogger(__name__)
Candidate = tuple[Provider, ProviderModel]


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleOutcome:
    """
    Immutable outcome of a single `ScoringRule` evaluating a single
    candidate.
    """

    rule_id: str
    """Identifier of the rule that produced this outcome."""

    contribution: float
    """
    Net amount this rule adds to the candidate's total score. May be
    a weighted, normalized sub-score (`raw_score * weight`) or a flat
    preference bonus/penalty.
    """

    raw_score: float | None = None
    """Normalized [0, 1] sub-score, when this rule computes one."""

    weight: float | None = None
    """Configured weight applied, when this rule is weight-driven."""

    note: str = ""
    """Short, human-readable explanation, for transparency/logging."""


class ScoringRule(ABC):
    """
    A single, independently pluggable scoring dimension or
    preference.

    Concrete rules are stateless and side-effect free: `evaluate()` is
    a pure function of its arguments.
    """

    id: str
    """
    Stable identifier for this rule. Matches the corresponding
    `[model_selection.weights]` or `[model_selection.preferences]`
    configuration key when one exists.
    """

    @abstractmethod
    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        """
        Evaluate one candidate.

        Args:
            provider:
                The candidate's Provider.

            model:
                The candidate's ProviderModel.

            requirements:
                The Goal's ExecutionRequirements.

            config:
                The active ModelSelectionConfig.

            candidate_pool:
                Every candidate still under consideration (post
                hard-requirement filtering), for rules that need to
                normalize relative to their peers (e.g. latency,
                context window).

        Returns:
            This rule's RuleOutcome for the candidate.
        """


def _normalize_lower_is_better(
    value: float | None,
    values: Sequence[float],
) -> float:
    """
    Normalize `value` to [0, 1] within `values`, where the lowest
    value scores 1.0 and the highest scores 0.0. Returns a neutral
    0.5 when `value` is unknown or every value is equal.
    """

    if value is None or not values:
        return 0.5

    lowest, highest = min(values), max(values)

    if highest == lowest:
        return 1.0

    return 1.0 - ((value - lowest) / (highest - lowest))


def _numeric_metadata(model: ProviderModel, key: str) -> float | None:
    """
    Read a numeric value from `model.metadata`, or `None` if absent
    or not a number.
    """

    value = model.metadata.get(key)

    if isinstance(value, (int, float)):
        return float(value)

    return None


def _normalize_higher_is_better(
    value: float | None,
    values: Sequence[float],
) -> float:
    """
    Normalize `value` to [0, 1] within `values`, where the highest
    value scores 1.0 and the lowest scores 0.0. Returns a neutral
    0.5 when `value` is unknown or every value is equal.
    """

    if value is None or not values:
        return 0.5

    lowest, highest = min(values), max(values)

    if highest == lowest:
        return 1.0

    return (value - lowest) / (highest - lowest)


class LatencyRule(ScoringRule):
    """
    Rewards lower estimated latency, relative to every other
    candidate under consideration.

    Reads the well-known `estimated_latency_ms` key from
    `ProviderModel.metadata`, when a provider chooses to report it.
    Contributes a neutral score for every candidate when no candidate
    reports it, rather than favoring or penalizing anyone.
    """

    id = "latency"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        values = [
            value
            for _, candidate_model in candidate_pool
            if (value := _numeric_metadata(candidate_model, "estimated_latency_ms"))
            is not None
        ]

        latency = _numeric_metadata(model, "estimated_latency_ms")
        raw_score = _normalize_lower_is_better(latency, values)
        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"estimated_latency_ms={latency}"
                if latency is not None
                else "no latency estimate reported"
            ),
        )


class ReasoningRule(ScoringRule):
    """
    Rewards or penalizes a model's reasoning capability based on how
    much reasoning the Goal actually needs.

    A COMPLEX Goal favors reasoning-capable models. A SIMPLE Goal
    strongly favors models *without* a heavy reasoning capability. A
    NORMAL Goal - the common case for everyday chat - still mildly
    favors non-reasoning models, since reasoning-tuned models
    routinely spend significant extra time "thinking" even when a
    request does not warrant it, which is precisely the "reasoning
    models used unnecessarily" problem this framework exists to
    address; it is not a hard exclusion, since a reasoning-capable
    model remains an entirely reasonable general-purpose choice when
    it is otherwise clearly the best fit (e.g. only candidate, or far
    ahead on other dimensions).
    """

    id = "reasoning"

    _COMPLEX_SCORES = {True: 1.0, False: 0.3}
    _NORMAL_SCORES = {True: 0.8, False: 1.0}
    _SIMPLE_SCORES = {True: 0.5, False: 1.0}

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        supports_reasoning = ModelCapability.REASONING in model.capabilities

        logger.debug(
            "ReasoningRule: "
            "model=%s "
            "reasoning_level=%s "
            "capabilities=%s "
            "supports_reasoning=%s",
            model.id,
            requirements.reasoning_level.value,
            sorted(capability.value for capability in model.capabilities),
            ModelCapability.REASONING in model.capabilities,
        )

        if requirements.reasoning_level is ReasoningLevel.COMPLEX:
            raw_score = self._COMPLEX_SCORES[supports_reasoning]
        elif requirements.reasoning_level is ReasoningLevel.SIMPLE:
            raw_score = self._SIMPLE_SCORES[supports_reasoning]
        else:
            raw_score = self._NORMAL_SCORES[supports_reasoning]

        weight = config.weight_for(self.id)

        logger.debug(
            "ReasoningRule Result: "
            "model=%s "
            "raw_score=%.2f "
            "weight=%.2f "
            "contribution=%.2f",
            model.id,
            raw_score,
            weight,
            raw_score * weight,
        )

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"reasoning_level={requirements.reasoning_level.value} "
                f"supports_reasoning={supports_reasoning}"
            ),
        )


class ToolCallingRule(ScoringRule):
    """
    Rewards tool-calling support when the Goal prefers it. Contributes
    no bonus when tool calling is not needed (candidates missing a
    REQUIRED tool-calling capability are already excluded before
    scoring by `filtering.py`).
    """

    id = "tool_calling"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        supports_tools = (
            ModelExecutionFeature.TOOL_CALLING in model.execution_features
        )

        if requirements.tool_calling is Requirement.NOT_NEEDED:
            raw_score = 1.0
        else:
            raw_score = 1.0 if supports_tools else 0.5

        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=f"tool_calling={requirements.tool_calling.value} supports_tools={supports_tools}",
        )


class ContextWindowRule(ScoringRule):
    """
    Rewards a larger context window, relative to every other
    candidate under consideration.
    """

    id = "context_window"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        values = [
            float(candidate_model.limits.context_window)
            for _, candidate_model in candidate_pool
            if candidate_model.limits.context_window is not None
        ]

        context_window = model.limits.context_window
        raw_score = _normalize_higher_is_better(
            float(context_window) if context_window is not None else None,
            values,
        )
        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"context_window={context_window}"
                if context_window is not None
                else "no context window reported"
            ),
        )


class CostRule(ScoringRule):
    """
    Rewards lower cost, relative to every other candidate under
    consideration.

    Reads the well-known `cost_per_1k_tokens` key from
    `ProviderModel.metadata`. Local providers that never report a cost
    score as free (1.0); this dimension only differentiates once a
    cost-reporting provider is registered.
    """

    id = "cost"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        cost = _numeric_metadata(model, "cost_per_1k_tokens")

        if cost is None:
            raw_score = 1.0
        else:
            values = [
                value
                for _, candidate_model in candidate_pool
                if (
                    value := _numeric_metadata(
                        candidate_model, "cost_per_1k_tokens"
                    )
                )
                is not None
            ]
            raw_score = _normalize_lower_is_better(cost, values)

        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"cost_per_1k_tokens={cost}" if cost is not None else "free/local"
            ),
        )


class ExperienceRule(ScoringRule):
    """
    Rewards a provider/model with a higher historical success rate for
    this Goal's capability, as reported by an injected
    `ExperienceSource` (see
    docs/architecture/Intelligence_Foundation_Design.md section 6A).

    Contributes a neutral 0.5 raw score -- not a penalty -- whenever no
    `ExperienceSource` was supplied, or it has no data yet for this
    capability/provider/model, exactly like every other rule degrades
    when its metadata is absent. This rule is opt-in: it ships in
    `DEFAULT_WEIGHTED_RULES` but its default `[model_selection.weights]
    experience` weight is `0.0` until an operator explicitly enables
    it, per the design's conservative-rollout decision.
    """

    id = "experience"

    def __init__(self, experience_source: ExperienceSource | None = None) -> None:
        self._experience_source = experience_source

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        rate: float | None = None

        if self._experience_source is not None and requirements.capability_id:
            try:
                rate = self._experience_source.aggregate_outcome_rate(
                    capability_id=requirements.capability_id,
                    provider_id=provider.id,
                    model_id=model.id,
                )
            except Exception:
                # Never let an unavailable/uninitialized Experience
                # backend break planning -- degrade to neutral, exactly
                # like an absent ProviderModel.metadata key.
                rate = None

        raw_score = rate if rate is not None else 0.5
        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"historical_success_rate={rate}"
                if rate is not None
                else "no experience data reported"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _CandidateModelHint:
    """
    One routing-model-recommended candidate for *this specific
    request*, parsed from `ExecutionRequirements.metadata
    ["candidate_models"]` (see `RoutingRecommendationRule`).

    Deliberately private and unexported: this is a scoring-rule-local
    parsing convenience, never a first-class part of
    `ExecutionRequirements`'s own shape -- a recommendation is not a
    requirement (see `ExecutionRequirements.metadata`'s own
    docstring, the extension point this rule reads from).
    """

    provider_id: str
    model_id: str
    confidence: float = 1.0


def _parse_candidate_model_hints(raw: object) -> tuple[_CandidateModelHint, ...]:
    """
    Defensively parse `ExecutionRequirements.metadata
    ["candidate_models"]` into `_CandidateModelHint` instances.

    Never raises: any missing, malformed, or partially-malformed
    entry is simply skipped, exactly like every other optional signal
    in this framework (e.g. `ExperienceRule`'s own defensive
    degrade-to-neutral posture). Returns an empty tuple when `raw` is
    absent or not a list/tuple at all -- the common case for a
    request with no routing recommendation.
    """

    if not isinstance(raw, (list, tuple)):
        return ()

    hints: list[_CandidateModelHint] = []

    for item in raw:
        if not isinstance(item, Mapping):
            continue

        provider_id = item.get("provider_id")
        model_id = item.get("model_id")

        if not isinstance(provider_id, str) or not provider_id:
            continue

        if not isinstance(model_id, str) or not model_id:
            continue

        confidence = item.get("confidence", 1.0)

        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            confidence = 1.0

        hints.append(
            _CandidateModelHint(
                provider_id=provider_id,
                model_id=model_id,
                confidence=max(0.0, min(1.0, float(confidence))),
            )
        )

    return tuple(hints)


class RoutingRecommendationRule(ScoringRule):
    """
    Rewards a candidate the routing model explicitly recommended for
    *this specific request*, as an optional, per-turn semantic signal
    layered on top of every other, provider-metadata-driven scoring
    dimension (latency, cost, context window, experience, ...).

    This is the AI-assisted model-selection refinement: deterministic
    filtering/scoring alone cannot semantically distinguish between
    two models that advertise the same specialization (e.g. two
    Vision-capable models); a routing model that has actually read
    the current request's content can recommend which of them fits
    *this* request better. That recommendation is read here purely as
    one more scored signal -- it can never select a candidate that
    `filtering.py` already rejected, and it never bypasses any other
    rule.

    Reads `requirements.metadata["candidate_models"]` -- deliberately
    not a first-class `ExecutionRequirements` field, since a
    recommendation is not a requirement (see `ExecutionRequirements
    .metadata`'s own docstring). Contributes a neutral 0.5 raw score
    -- never a penalty -- for every candidate whenever no hint was
    supplied at all, or none matches a given candidate, so a request
    carrying no routing recommendation behaves identically to before
    this rule existed (backward compatible by construction).
    """

    id = "routing_recommendation"

    def evaluate(
        self,
        *,
        provider: Provider,
        model: ProviderModel,
        requirements: ExecutionRequirements,
        config: ModelSelectionConfig,
        candidate_pool: Sequence[Candidate],
    ) -> RuleOutcome:
        hints = _parse_candidate_model_hints(
            requirements.metadata.get("candidate_models")
        )

        matched = next(
            (
                hint
                for hint in hints
                if hint.provider_id == provider.id and hint.model_id == model.id
            ),
            None,
        )

        raw_score = matched.confidence if matched is not None else 0.5
        weight = config.weight_for(self.id)

        return RuleOutcome(
            rule_id=self.id,
            contribution=raw_score * weight,
            raw_score=raw_score,
            weight=weight,
            note=(
                f"routing_recommended_confidence={matched.confidence:.2f}"
                if matched is not None
                else "no routing recommendation for this candidate"
            ),
        )


DEFAULT_WEIGHTED_RULES: tuple[ScoringRule, ...] = (
    LatencyRule(),
    ReasoningRule(),
    ToolCallingRule(),
    ContextWindowRule(),
    CostRule(),
    ExperienceRule(),
    RoutingRecommendationRule(),
)
"""
The built-in weighted scoring dimensions. Combined with
`preference_rules.DEFAULT_PREFERENCE_RULES` to form
`DEFAULT_SCORING_RULES` (see `__init__.py`). `ExperienceRule` ships
with no `ExperienceSource` by default (neutral no-op) -- Planner wires
a real one only when `experience_source` is supplied to its
constructor (see `planner.py`). `RoutingRecommendationRule` similarly
degrades to a neutral no-op whenever no routing recommendation was
supplied for a given request (see its own docstring).
"""
