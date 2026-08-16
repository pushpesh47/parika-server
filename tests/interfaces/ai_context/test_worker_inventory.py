"""
Unit tests for `parika.interfaces.ai_context.worker_inventory`.
"""

from __future__ import annotations

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.model_resource_requirements import (
    ModelResourceRequirements,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.interfaces.ai_context.worker_inventory import render_worker_inventory


def _provider(provider_id: str, *models: ProviderModel) -> Provider:
    # `ProviderModel` is not hashable (its `metadata` field is a
    # `MappingProxyType`), so -- exactly like the existing
    # `model_selection` test suite already does (see
    # `tests/core/planner/model_selection/test_selector.py`) -- a
    # plain tuple is passed for `models` rather than an actual
    # frozenset; `Provider.__post_init__` never converts it, so
    # iteration behaves identically either way.
    return Provider(id=provider_id, name=provider_id, models=models)  # type: ignore[arg-type]


class TestRenderWorkerInventory:
    def test_returns_empty_string_when_no_models_exist(self) -> None:
        assert render_worker_inventory([]) == ""

    def test_returns_empty_string_when_only_model_is_excluded(self) -> None:
        model = ProviderModel(id="model-a", name="model-a")
        providers = [_provider("provider.test", model)]

        assert render_worker_inventory(providers, exclude=model) == ""

    def test_excludes_exactly_the_routing_model(self) -> None:
        routing_model = ProviderModel(id="qwen3.6", name="qwen3.6")
        worker_model = ProviderModel(id="minicpm-v4.5", name="minicpm-v4.5")
        providers = [_provider("provider.ollama", routing_model, worker_model)]

        text = render_worker_inventory(providers, exclude=routing_model)

        assert "minicpm-v4.5" in text
        assert "qwen3.6" not in text

    def test_no_exclusion_when_exclude_is_none(self) -> None:
        model_a = ProviderModel(id="model-a", name="model-a")
        model_b = ProviderModel(id="model-b", name="model-b")
        providers = [_provider("provider.test", model_a, model_b)]

        text = render_worker_inventory(providers)

        assert "model-a" in text
        assert "model-b" in text

    def test_renders_provider_and_model_identity(self) -> None:
        model = ProviderModel(id="minicpm-v4.5", name="minicpm-v4.5")
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)

        assert "provider.ollama/minicpm-v4.5" in text

    def test_renders_capabilities_and_modalities(self) -> None:
        model = ProviderModel(
            id="minicpm-v4.5",
            name="minicpm-v4.5",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION, ModelCapability.VISION}),
            supported_modalities=frozenset({"text", "image"}),
        )
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)

        assert "capabilities: text_generation, vision" in text
        assert "modalities: image, text" in text

    def test_renders_thinking_tool_calling_structured_output_streaming_flags(
        self,
    ) -> None:
        model = ProviderModel(
            id="qwen3.6",
            name="qwen3.6",
            capabilities=frozenset({ModelCapability.REASONING}),
            execution_features=frozenset(
                {
                    ModelExecutionFeature.TOOL_CALLING,
                    ModelExecutionFeature.STREAMING,
                }
            ),
        )
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)

        assert "thinking_support: yes" in text
        assert "tool_calling: yes" in text
        assert "structured_output: no" in text
        assert "streaming: yes" in text

    def test_omits_context_window_when_unreported(self) -> None:
        model = ProviderModel(id="model-a", name="model-a")
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "context_window" not in text

    def test_renders_context_window_when_reported(self) -> None:
        model = ProviderModel(
            id="model-a",
            name="model-a",
            limits=ModelLimits(context_window=32768),
        )
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "context_window: 32768" in text

    def test_omits_resources_when_fully_unreported(self) -> None:
        model = ProviderModel(id="model-a", name="model-a")
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "resources:" not in text

    def test_renders_resources_when_reported(self) -> None:
        model = ProviderModel(
            id="model-a",
            name="model-a",
            resource_requirements=ModelResourceRequirements(
                min_ram_bytes=8_000_000_000, requires_gpu=True
            ),
        )
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "min_ram_bytes=8000000000" in text
        assert "requires_gpu=yes" in text

    def test_renders_description_when_reported(self) -> None:
        model = ProviderModel(
            id="model-a", name="model-a", description="model-a, 8b, q4_0"
        )
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "description: model-a, 8b, q4_0" in text

    def test_omits_description_when_unreported(self) -> None:
        model = ProviderModel(id="model-a", name="model-a")
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert "description:" not in text


class TestParikaModelKnowledgeSeparation:
    """
    PARIKA Model Knowledge must be rendered as its own, explicitly
    labeled section, never merged into the provider-facts segment
    (see `parika.core.semantics.model_knowledge`'s docstring).
    """

    def test_known_model_gets_a_separate_parika_knowledge_line(self) -> None:
        model = ProviderModel(id="minicpm-v4.5:latest", name="minicpm-v4.5:latest")
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)

        assert "PARIKA observed knowledge (not provider-reported): " in text
        assert "chart_analysis" in text
        assert "ui_analysis" in text

    def test_unknown_model_has_no_parika_knowledge_line(self) -> None:
        model = ProviderModel(id="totally-unknown-model", name="totally-unknown-model")
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)

        assert "PARIKA observed knowledge" not in text

    def test_parika_knowledge_line_is_indented_under_its_model(self) -> None:
        model = ProviderModel(id="glm-ocr:latest", name="glm-ocr:latest")
        providers = [_provider("provider.ollama", model)]

        text = render_worker_inventory(providers)
        lines = text.splitlines()
        knowledge_line_index = next(
            index for index, line in enumerate(lines) if "PARIKA observed knowledge" in line
        )

        assert lines[knowledge_line_index].startswith("  ")
        assert lines[knowledge_line_index - 1].startswith("- provider.ollama/glm-ocr:latest")


class TestMultipleProvidersAndModels(object):
    def test_renders_one_entry_per_model_across_providers(self) -> None:
        model_a = ProviderModel(id="model-a", name="model-a")
        model_b = ProviderModel(id="model-b", name="model-b")
        providers = [
            _provider("provider.one", model_a),
            _provider("provider.two", model_b),
        ]

        text = render_worker_inventory(providers)

        assert "provider.one/model-a" in text
        assert "provider.two/model-b" in text

    def test_header_is_present_when_any_model_is_rendered(self) -> None:
        model = ProviderModel(id="model-a", name="model-a")
        providers = [_provider("provider.test", model)]

        text = render_worker_inventory(providers)

        assert text.startswith("Other AI models currently installed")
