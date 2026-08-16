"""
PARIKA Planner - Hard Requirement Filtering Pipeline

Determines whether a candidate (Provider, ProviderModel) must be
excluded from scoring entirely. This is kept separate from
`rules.py`/`preference_rules.py` because these are binary exclusions,
not scored contributions: a candidate either satisfies every hard
requirement and proceeds to scoring, or it does not and is rejected
with a specific, loggable reason.

`evaluate_hard_requirements()` composes the ordered filtering pipeline
mandated by the Model Selection Framework's design: Task Classification
happens earlier, in `requirements.build_execution_requirements()` (it
produces the `required_specializations`/`required_capabilities`/
`required_modalities`/`required_execution_features` this module
filters on); ranking happens later, in `selector.py`, and only ever
sees candidates that already survived every step here.

    1. Filter by specialization      (`_filter_specialization`)
    2. Filter by required capabilities
       (`_filter_capabilities`, `_filter_execution_features`)
    3. Filter by supported modalities (`_filter_modalities`)
    4. Filter unhealthy models        (`_filter_health`)
    5. Filter unavailable models      (`_filter_availability`)
    6. Filter by context window       (`_filter_context_window`)
    7. Filter insufficient resources  (`_filter_resources`)

Two different graceful-degradation contracts are deliberately in play,
matching how confidently each signal can be trusted:

- `specializations`/`supported_modalities` are optional, best-effort
  provider-reported tags. A model reporting *none at all* is never
  rejected on that dimension - "unreported" is not "incompatible".
  This is what lets the very same filtering pipeline work correctly
  both for providers that have started advertising rich task metadata
  and for providers (e.g. today's Ollama integration, for most
  dimensions) that have not yet - see `docs/architecture
  /Model_Selection_Framework.md` section 5.
- `capabilities`/`execution_features` (and their `required_*`
  counterparts) are the model's own declared, mandatory contract -
  exactly like `requirements.capability` already was before this
  pipeline existed. A model that does not report one is *always*
  treated as not supporting it.
"""

from __future__ import annotations

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel

from .requirements import ExecutionRequirements, Requirement
import logging

logger = logging.getLogger(__name__)


