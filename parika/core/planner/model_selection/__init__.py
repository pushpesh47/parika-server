"""
PARIKA Planner - Model Selection

Internal implementation of Planner's provider/model selection
strategy: an evolution of the same decision Planner has always made
(see `planner.py`'s `_select_provider_model`), now expressed as
provider-independent `ExecutionRequirements` scored against
configuration-driven, pluggable `ScoringRule` instances.

This subpackage is imported only by `parika.core.planner.planner`.
`ProviderManager` and every other Core component are unaffected by,
and unaware of, its existence - model/provider selection remains
exclusively Planner's responsibility, exactly as documented in
`Core_Component_Responsibilities.md`.
"""

from .config import ModelSelectionConfig, load_model_selection_config
from .evaluation import CandidateEvaluation
from .experience_source import ExperienceSource
from .filtering import evaluate_hard_requirements
from .requirements import (
    AccuracyPreference,
    CapabilityHint,
    CostPreference,
    CreativityLevel,
    DeploymentPreference,
    ExecutionPriority,
    ExecutionRequirements,
    ImportanceLevel,
    InformationFreshness,
    LatencyPreference,
    ReasoningLevel,
    Requirement,
    ThinkingMode,
    build_execution_requirements,
)
from .preference_rules import DEFAULT_PREFERENCE_RULES
from .routing_config import RoutingConfig, load_routing_config
from .routing_strategy import select_fixed_routing_model
from .rules import (
    DEFAULT_WEIGHTED_RULES,
    ExperienceRule,
    RoutingRecommendationRule,
    RuleOutcome,
    ScoringRule,
)
from .selection_result import ModelSelectionResult
from .selector import (
    apply_context_budget,
    apply_reasoning_preference,
    read_estimated_prompt_tokens,
    select_provider_model,
)
from .task_classification import (
    TaskCategory,
    TaskRequirementProfile,
    default_task_category_for,
    get_task_profile,
    register_task_profile,
)

DEFAULT_SCORING_RULES: tuple[ScoringRule, ...] = (
    *DEFAULT_WEIGHTED_RULES,
    *DEFAULT_PREFERENCE_RULES,
)
"""
The built-in rule set used when Planner is not constructed with an
explicit override: every weighted scoring dimension
(`rules.DEFAULT_WEIGHTED_RULES`) followed by every preference bonus
(`preference_rules.DEFAULT_PREFERENCE_RULES`). Embedders may pass a
different sequence of `ScoringRule` instances to
`Planner.__init__(scoring_rules=...)` without changing any Planner or
selector code.
"""

__all__ = [
    "AccuracyPreference",
    "CandidateEvaluation",
    "CapabilityHint",
    "CostPreference",
    "CreativityLevel",
    "DEFAULT_SCORING_RULES",
    "DeploymentPreference",
    "ExecutionPriority",
    "ExecutionRequirements",
    "ExperienceRule",
    "ExperienceSource",
    "ImportanceLevel",
    "InformationFreshness",
    "LatencyPreference",
    "ModelSelectionConfig",
    "ModelSelectionResult",
    "ReasoningLevel",
    "Requirement",
    "RoutingConfig",
    "RoutingRecommendationRule",
    "RuleOutcome",
    "ScoringRule",
    "TaskCategory",
    "TaskRequirementProfile",
    "ThinkingMode",
    "apply_context_budget",
    "apply_reasoning_preference",
    "build_execution_requirements",
    "default_task_category_for",
    "evaluate_hard_requirements",
    "get_task_profile",
    "load_model_selection_config",
    "load_routing_config",
    "read_estimated_prompt_tokens",
    "register_task_profile",
    "select_fixed_routing_model",
    "select_provider_model",
]
