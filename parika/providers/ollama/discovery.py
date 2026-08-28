"""
PARIKA Ollama Provider - Model Discovery Helpers

Pure functions that turn already-fetched `/api/tags` and `/api/show`
payloads into a `ProviderModel`. Kept separate from `driver.py` (which
owns the actual HTTP calls) so this translation logic is independently
testable and the driver itself stays focused on orchestration (see
`PARIKA_Core_Coding_Standards.md` - File Size Guidelines).
"""

from __future__ import annotations

from typing import Any

from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.provider_context import OllamaContextCapability

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.semantics import resolve_specializations

from .latency_estimation import estimate_baseline_metrics
from .model_mapping import (
    capabilities_from_show,
    execution_features_from_show,
    limits_from_show,
    modalities_from_show,
    specializations_from_show,
)
import logging

logger = logging.getLogger(__name__)


def build_provider_model(
    name: str,
    tags_entry: dict[str, Any],
    show_payload: dict[str, Any],
) -> ProviderModel:
    """
    Build a single ProviderModel from a `/api/tags` entry, enriched
    with a `/api/show` payload (empty when details could not be
    fetched).

    In addition to the normalized capability/feature/limit fields,
    `ProviderModel.metadata` is populated with a small set of
    well-known, provider-reported keys that Planner's model-selection
    scoring rules read generically (never assuming any specific
    provider populated them):

    - `estimated_latency_ms`, `estimated_throughput_tps`: a coarse
      baseline derived from Ollama's own `parameter_size`, present
      only when it could be parsed (see `latency_estimation.py`).
    - `deployment_type`: always `"local"` for Ollama, since it only
      ever runs models on infrastructure PARIKA itself controls.

    `ProviderModel.supported_modalities` is populated purely from
    Ollama's own reported `capabilities` list (see `model_mapping
    .modalities_from_show()`).

    `ProviderModel.specializations` goes through one additional step:
    Ollama's own reported `capabilities` list is first translated into
    raw Provider Metadata evidence (`model_mapping
    .specializations_from_show()`) - conservatively, so this
    integration never fabricates a specialization Ollama did not
    actually report (e.g. it never claims `"coding"` for any model,
    since Ollama does not report that) - and that evidence is then
    resolved to its final, canonical form by the Core Semantic
    Enrichment layer (`parika.core.semantics.resolve_specializations()`),
    which also applies any Local Curated Override registered for this
    specific model id (e.g. correcting a model like `"glm-ocr"` whose
    generic `"completion"` capability would otherwise be
    mis-classified as `"general_chat"` - see `parika.core.semantics
    .overrides`). `ProviderModel.resource_requirements` is left at its
    default (fully unreported), since Ollama does not expose hardware
    requirements for a model today.

    Args:
        name:
            Model identifier as reported by `/api/tags`.

        tags_entry:
            The `/api/tags` entry for this model.

        show_payload:
            The `/api/show` response for this model, or `{}` if it
            could not be fetched.

    Returns:
        The normalized ProviderModel.
    """

    details = tags_entry.get("details")
    details = details if isinstance(details, dict) else {}

    capabilities = capabilities_from_show(show_payload)
    supports_reasoning = ModelCapability.REASONING in capabilities

    # Provider Metadata evidence (mechanical, Ollama-specific) ->
    # Semantic Enrichment (provider-independent, Core-level) -> the
    # final, canonical specializations. See this function's docstring.
    raw_specializations = specializations_from_show(show_payload)
    specializations = resolve_specializations(name, raw_specializations)

    metadata: dict[str, Any] = {"deployment_type": "local"}
    metadata.update(
        estimate_baseline_metrics(
            details,
            supports_reasoning=supports_reasoning,
        )
    )

    logger.debug(
        "Discovered model '%s': "
        "specializations=%s (provider_reported=%s) "
        "modalities=%s "
        "capabilities=%s "
        "execution_features=%s",
        name,
        sorted(specializations),
        sorted(raw_specializations),
        sorted(modalities_from_show(show_payload)),
        sorted(value.value for value in capabilities),
        sorted(
            value.value
            for value in execution_features_from_show(show_payload)
        ),
    )

    return ProviderModel(
        id=name,
        name=name,
        description=describe_model(details),
        capabilities=capabilities,
        execution_features=execution_features_from_show(show_payload),
        limits=limits_from_show(show_payload),
        specializations=specializations,
        supported_modalities=modalities_from_show(show_payload),
        metadata=metadata,
        context_capability=OllamaContextCapability(),
    )


def describe_model(details: dict[str, Any]) -> str | None:
    """
    Build a short human-readable description from a `/api/tags`
    `details` object.
    """

    family = details.get("family")
    parameter_size = details.get("parameter_size")
    quantization = details.get("quantization_level")

    parts = [
        str(value)
        for value in (family, parameter_size, quantization)
        if value
    ]

    return ", ".join(parts) if parts else None
