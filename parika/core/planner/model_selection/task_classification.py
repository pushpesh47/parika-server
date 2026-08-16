"""
PARIKA Planner - Task Classification

Defines the Task Classification layer of the Model Selection
Framework: the step that turns a resolved Capability's category into
a small, generic statement of *what kind of task* a Goal represents
(`TaskCategory`) and *what a model needs to bring* to be even
considered a candidate for it (`TaskRequirementProfile`).

This module knows nothing about providers, models, or provider-
specific implementations. It never mentions a model name, a provider
name, or a provider-specific capability - only generic, reusable task
vocabulary (`general_chat`, `coding`, `ocr`, `image_generation`, ...).
The examples shipped in `_BUILTIN_TASK_PROFILES` are exactly that -
examples - not an exhaustive or closed list: `register_task_profile()`
lets any future task category be added, by any caller, at any time,
without editing this module, `selector.py`, or `planner.py`; and
`get_task_profile()` falls back to a generic, self-describing profile
for a task category nobody has registered a profile for at all, so an
entirely new, never-seen-before task category *still* participates
correctly in specialization filtering (see `filtering.py`) with zero
code changes anywhere.

Classification here is purely structural - it reads only the already-
resolved `CapabilityCategory` (Planner's existing, frozen concept) and
an optional explicit override carried in `Goal.metadata
["execution_requirements"]["task_category"]` (the same generic
override mechanism `build_execution_requirements()` already uses for
every other requirement dimension - see `requirements.py`). It never
re-parses a message's text; that semantic understanding, when needed,
already happens once in the Interfaces layer (AI Context Engineering)
before `Brain.handle()` is ever called (see `requirements.py`'s module
docstring for why Planner's own text-based inference was removed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)


class TaskCategory(StrEnum):
    """
    Generic, provider-independent classification of what kind of task
    a Goal represents.

    This enum documents the *well-known* task categories the built-in
    `_BUILTIN_TASK_PROFILES` ships default requirement profiles for.
    It is explicitly **not** the only supported set: any caller may
    pass an arbitrary string as a task category (e.g. via `Goal
    .metadata["execution_requirements"]["task_category"]`); see this
    module's docstring and `get_task_profile()`.
    """

    GENERAL_CHAT = "general_chat"
    REASONING = "reasoning"
    CODING = "coding"
    TOOL_USE = "tool_use"
    VISION_UNDERSTANDING = "vision_understanding"
    OCR = "ocr"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDITING = "image_editing"
    VIDEO_UNDERSTANDING = "video_understanding"
    VIDEO_GENERATION = "video_generation"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    TRANSLATION = "translation"
    EMBEDDING = "embedding"
    RERANKING = "reranking"
    PLANNING = "planning"
    MULTIMODAL = "multimodal"
    STRUCTURED_OUTPUT = "structured_output"


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskRequirementProfile:
    """
    Immutable, generic statement of what a `ProviderModel` must bring
    to be a candidate for one `TaskCategory`.

    Every field is a hard (filtering-stage) requirement, evaluated by
    `filtering.py` *before* any candidate is scored - never a ranking
    preference. Every field defaults to empty, so a task category with
    nothing registered for a dimension simply never filters on it.
    """

    task_category: TaskCategory | str
    """The task category this profile describes."""

    required_specializations: frozenset[str] = field(default_factory=frozenset)
    """
    Specialization tags (see `ProviderModel.specializations`) at least
    one of which a model must advertise, *if* it advertises any
    specialization at all. See `filtering.py` for the exact
    graceful-degradation semantics: a model reporting no
    specializations at all is never rejected on this dimension.
    """

    required_capabilities: frozenset[ModelCapability] = field(
        default_factory=frozenset
    )
    """
    Additional `ModelCapability` values a model must support, on top
    of whatever single `ExecutionRequirements.capability` Planner
    already derived from the resolved Capability's category.
    """

    required_modalities: frozenset[str] = field(default_factory=frozenset)
    """
    Modality tags (see `ProviderModel.supported_modalities`) at least
    one of which a model must advertise, *if* it advertises any
    modality at all - the same graceful-degradation semantics as
    `required_specializations`.
    """

    required_execution_features: frozenset[ModelExecutionFeature] = field(
        default_factory=frozenset
    )
    """
    Additional `ModelExecutionFeature` values a model must support
    for this task (e.g. `TOOL_CALLING` for `TOOL_USE`).
    """


_BUILTIN_TASK_PROFILES: dict[str, TaskRequirementProfile] = {
    TaskCategory.GENERAL_CHAT: TaskRequirementProfile(
        task_category=TaskCategory.GENERAL_CHAT,
        required_specializations=frozenset({"general_chat"}),
    ),
    TaskCategory.REASONING: TaskRequirementProfile(
        task_category=TaskCategory.REASONING,
        required_specializations=frozenset({"reasoning"}),
        required_capabilities=frozenset({ModelCapability.REASONING}),
    ),
    TaskCategory.CODING: TaskRequirementProfile(
        task_category=TaskCategory.CODING,
        required_specializations=frozenset({"coding"}),
        required_capabilities=frozenset({ModelCapability.CODING}),
    ),
    TaskCategory.TOOL_USE: TaskRequirementProfile(
        task_category=TaskCategory.TOOL_USE,
        required_specializations=frozenset({"tool_use"}),
        required_execution_features=frozenset(
            {ModelExecutionFeature.TOOL_CALLING}
        ),
    ),
    TaskCategory.VISION_UNDERSTANDING: TaskRequirementProfile(
        task_category=TaskCategory.VISION_UNDERSTANDING,
        required_specializations=frozenset({"vision_understanding"}),
        required_capabilities=frozenset({ModelCapability.VISION}),
        required_modalities=frozenset({"image"}),
    ),
    TaskCategory.OCR: TaskRequirementProfile(
        task_category=TaskCategory.OCR,
        required_specializations=frozenset({"ocr"}),
        required_modalities=frozenset({"image"}),
    ),
    TaskCategory.IMAGE_GENERATION: TaskRequirementProfile(
        task_category=TaskCategory.IMAGE_GENERATION,
        required_specializations=frozenset({"image_generation"}),
        required_capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
        required_modalities=frozenset({"image"}),
    ),
    TaskCategory.IMAGE_EDITING: TaskRequirementProfile(
        task_category=TaskCategory.IMAGE_EDITING,
        required_specializations=frozenset({"image_editing"}),
        required_capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
        required_modalities=frozenset({"image"}),
    ),
    TaskCategory.VIDEO_UNDERSTANDING: TaskRequirementProfile(
        task_category=TaskCategory.VIDEO_UNDERSTANDING,
        required_specializations=frozenset({"video_understanding"}),
        required_modalities=frozenset({"video"}),
    ),
    TaskCategory.VIDEO_GENERATION: TaskRequirementProfile(
        task_category=TaskCategory.VIDEO_GENERATION,
        required_specializations=frozenset({"video_generation"}),
        required_capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
        required_modalities=frozenset({"video"}),
    ),
    TaskCategory.SPEECH_TO_TEXT: TaskRequirementProfile(
        task_category=TaskCategory.SPEECH_TO_TEXT,
        required_specializations=frozenset({"speech_to_text"}),
        required_capabilities=frozenset({ModelCapability.SPEECH_TO_TEXT}),
        required_modalities=frozenset({"audio"}),
    ),
    TaskCategory.TEXT_TO_SPEECH: TaskRequirementProfile(
        task_category=TaskCategory.TEXT_TO_SPEECH,
        required_specializations=frozenset({"text_to_speech"}),
        required_capabilities=frozenset({ModelCapability.TEXT_TO_SPEECH}),
        required_modalities=frozenset({"audio"}),
    ),
    TaskCategory.TRANSLATION: TaskRequirementProfile(
        task_category=TaskCategory.TRANSLATION,
        required_specializations=frozenset({"translation"}),
        required_capabilities=frozenset({ModelCapability.TRANSLATION}),
    ),
    TaskCategory.EMBEDDING: TaskRequirementProfile(
        task_category=TaskCategory.EMBEDDING,
        required_specializations=frozenset({"embedding"}),
        required_capabilities=frozenset({ModelCapability.EMBEDDING}),
    ),
    TaskCategory.RERANKING: TaskRequirementProfile(
        task_category=TaskCategory.RERANKING,
        required_specializations=frozenset({"reranking"}),
        required_capabilities=frozenset({ModelCapability.RERANKING}),
    ),
    TaskCategory.PLANNING: TaskRequirementProfile(
        task_category=TaskCategory.PLANNING,
        required_specializations=frozenset({"planning"}),
    ),
    TaskCategory.MULTIMODAL: TaskRequirementProfile(
        task_category=TaskCategory.MULTIMODAL,
        required_specializations=frozenset({"multimodal"}),
        required_execution_features=frozenset(
            {ModelExecutionFeature.MULTIMODAL_INPUT}
        ),
    ),
    TaskCategory.STRUCTURED_OUTPUT: TaskRequirementProfile(
        task_category=TaskCategory.STRUCTURED_OUTPUT,
        required_specializations=frozenset({"structured_output"}),
        required_execution_features=frozenset(
            {ModelExecutionFeature.STRUCTURED_OUTPUT}
        ),
    ),
}
"""
Default requirement profiles for every well-known `TaskCategory`.
Purely example data, keyed by the enum's own string value - adding a
new *well-known* task category means adding one more entry here (a
data change, not a change to any filtering/selection/Planner logic);
adding a never-seen-before task category requires no change at all,
anywhere, since `get_task_profile()` synthesizes a sensible generic
profile for it.
"""

_registered_task_profiles: dict[str, TaskRequirementProfile] = {}
"""
Task profiles registered at runtime via `register_task_profile()`,
layered *over* `_BUILTIN_TASK_PROFILES`. Kept separate from the
built-in table so callers can always tell which profiles are this
module's own examples versus externally contributed ones.
"""

_CATEGORY_TASK_DEFAULTS: dict[CapabilityCategory, TaskCategory] = {
    CapabilityCategory.LLM: TaskCategory.GENERAL_CHAT,
    CapabilityCategory.REASONING: TaskCategory.REASONING,
    CapabilityCategory.PLANNING: TaskCategory.PLANNING,
    CapabilityCategory.VISION: TaskCategory.VISION_UNDERSTANDING,
    CapabilityCategory.OCR: TaskCategory.OCR,
    CapabilityCategory.EMBEDDING: TaskCategory.EMBEDDING,
    CapabilityCategory.TRANSLATION: TaskCategory.TRANSLATION,
    CapabilityCategory.SPEECH: TaskCategory.SPEECH_TO_TEXT,
    CapabilityCategory.TEXT_TO_SPEECH: TaskCategory.TEXT_TO_SPEECH,
    CapabilityCategory.IMAGE_GENERATION: TaskCategory.IMAGE_GENERATION,
    CapabilityCategory.VIDEO_GENERATION: TaskCategory.VIDEO_GENERATION,
}
"""
Default `CapabilityCategory -> TaskCategory` derivation, used only
when a caller did not supply an explicit `task_category` override.
Every category present here is also present in Planner's own
`CATEGORY_TO_MODEL_CAPABILITY` (`planner.py`) - this table only ever
*refines* an already-routable category with a richer task
classification; it never changes which categories are routable to a
Provider at all (that remains Planner's unmodified responsibility).
"""


def register_task_profile(profile: TaskRequirementProfile) -> None:
    """
    Register (or override) the `TaskRequirementProfile` used for one
    task category.

    This is the extension point that lets a brand new task category -
    or a project-specific refinement of a built-in one - be added at
    any time, from anywhere (a Module, an Interfaces-layer component,
    application start-up code, ...), without editing this module,
    `filtering.py`, `selector.py`, or `planner.py`. Registering the
    same `task_category` twice replaces the previous profile.
    """

    _registered_task_profiles[str(profile.task_category)] = profile


def get_task_profile(task_category: TaskCategory | str) -> TaskRequirementProfile:
    """
    Return the `TaskRequirementProfile` for a task category.

    Resolution order: an explicitly `register_task_profile()`-ed
    profile, then a built-in example profile, then a generic,
    synthesized fallback that requires the model to advertise a
    specialization equal to the task category's own name - so a
    completely unrecognized task category still participates
    correctly in specialization filtering (see `filtering.py`)
    instead of silently matching every candidate.
    """

    key = str(task_category)

    if key in _registered_task_profiles:
        return _registered_task_profiles[key]

    if key in _BUILTIN_TASK_PROFILES:
        return _BUILTIN_TASK_PROFILES[key]

    return TaskRequirementProfile(
        task_category=task_category,
        required_specializations=frozenset({key}) if key else frozenset(),
    )


def default_task_category_for(
    category: CapabilityCategory,
) -> TaskCategory | None:
    """
    Return the default `TaskCategory` for a resolved
    `CapabilityCategory`, or `None` when this layer has no built-in
    opinion for it (the caller falls back to no task classification
    at all - identical to this framework's behavior before Task
    Classification existed).
    """

    return _CATEGORY_TASK_DEFAULTS.get(category)
