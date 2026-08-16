"""
PARIKA AI Context Engineering - Worker Model Inventory

Owns ONLY rendering a compact, semantic, per-turn inventory of every
other installed AI model, for a routing model's own reasoning about
which candidate worker model(s) it should recommend for a downstream,
Provider-backed task (see `parika/interfaces/ai_context
/model_selection_policy.py` for the generic instruction text that
tells the routing model this inventory exists and how it may act on
it).

Built entirely from already-normalized, already-in-memory runtime
objects (`Provider`/`ProviderModel`, see
`parika/core/provider_manager/`) -- never performs, or requires, any
additional provider API call (no `/api/tags`, no `/api/show`). This
module owns zero provider-specific knowledge: every field it reads
already exists on the generic `Provider`/`ProviderModel` domain
objects the Model Selection Framework itself already consumes.

Self-exclusion (excluding the model that will actually handle this
turn) is achieved by the *caller* passing that exact, already-selected
`ProviderModel` instance as `exclude` -- see `goal_builder
._build_provider_request()`, which calls this module only after
Planner has already selected the routing model (i.e. from inside the
`provider_request_builder` closure Planner invokes at
`planner.py:676`, strictly after model selection at `planner.py:666-
667`). This module itself never selects, ranks, or filters a model for
execution purposes -- it only decides how to describe candidates that
already exist, exactly like `api/handlers/providers.py`'s own
`{id, capabilities}` REST reduction already does for a different
audience.

Two, deliberately separate kinds of information are rendered per
model, and are never merged together (see
`parika/core/semantics/model_knowledge.py`'s own docstring for the
same distinction at the data layer):

1. Objective provider facts -- `ProviderModel`'s own normalized
   fields (capabilities, modalities, execution features, context
   window, resource requirements, provider-reported description).
2. PARIKA Model Knowledge -- PARIKA's own observed knowledge about a
   model's real-world strengths (`parika.core.semantics
   .model_knowledge.get_model_knowledge()`), explicitly labeled as
   PARIKA's own observation, never presented as if it were a
   provider-reported fact.
"""

from __future__ import annotations

from collections.abc import Sequence

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_resource_requirements import (
    ModelResourceRequirements,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.semantics.model_knowledge import get_model_knowledge

_HEADER = (
    "Other AI models currently installed and available for "
    "specialized, Provider-backed tasks (the model handling this "
    "conversation turn is excluded from this list):"
)


def render_worker_inventory(
    providers: Sequence[Provider],
    *,
    exclude: ProviderModel | None = None,
) -> str:
    """
    Render the compact worker model inventory text block.

    Args:
        providers:
            Every registered `Provider` (typically
            `ProviderManager.get_all()`, a zero-I/O, already-cached
            read).

        exclude:
            The `ProviderModel` to omit from the rendered inventory --
            the model already selected to handle this turn. `None`
            renders every model (used only when no exclusion is
            known/desired, e.g. by a caller other than the routing
            Goal's own `provider_request_builder`).

    Returns:
        The rendered text block, or an empty string when there are no
        other models to describe (e.g. a single-model install, or
        every provider reporting zero models) -- an empty string is
        never injected as a message by any caller.
    """

    lines: list[str] = []

    for provider in providers:
        for model in provider.models:
            if exclude is not None and model == exclude:
                continue

            lines.append(_render_model_entry(provider, model))

    if not lines:
        return ""

    return _HEADER + "\n" + "\n".join(lines)


def _render_model_entry(provider: Provider, model: ProviderModel) -> str:
    facts = _render_provider_facts(provider, model)
    knowledge = _render_parika_knowledge(model)

    entry = f"- {provider.id}/{model.id} :: {facts}"

    if knowledge:
        entry += f"\n  {knowledge}"

    return entry


def _render_provider_facts(provider: Provider, model: ProviderModel) -> str:
    """
    Render every *objective provider fact* segment for one model,
    omitting any segment whose underlying field is unreported/empty
    (never a placeholder like `"none"`/`"null"`) -- the same graceful-
    degradation contract the Model Selection Framework itself already
    applies to these exact fields (see `filtering.py`/`rules.py`).
    """

    segments: list[str] = []

    if model.capabilities:
        segments.append(
            "capabilities: " + ", ".join(sorted(value.value for value in model.capabilities))
        )

    if model.specializations:
        segments.append(
            "specializations: " + ", ".join(sorted(model.specializations))
        )

    if model.supported_modalities:
        segments.append(
            "modalities: " + ", ".join(sorted(model.supported_modalities))
        )

    segments.append(
        "thinking_support: "
        + _yes_no(ModelCapability.REASONING in model.capabilities)
    )
    segments.append(
        "tool_calling: "
        + _yes_no(ModelExecutionFeature.TOOL_CALLING in model.execution_features)
    )
    segments.append(
        "structured_output: "
        + _yes_no(ModelExecutionFeature.STRUCTURED_OUTPUT in model.execution_features)
    )
    segments.append(
        "streaming: "
        + _yes_no(ModelExecutionFeature.STREAMING in model.execution_features)
    )

    if model.limits.context_window is not None:
        segments.append(f"context_window: {model.limits.context_window}")

    resources = _render_resource_requirements(model.resource_requirements)

    if resources:
        segments.append(f"resources: {resources}")

    if model.description:
        segments.append(f"description: {model.description}")

    return " | ".join(segments)


def _render_parika_knowledge(model: ProviderModel) -> str:
    """
    Render PARIKA's own observed knowledge about this model, clearly
    labeled as PARIKA's own observation -- never merged with, or
    described as, a provider-reported fact (see this module's own
    docstring and `model_knowledge.py`'s docstring for why this
    distinction is mandatory).

    Returns an empty string when PARIKA has no observed knowledge
    about this model, or when the knowledge entry declares no
    strengths -- never a placeholder.
    """

    entry = get_model_knowledge(model.id)

    if entry is None or not entry.strengths:
        return ""

    return "PARIKA observed knowledge (not provider-reported): " + ", ".join(
        sorted(entry.strengths)
    )


def _render_resource_requirements(
    requirements: ModelResourceRequirements,
) -> str:
    parts: list[str] = []

    if requirements.min_ram_bytes is not None:
        parts.append(f"min_ram_bytes={requirements.min_ram_bytes}")

    if requirements.min_vram_bytes is not None:
        parts.append(f"min_vram_bytes={requirements.min_vram_bytes}")

    if requirements.min_disk_bytes is not None:
        parts.append(f"min_disk_bytes={requirements.min_disk_bytes}")

    if requirements.requires_gpu:
        parts.append("requires_gpu=yes")

    if requirements.min_gpu_count is not None:
        parts.append(f"min_gpu_count={requirements.min_gpu_count}")

    return ", ".join(parts)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