def evaluate_hard_requirements(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Check whether a candidate satisfies every hard requirement.

    Runs the full filtering pipeline, in order, stopping at (and
    returning) the first failing step - specialization, then required
    capabilities/execution features, then modalities, then provider
    health, then provider availability, then context window, then
    resource sufficiency.

    Args:
        provider:
            The candidate's Provider.

        model:
            The candidate's ProviderModel.

        requirements:
            The Goal's ExecutionRequirements.

    Returns:
        `None` if the candidate satisfies every hard requirement and
        should proceed to scoring, otherwise a short, human-readable
        rejection reason.
    """

    for step in (
        _filter_specialization,
        _filter_capabilities,
        _filter_execution_features,
        _filter_modalities,
        _filter_health,
        _filter_availability,
        _filter_context_window,
        _filter_resources,
    ):
        reason = step(provider, model, requirements)

        if reason is None:
            logger.debug(
                "Filter PASSED: model=%s filter=%s",
                model.id,
                step.__name__,
            )
        else:
            logger.debug(
                "Filter FAILED: model=%s filter=%s reason=%s",
                model.id,
                step.__name__,
                reason,
            )

        if reason is not None:
            return reason

    return None


def _filter_specialization(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 1: reject a model whose *declared* specializations do not
    include any specialization this task requires.

    This is the direct fix for "an OCR model gets picked for ordinary
    conversation" and its siblings: once a Provider advertises
    `ProviderModel.specializations` (e.g. `{"ocr"}`), a model
    specialized for a different task can no longer even be scored for
    an unrelated one. A model that reports no specializations at all
    is unaffected - specialization is optional, best-effort metadata,
    not a closed-world claim of incompatibility (see this module's
    docstring).
    """

    if not requirements.required_specializations:
        return None

    if not model.specializations:
        return None

    if model.specializations & requirements.required_specializations:
        return None

    return (
        "model specializations "
        f"{sorted(model.specializations)} do not include any "
        f"required specialization {sorted(requirements.required_specializations)}"
    )


def _filter_capabilities(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 2 (capabilities half): reject a model missing the single
    hard-required `ModelCapability`, or any additional capability
    Task Classification declared required for this task.
    """

    if requirements.capability not in model.capabilities:
        return (
            f"model does not support required capability "
            f"'{requirements.capability.value}'"
        )

    missing = requirements.required_capabilities - model.capabilities

    if missing:
        return (
            "model does not support required capabilities: "
            f"{sorted(value.value for value in missing)}"
        )

    if requirements.vision is Requirement.REQUIRED and (
        ModelCapability.VISION not in model.capabilities
    ):
        return "model does not support required vision input"

    return None


def _filter_execution_features(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 2 (execution features half): reject a model missing a
    `REQUIRED` (not `PREFERRED`) tool-calling/structured-output
    requirement, or any additional execution feature Task
    Classification declared required for this task.
    """

    if requirements.tool_calling is Requirement.REQUIRED and (
        ModelExecutionFeature.TOOL_CALLING not in model.execution_features
    ):
        return "model does not support required tool calling"

    if requirements.structured_output is Requirement.REQUIRED and (
        ModelExecutionFeature.STRUCTURED_OUTPUT not in model.execution_features
    ):
        return "model does not support required structured output"

    missing = requirements.required_execution_features - model.execution_features

    if missing:
        return (
            "model does not support required execution features: "
            f"{sorted(value.value for value in missing)}"
        )

    return None


def _filter_modalities(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 3: reject a model whose *declared* supported modalities do
    not include any modality this task requires.

    Same optional, best-effort semantics as `_filter_specialization`:
    a model reporting no modalities at all is never rejected here.
    """

    if not requirements.required_modalities:
        return None

    if not model.supported_modalities:
        return None

    if model.supported_modalities & requirements.required_modalities:
        return None

    return (
        "model supported modalities "
        f"{sorted(model.supported_modalities)} do not include any "
        f"required modality {sorted(requirements.required_modalities)}"
    )


def _filter_health(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 4: reject a candidate whose Provider's reported health is
    explicitly unavailable. Unknown health (`provider.health is None`)
    is not a rejection.
    """

    if provider.health is not None and not provider.health.available:
        return "provider is unavailable"

    return None


def _filter_availability(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 5: reject a candidate whose Provider is administratively
    disabled for routing.
    """

    if not provider.enabled:
        return "provider is disabled"

    return None


def _filter_context_window(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 6: reject a model whose advertised context window is smaller
    than (or absent, when one is required) `requirements
    .min_context_window`.
    """

    if requirements.min_context_window is None:
        return None

    if (
        model.limits.context_window is None
        or model.limits.context_window < requirements.min_context_window
    ):
        return (
            f"model context window "
            f"({model.limits.context_window}) is smaller than the "
            f"required minimum ({requirements.min_context_window})"
        )

    return None


def _filter_resources(
    provider: Provider,
    model: ProviderModel,
    requirements: ExecutionRequirements,
) -> str | None:
    """
    Step 7: reject a model whose declared
    `ProviderModel.resource_requirements` are known to exceed the
    supplied `requirements.available_resources` snapshot.

    Resource validation is skipped entirely - never treated as a
    rejection - whenever no snapshot was supplied
    (`available_resources is None`), or whenever a specific
    requirement dimension was never declared by the model at all
    (each `ModelResourceRequirements` field defaults to "unreported").
    """

    snapshot = requirements.available_resources

    if snapshot is None:
        return None

    needs = model.resource_requirements

    if (
        needs.min_ram_bytes is not None
        and snapshot.memory.available_bytes < needs.min_ram_bytes
    ):
        return (
            f"model requires at least {needs.min_ram_bytes} bytes of "
            f"RAM, but only {snapshot.memory.available_bytes} are "
            "available"
        )

    if (
        needs.min_disk_bytes is not None
        and snapshot.disk.free_bytes < needs.min_disk_bytes
    ):
        return (
            f"model requires at least {needs.min_disk_bytes} bytes of "
            f"free disk space, but only {snapshot.disk.free_bytes} are "
            "available"
        )

    if needs.requires_gpu and snapshot.gpu.status.value != "available":
        return (
            "model requires a GPU, but no GPU is currently reported as "
            f"available (status={snapshot.gpu.status.value})"
        )

    return None
