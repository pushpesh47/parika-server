"""
PARIKA Ollama Provider - Model Capability Mapping

Translates the model metadata reported by Ollama's own `/api/show`
endpoint into normalized `ModelCapability`, `ModelExecutionFeature`,
and `ModelLimits` values.

This mapping is driven entirely by data Ollama itself reports for each
discovered model (its `capabilities` list and `model_info` fields), not
by hardcoded model names or families, so that any Ollama-compatible
model - qwen, llama, mistral, deepseek, glm, or otherwise - is mapped
consistently without code changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_limits import ModelLimits

_CAPABILITY_MAP: dict[str, ModelCapability] = {
    "completion": ModelCapability.TEXT_GENERATION,
    "vision": ModelCapability.VISION,
    "embedding": ModelCapability.EMBEDDING,
    "thinking": ModelCapability.REASONING,
}
"""
Maps a value reported in Ollama's `/api/show` `capabilities` list to
the corresponding normalized `ModelCapability`.
"""

_EXECUTION_FEATURE_MAP: dict[str, ModelExecutionFeature] = {
    "tools": ModelExecutionFeature.TOOL_CALLING,
}
"""
Maps a value reported in Ollama's `/api/show` `capabilities` list to
the corresponding normalized `ModelExecutionFeature`.
"""

_CONTEXT_LENGTH_SUFFIX = ".context_length"
"""
Suffix of the architecture-specific `model_info` key that reports a
model's context window (e.g. "llama.context_length",
"qwen2.context_length"). The architecture prefix varies per model
family, so every key is scanned rather than looking one up by name.
"""

_CAPABILITY_SPECIALIZATION_MAP: dict[str, str] = {
    "completion": "general_chat",
    "embedding": "embedding",
    "thinking": "reasoning",
}
"""
Maps a value reported in Ollama's `/api/show` `capabilities` list to
the generic Model Selection Framework specialization tag (see
`parika.core.provider_manager.provider_model.ProviderModel
.specializations` and `parika.core.planner.model_selection
.task_classification`) it corresponds to. Deliberately conservative:
only specializations Ollama's own `/api/show` response actually
implies are ever reported - nothing here is a per-model-name guess
about what a specific model was fine-tuned for (e.g. "coding"), which
Ollama does not report today.

This is the *Provider Metadata* evidence source of the Semantic
Enrichment layer (see `parika.core.semantics` module docstring):
`specializations_from_show()` below produces only this raw, mechanical
evidence. It deliberately does NOT have the final word - a model
reporting `"completion"` genuinely may not be general-chat-specialized
(e.g. an OCR-focused model still reports `"completion"`, since that is
Ollama's generic "can generate text" signal, not a specialization
claim). `parika.core.semantics.resolve_specializations()` (invoked
from `discovery.build_provider_model()`) combines this evidence with
any Local Curated Override before it ever reaches `ProviderModel
.specializations` - this module is not the place to special-case any
specific model name (e.g. `"vision"` is deliberately left unmapped
here today: Ollama's `"vision"` capability only means the model
accepts image input, already captured precisely by `ModelCapability
.VISION` and the `"image"` modality below - it is not, on its own,
reliable evidence of a `"vision_understanding"` *specialization*, so
nothing is fabricated for it until a real need justifies adding one).
"""

_CAPABILITY_MODALITY_MAP: dict[str, str] = {
    "vision": "image",
}
"""
Maps a value reported in Ollama's `/api/show` `capabilities` list to
the generic modality tag (see `ProviderModel.supported_modalities`)
it corresponds to. Every model implicitly supports the `"text"`
modality (see `modalities_from_show()`); this table only ever adds
*additional* modalities beyond that baseline.
"""


def capabilities_from_show(show_payload: Mapping[str, Any]) -> frozenset[ModelCapability]:
    """
    Derive `ModelCapability` values from an Ollama `/api/show` payload.

    Args:
        show_payload:
            Parsed JSON body returned by `POST /api/show`.

    Returns:
        Normalized capabilities. Falls back to
        `{ModelCapability.TEXT_GENERATION}` when Ollama reports no
        `capabilities` list at all (older Ollama servers), since every
        model servable through `/api/generate` can produce text.
    """

    reported = show_payload.get("capabilities")

    if not isinstance(reported, list) or not reported:
        return frozenset({ModelCapability.TEXT_GENERATION})

    capabilities = {
        _CAPABILITY_MAP[value]
        for value in reported
        if isinstance(value, str) and value in _CAPABILITY_MAP
    }

    return frozenset(capabilities)


def execution_features_from_show(
    show_payload: Mapping[str, Any],
) -> frozenset[ModelExecutionFeature]:
    """
    Derive `ModelExecutionFeature` values from an Ollama `/api/show`
    payload.

    Streaming is always included: every Ollama chat/generate endpoint
    supports `stream: true` regardless of the selected model.
    """

    reported = show_payload.get("capabilities")

    features = {ModelExecutionFeature.STREAMING}

    if isinstance(reported, list):
        features.update(
            _EXECUTION_FEATURE_MAP[value]
            for value in reported
            if isinstance(value, str) and value in _EXECUTION_FEATURE_MAP
        )

    return frozenset(features)


def specializations_from_show(show_payload: Mapping[str, Any]) -> frozenset[str]:
    """
    Derive generic Model Selection Framework specialization tags from
    an Ollama `/api/show` payload's `capabilities` list.

    Returns an empty set when Ollama reports no `capabilities` list at
    all (older Ollama servers) - unreported, not "unspecialized" (see
    `ProviderModel.specializations`'s graceful-degradation contract).
    """

    reported = show_payload.get("capabilities")

    if not isinstance(reported, list):
        return frozenset()

    return frozenset(
        _CAPABILITY_SPECIALIZATION_MAP[value]
        for value in reported
        if isinstance(value, str) and value in _CAPABILITY_SPECIALIZATION_MAP
    )


def modalities_from_show(show_payload: Mapping[str, Any]) -> frozenset[str]:
    """
    Derive generic Model Selection Framework modality tags from an
    Ollama `/api/show` payload's `capabilities` list.

    Every model servable through `/api/generate` or `/api/chat`
    supports the `"text"` modality; `capabilities` may report
    additional ones (e.g. `"vision"` -> `"image"`).
    """

    reported = show_payload.get("capabilities")

    modalities = {"text"}

    if isinstance(reported, list):
        modalities.update(
            _CAPABILITY_MODALITY_MAP[value]
            for value in reported
            if isinstance(value, str) and value in _CAPABILITY_MODALITY_MAP
        )

    return frozenset(modalities)


def limits_from_show(show_payload: Mapping[str, Any]) -> ModelLimits:
    """
    Derive `ModelLimits` from an Ollama `/api/show` payload.

    The context window is read from whichever architecture-specific
    `model_info` key ends with `.context_length` (the key prefix
    varies per model family, e.g. "llama.context_length" versus
    "qwen2.context_length"). Ollama does not report a maximum output
    token count, so `max_output_tokens` is always `None`.
    """

    model_info = show_payload.get("model_info")

    if not isinstance(model_info, dict):
        return ModelLimits()

    context_window: int | None = None

    for key, value in model_info.items():
        if not isinstance(key, str) or not key.endswith(_CONTEXT_LENGTH_SUFFIX):
            continue

        if isinstance(value, int):
            context_window = value
            break

    return ModelLimits(context_window=context_window)
