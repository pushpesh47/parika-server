"""
PARIKA Planner - Execution Requirements

Defines `ExecutionRequirements`: the provider-independent statement of
*what* a Goal needs from whichever Provider model ultimately executes
it.

`ExecutionRequirements` never names a provider, a model, or any
provider-specific flag. It is Planner's own internal vocabulary for
describing a request's needs before Planner (still, exactly as today,
the sole decision-maker - see `PARIKA_Decision_Flow.md` section 4.4
and `Core_Component_Responsibilities.md`'s ProviderManager "Does NOT"
list) evaluates candidate Provider models against it.

Callers populate requirements through the pre-existing, generic
`Goal.metadata` mapping (no change to `Goal`'s shape) under the
well-known key `"execution_requirements"`, either as an
`ExecutionRequirements` instance or as a plain dict of raw values.
When absent, Planner derives a sensible default purely from the
resolved Capability's category.

Requirements were previously also derivable from a message's text via
Planner's own Requirement Inference framework (pattern/regex rules
over `Goal.inputs["message"]`); that framework has been removed (see
`docs/architecture/Request_Understanding.md`) as part of PARIKA's AI
Context Engineering migration -- semantic understanding of a request
now happens once, in the Interfaces layer, before `Brain.handle()` is
ever called, not by re-guessing intent from text a second time inside
Planner. Callers (see `parika/interfaces/chat_capability.py`
`build_chat_goal()`) that need to influence model selection now supply
an explicit `Goal.metadata["execution_requirements"]` override
instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
import logging

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.resource_manager.models import ResourceSnapshot

from .task_classification import default_task_category_for, get_task_profile

logger = logging.getLogger(__name__)


class ReasoningLevel(StrEnum):
    """
    How much reasoning a Goal is expected to need.
    """

    SIMPLE = "simple"
    NORMAL = "normal"
    COMPLEX = "complex"


class ThinkingMode(StrEnum):
    """
    Resolved preference for whether extended reasoning ("thinking")
    should be requested from the selected model.
    """

    OFF = "off"
    AUTO = "auto"
    ON = "on"


class Requirement(StrEnum):
    """
    Generic three-state requirement level used for optional
    execution features (tool calling, vision, structured output).
    """

    REQUIRED = "required"
    PREFERRED = "preferred"
    NOT_NEEDED = "not_needed"


class LatencyPreference(StrEnum):
    """How strongly latency should influence model selection."""

    LOW = "low"
    NORMAL = "normal"
    RELAXED = "relaxed"


class CreativityLevel(StrEnum):
    """How much creative variation the response should have."""

    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


class AccuracyPreference(StrEnum):
    """Trade-off preference between speed and precision."""

    FAST = "fast"
    BALANCED = "balanced"
    PRECISE = "precise"


class CostPreference(StrEnum):
    """Trade-off preference between cost and quality."""

    CHEAP = "cheap"
    BALANCED = "balanced"
    PREMIUM = "premium"


class DeploymentPreference(StrEnum):
    """Preference for where the selected model should run."""

    LOCAL_ONLY = "local_only"
    CLOUD_ONLY = "cloud_only"
    ANY = "any"


class ExecutionPriority(StrEnum):
    """Relative priority of this Goal's execution."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ImportanceLevel(StrEnum):
    """Generic importance level (used for `memory_importance`)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class InformationFreshness(StrEnum):
    """
    How time-sensitive the information needed to answer a Goal is.

    Populated by a caller's explicit `Goal.metadata
    ["execution_requirements"]` override; never inferred from message
    text inside Planner (see `build_execution_requirements()`'s module
    docstring for why that inference framework was removed).
    """

    STATIC = "static"
    """No live or current information is needed."""

    CURRENT_EVENTS = "current_events"
    """Up-to-date external/world information is needed (news, weather, prices, ...)."""

    REAL_TIME = "real_time"
    """The exact current date/time/clock is needed."""


class CapabilityHint(StrEnum):
    """
    Strongly-typed hint that a specific kind of external capability
    would help satisfy a Goal.

    A closed enum, not an arbitrary string, so nothing inside Planner
    threads free-form identifiers around. Populated only by an
    explicit `Goal.metadata["execution_requirements"]` override
    supplied by a caller (e.g. AI Context Engineering in
    `parika/interfaces/chat_capability.py`) -- Planner itself never
    derives this from message text. Planner never maps a hint to a
    concrete Tool or Provider itself; callers that build tool rosters
    decide which concrete capability, if any, corresponds to a given
    hint.
    """

    CURRENT_DATETIME = "current_datetime"
    """The exact current date/time/clock is needed."""

    LIVE_EXTERNAL_INFORMATION = "live_external_information"
    """Up-to-date external/world information is needed."""

    DOCUMENT_REFERENCE = "document_reference"
    """The request references or asks to act on already-supplied content."""

    NEWS_TOPIC = "news_topic"
    """
    The request asks for the latest headlines/coverage for one of a
    small set of recognized news topics (world, business, technology,
    science, health, politics, sports, entertainment), as opposed to a
    generic web search. Like every other `CapabilityHint`, Planner
    never maps this to `news.topic` itself; it exists so a caller
    supplying an explicit `Goal.metadata["execution_requirements"]`
    override has a typed signal available to express a preference for
    a topic-specific news capability over a generic search.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRequirements:
    """
    Immutable, provider-independent statement of what a Goal needs
    from a Provider model.

    Every field is optional (with a neutral default) except
    `capability`, so building requirements for a Goal that expresses
    no explicit preferences at all still produces a fully valid,
    usable object. New fields may be added over time without breaking
    existing callers, and unrecognized needs can always be carried in
    `metadata`.
    """

    capability: ModelCapability
    """
    The intrinsic AI capability a model must support, derived from the
    resolved Capability's category (see `CATEGORY_TO_MODEL_CAPABILITY`
    in `planner.py`). This is the one hard requirement every
    Provider-routed Goal has.
    """

    reasoning_level: ReasoningLevel = ReasoningLevel.NORMAL
    latency_preference: LatencyPreference = LatencyPreference.NORMAL
    streaming_required: bool = False
    tool_calling: Requirement = Requirement.NOT_NEEDED
    vision: Requirement = Requirement.NOT_NEEDED
    structured_output: Requirement = Requirement.NOT_NEEDED
    creativity: CreativityLevel = CreativityLevel.BALANCED
    min_context_window: int | None = None
    memory_importance: ImportanceLevel = ImportanceLevel.NORMAL
    accuracy_preference: AccuracyPreference = AccuracyPreference.BALANCED
    cost_preference: CostPreference = CostPreference.BALANCED
    deployment_preference: DeploymentPreference = DeploymentPreference.ANY
    execution_priority: ExecutionPriority = ExecutionPriority.NORMAL

    information_freshness: InformationFreshness = InformationFreshness.STATIC
    """
    How time-sensitive the information needed to answer this Goal is.
    See `InformationFreshness`.
    """

    capability_hints: frozenset[CapabilityHint] = field(default_factory=frozenset)
    """
    Strongly-typed hints that a specific kind of external capability
    would help. See `CapabilityHint`.
    """

    capability_id: str = ""
    """
    The resolved Capability's id (e.g. "web.search", "chat.respond").
    Threaded through so a future ScoringRule (e.g. one consulting
    Experience -- see
    docs/architecture/Intelligence_Foundation_Design.md section 6A) can
    look up capability-scoped historical data without Planner needing
    to change. Purely informational; no built-in rule reads it today
    except the optional ExperienceRule.
    """

    task_category: str = ""
    """
    The generic `TaskCategory` (see `task_classification.py`) this
    Goal was classified as, or a caller-supplied custom task category
    string. Purely informational for logging/diagnostics and any
    future capability-scoped rule -- the actual filtering effect of
    task classification is already fully captured by
    `required_specializations`/`required_capabilities`/
    `required_modalities`/`required_execution_features` below.
    """

    required_specializations: frozenset[str] = field(default_factory=frozenset)
    """
    Task Classification's specialization filter (see
    `task_classification.TaskRequirementProfile
    .required_specializations` and `filtering.py`'s specialization
    filtering step). A model satisfies this dimension when it
    advertises no `ProviderModel.specializations` at all (unknown,
    never treated as incompatible), or when its specializations
    intersect this set.
    """

    required_capabilities: frozenset[ModelCapability] = field(
        default_factory=frozenset
    )
    """
    Additional `ModelCapability` values a model must support, beyond
    the single hard-required `capability` above. Unlike
    `required_specializations`, this is never optional metadata: a
    model that does not report one of these capabilities is rejected,
    exactly like the existing single `capability` field.
    """

    required_modalities: frozenset[str] = field(default_factory=frozenset)
    """
    Task Classification's modality filter (see `filtering.py`'s
    modality filtering step). Same graceful-degradation semantics as
    `required_specializations`: a model advertising no
    `ProviderModel.supported_modalities` at all is never rejected on
    this dimension.
    """

    required_execution_features: frozenset[ModelExecutionFeature] = field(
        default_factory=frozenset
    )
    """
    Additional `ModelExecutionFeature` values a model must support,
    beyond the existing `tool_calling`/`structured_output` three-state
    fields. Always a hard requirement when non-empty, exactly like
    `required_capabilities`.
    """

    available_resources: ResourceSnapshot | None = None
    """
    Optional resource snapshot (see `ResourceManager
    .get_resource_snapshot()`) to validate a candidate's declared
    `ProviderModel.resource_requirements` against (`filtering.py`'s
    resource-validation step). `None` (the default) means "no
    snapshot was supplied" - resource validation is skipped entirely
    rather than treated as a rejection, exactly like every other
    optional signal in this framework.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Extension point for future requirement dimensions that do not yet
    warrant a dedicated field. Planner's built-in scoring rules ignore
    this mapping; a future rule may read a well-known key from it
    without requiring any change to this dataclass.
    """

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_hints",
            frozenset(self.capability_hints),
        )
        object.__setattr__(
            self,
            "required_specializations",
            frozenset(self.required_specializations),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(self.required_capabilities),
        )
        object.__setattr__(
            self,
            "required_modalities",
            frozenset(self.required_modalities),
        )
        object.__setattr__(
            self,
            "required_execution_features",
            frozenset(self.required_execution_features),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


_CATEGORY_DEFAULT_REASONING_LEVEL: dict[CapabilityCategory, ReasoningLevel] = {
    CapabilityCategory.REASONING: ReasoningLevel.COMPLEX,
    CapabilityCategory.PLANNING: ReasoningLevel.COMPLEX,
}
"""
Built-in, capability-category-driven default `reasoning_level`. This
is deliberately coarse (most categories default to NORMAL); callers
that know more about a specific Goal should supply an explicit
`reasoning_level` via `Goal.metadata["execution_requirements"]`.
"""

_ENUM_FIELDS: dict[str, type[StrEnum]] = {
    "reasoning_level": ReasoningLevel,
    "latency_preference": LatencyPreference,
    "tool_calling": Requirement,
    "vision": Requirement,
    "structured_output": Requirement,
    "creativity": CreativityLevel,
    "memory_importance": ImportanceLevel,
    "accuracy_preference": AccuracyPreference,
    "cost_preference": CostPreference,
    "deployment_preference": DeploymentPreference,
    "execution_priority": ExecutionPriority,
    "information_freshness": InformationFreshness,
}
"""
Maps each `ExecutionRequirements` field that holds an enum to its enum
type, used to coerce plain strings supplied through
`Goal.metadata["execution_requirements"]` into the correct type.
"""

_PLAIN_FIELDS = (
    "streaming_required",
    "min_context_window",
    "task_category",
)

_FROZENSET_STR_FIELDS = (
    "required_specializations",
    "required_modalities",
)
"""
`ExecutionRequirements` fields holding a `frozenset[str]` of free-form
tags, coerced from any list/tuple/set/frozenset of strings supplied
through `Goal.metadata["execution_requirements"]`.
"""

_FROZENSET_ENUM_FIELDS: dict[str, type[StrEnum]] = {
    "required_capabilities": ModelCapability,
    "required_execution_features": ModelExecutionFeature,
}
"""
`ExecutionRequirements` fields holding a `frozenset` of a specific
enum type, coerced the same way `capability_hints` already is.
"""


def build_execution_requirements(
    *,
    capability: ModelCapability,
    category: CapabilityCategory,
    capability_id: str = "",
    goal_metadata: Mapping[str, Any],
    goal_inputs: Mapping[str, Any] = MappingProxyType({}),
    available_resources: ResourceSnapshot | None = None,
) -> ExecutionRequirements:
    """
    Build the `ExecutionRequirements` for a resolved Goal.

    Precedence, highest first: (1) an explicit
    `Goal.metadata["execution_requirements"]` override, (2) agent
    preferences from `Goal.metadata["agent_id"]`/`Goal.metadata["agent_specialization"]`
    (3) the Task Classification layer's default profile for this Goal's task
    category (see `task_classification.py`), (4) the resolved
    Capability category's default `reasoning_level`. Any field the
    override does not set falls through to its Task Classification or
    category default.

    Agent Preferences (step 2): If the Goal has agent metadata attached
    by the AgentOrchestrator, the agent's preferred models, providers,
    and model constraints are incorporated into the requirements. These
    influence scoring but do not override hard constraints from
    execution_requirements or Task Classification.

    Task Classification (step 3): an explicit `task_category` string
    inside the override takes precedence; otherwise this function
    asks `task_classification.default_task_category_for(category)`
    for a sensible default (e.g. the `LLM` category classifies as
    `general_chat`). Whichever `TaskCategory` (or arbitrary custom
    string) results, `task_classification.get_task_profile()` supplies
    the default `required_specializations`/`required_capabilities`/
    `required_modalities`/`required_execution_features` - the hard
    filtering dimensions `filtering.py`'s pipeline evaluates *before*
    any candidate is scored. This never requires a Planner change to
    support a new task category: an override supplies its own
    `task_category` string, and an unrecognized one still gets a
    sensible generic profile (see `get_task_profile()`).

    Requirements were previously also derivable from a third,
    intermediate layer -- Planner's own Requirement Inference
    framework, a heuristic reading of `Goal.inputs["message"]` via
    pattern/regex rules. That framework has been removed (see this
    module's own docstring and `docs/architecture/
    Request_Understanding.md`): semantic understanding of a request
    now happens once, in the Interfaces layer (AI Context
    Engineering), before `Brain.handle()` is ever called, so a caller
    that needs a specific requirement now supplies it directly via an
    explicit override rather than relying on Planner to re-derive it
    from text a second time. `goal_inputs` is still accepted (Planner
    still forwards `Goal.inputs`) purely so a resolved Goal's message,
    if any, remains available for future, non-text-pattern-based
    signals without changing this function's signature again; no
    built-in logic reads it today.
    """

    override = goal_metadata.get("execution_requirements")

    if isinstance(override, ExecutionRequirements):
        return override

    override_mapping: Mapping[str, Any] = (
        override if isinstance(override, Mapping) else MappingProxyType({})
    )

    # Extract agent preferences from goal metadata
    agent_preferences = {}
    agent_id = goal_metadata.get("agent_id")
    agent_specialization = goal_metadata.get("agent_specialization")
    
    if agent_id is not None:
        agent_preferences["agent_id"] = agent_id
    if agent_specialization is not None:
        agent_preferences["agent_specialization"] = agent_specialization
    
    # Note: Agent model/provider preferences are stored in AgentProfile
    # but AgentOrchestrator doesn't currently pass them through goal metadata.
    # They could be added here if needed in the future.
    # For now, we store the agent identity in metadata for potential future use.

    task_category_value = override_mapping.get("task_category")

    if not (isinstance(task_category_value, str) and task_category_value):
        default_task_category = default_task_category_for(category)
        task_category_value = (
            str(default_task_category) if default_task_category is not None else ""
        )

    profile = get_task_profile(task_category_value) if task_category_value else None

    defaults: dict[str, Any] = {
        "capability": capability,
        "capability_id": capability_id,
        "task_category": task_category_value,
        "reasoning_level": _CATEGORY_DEFAULT_REASONING_LEVEL.get(
            category,
            ReasoningLevel.NORMAL,
        ),
        "available_resources": available_resources,
        "metadata": {"agent_preferences": agent_preferences} if agent_preferences else {},
    }

    if profile is not None:
        defaults["required_specializations"] = profile.required_specializations
        defaults["required_capabilities"] = profile.required_capabilities
        defaults["required_modalities"] = profile.required_modalities
        defaults["required_execution_features"] = (
            profile.required_execution_features
        )

    if isinstance(override, Mapping):
        for key, value in override.items():
            if key == "capability":
                continue

            if key in _ENUM_FIELDS and isinstance(value, str):
                defaults[key] = _ENUM_FIELDS[key](value)
            elif key == "capability_hints" and isinstance(value, (list, tuple, set, frozenset)):
                defaults[key] = frozenset(
                    CapabilityHint(item) if isinstance(item, str) else item
                    for item in value
                )
            elif key in _FROZENSET_STR_FIELDS and isinstance(
                value, (list, tuple, set, frozenset)
            ):
                defaults[key] = frozenset(str(item) for item in value)
            elif key in _FROZENSET_ENUM_FIELDS and isinstance(
                value, (list, tuple, set, frozenset)
            ):
                enum_type = _FROZENSET_ENUM_FIELDS[key]
                defaults[key] = frozenset(
                    enum_type(item) if isinstance(item, str) else item
                    for item in value
                )
            elif (
                key in _ENUM_FIELDS
                or key in _PLAIN_FIELDS
                or key == "capability_hints"
                or key in _FROZENSET_STR_FIELDS
                or key in _FROZENSET_ENUM_FIELDS
            ):
                defaults[key] = value
            elif key == "metadata" and isinstance(value, Mapping):
                # Merge override metadata with agent preferences
                merged_metadata = dict(value)
                if agent_preferences:
                    merged_metadata["agent_preferences"] = agent_preferences
                defaults[key] = merged_metadata

    requirements = ExecutionRequirements(**defaults)

    logger.debug(
        "ExecutionRequirements built: "
        "capability=%s "
        "task_category=%s "
        "required_specializations=%s "
        "required_capabilities=%s "
        "required_modalities=%s "
        "required_execution_features=%s",
        requirements.capability.value,
        requirements.task_category,
        sorted(requirements.required_specializations),
        sorted(value.value for value in requirements.required_capabilities),
        sorted(requirements.required_modalities),
        sorted(value.value for value in requirements.required_execution_features),
    )

    return requirements
