"""
Unit tests for Ollama model capability mapping.
"""

from __future__ import annotations

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.providers.ollama.model_mapping import (
    capabilities_from_show,
    execution_features_from_show,
    limits_from_show,
    modalities_from_show,
    specializations_from_show,
)


class TestCapabilitiesFromShow:
    def test_maps_completion_and_tools_and_thinking(self) -> None:
        payload = {"capabilities": ["completion", "tools", "thinking"]}

        capabilities = capabilities_from_show(payload)

        assert capabilities == {
            ModelCapability.TEXT_GENERATION,
            ModelCapability.REASONING,
        }

    def test_maps_embedding_only_model(self) -> None:
        payload = {"capabilities": ["embedding"]}

        assert capabilities_from_show(payload) == {
            ModelCapability.EMBEDDING,
        }

    def test_maps_vision_capability(self) -> None:
        payload = {"capabilities": ["completion", "vision"]}

        assert capabilities_from_show(payload) == {
            ModelCapability.TEXT_GENERATION,
            ModelCapability.VISION,
        }

    def test_falls_back_to_text_generation_when_missing(self) -> None:
        assert capabilities_from_show({}) == {
            ModelCapability.TEXT_GENERATION,
        }

    def test_falls_back_when_capabilities_not_a_list(self) -> None:
        assert capabilities_from_show({"capabilities": "completion"}) == {
            ModelCapability.TEXT_GENERATION,
        }

    def test_ignores_unknown_capability_values(self) -> None:
        payload = {"capabilities": ["completion", "insert", "unknown"]}

        assert capabilities_from_show(payload) == {
            ModelCapability.TEXT_GENERATION,
        }


class TestExecutionFeaturesFromShow:
    def test_always_includes_streaming(self) -> None:
        features = execution_features_from_show({})

        assert ModelExecutionFeature.STREAMING in features

    def test_maps_tools_to_tool_calling(self) -> None:
        payload = {"capabilities": ["completion", "tools"]}

        features = execution_features_from_show(payload)

        assert features == {
            ModelExecutionFeature.STREAMING,
            ModelExecutionFeature.TOOL_CALLING,
        }

    def test_no_tool_calling_when_not_reported(self) -> None:
        payload = {"capabilities": ["completion"]}

        features = execution_features_from_show(payload)

        assert features == {ModelExecutionFeature.STREAMING}


class TestLimitsFromShow:
    def test_extracts_architecture_specific_context_length(self) -> None:
        payload = {
            "model_info": {
                "general.architecture": "qwen3",
                "qwen3.context_length": 40960,
            }
        }

        limits = limits_from_show(payload)

        assert limits.context_window == 40960
        assert limits.max_output_tokens is None

    def test_returns_default_limits_when_model_info_missing(self) -> None:
        limits = limits_from_show({})

        assert limits.context_window is None

    def test_ignores_non_integer_context_length(self) -> None:
        payload = {"model_info": {"llama.context_length": "not-a-number"}}

        limits = limits_from_show(payload)

        assert limits.context_window is None


class TestSpecializationsFromShow:
    def test_maps_completion_to_general_chat(self) -> None:
        payload = {"capabilities": ["completion"]}

        assert specializations_from_show(payload) == {"general_chat"}

    def test_maps_embedding_to_embedding(self) -> None:
        payload = {"capabilities": ["embedding"]}

        assert specializations_from_show(payload) == {"embedding"}

    def test_maps_thinking_to_reasoning(self) -> None:
        payload = {"capabilities": ["completion", "thinking"]}

        assert specializations_from_show(payload) == {
            "general_chat",
            "reasoning",
        }

    def test_never_fabricates_coding_specialization(self) -> None:
        payload = {"capabilities": ["completion", "tools"]}

        specializations = specializations_from_show(payload)

        assert "coding" not in specializations

    def test_never_fabricates_vision_understanding_specialization(self) -> None:
        payload = {"capabilities": ["completion", "vision"]}

        # Raw Provider Metadata evidence only reports "general_chat"
        # here (from "completion"): Ollama's "vision" capability only
        # means the model accepts image input (already captured
        # precisely by `ModelCapability.VISION` and the "image"
        # modality), not that it is specialized for vision
        # understanding. Correcting a *specific* model's specialization
        # (e.g. "glm-ocr") is the Semantic Enrichment layer's job
        # (`parika.core.semantics.resolve_specializations()` via
        # `parika.providers.ollama.discovery.build_provider_model()`),
        # not this mechanical mapping function's.
        specializations = specializations_from_show(payload)

        assert specializations == {"general_chat"}
        assert "vision_understanding" not in specializations

    def test_empty_when_capabilities_missing(self) -> None:
        assert specializations_from_show({}) == frozenset()


class TestModalitiesFromShow:
    def test_always_includes_text(self) -> None:
        assert modalities_from_show({}) == {"text"}

    def test_maps_vision_capability_to_image_modality(self) -> None:
        payload = {"capabilities": ["completion", "vision"]}

        assert modalities_from_show(payload) == {"text", "image"}

    def test_no_image_modality_when_vision_not_reported(self) -> None:
        payload = {"capabilities": ["completion"]}

        assert modalities_from_show(payload) == {"text"}
