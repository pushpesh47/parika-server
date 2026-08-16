"""
Unit tests for `parika.providers.ollama.discovery.build_provider_model()`,
focused on the Semantic Enrichment integration: raw Ollama
`/api/show` metadata must be resolved into the *final*, canonical
`ProviderModel.specializations` (Provider Metadata evidence plus any
Local Curated Override), not the raw provider-reported value.
"""

from __future__ import annotations

from parika.core.provider_manager.model_capability import ModelCapability
from parika.providers.ollama.discovery import build_provider_model


class TestBuildProviderModelSpecializations:
    def test_ordinary_chat_model_keeps_general_chat(self) -> None:
        model = build_provider_model(
            "qwen3-coder-next:latest",
            tags_entry={"details": {"family": "qwen3"}},
            show_payload={
                "capabilities": ["completion", "tools"],
                "model_info": {"qwen3.context_length": 40960},
            },
        )

        assert model.specializations == {"general_chat"}

    def test_glm_ocr_is_resolved_to_ocr_not_general_chat(self) -> None:
        """
        The exact bug this change fixes: Ollama's `/api/show` for
        `glm-ocr` reports `capabilities: ["completion", "vision"]`.
        Mechanically, `"completion"` implies `"general_chat"` and
        `"vision"` implies `"vision_understanding"` - but the Local
        Curated Override for `"glm-ocr"` corrects this to the model's
        actual specialization: OCR/document understanding, not
        general conversation.
        """

        model = build_provider_model(
            "glm-ocr:latest",
            tags_entry={"details": {"family": "glm"}},
            show_payload={
                "capabilities": ["completion", "vision"],
                "model_info": {"glm4.context_length": 8192},
            },
        )

        assert model.specializations == {"ocr", "document_understanding"}
        assert "general_chat" not in model.specializations

        # Only `specializations` is affected by Semantic Enrichment;
        # every other field is populated exactly as before.
        assert model.capabilities == {
            ModelCapability.TEXT_GENERATION,
            ModelCapability.VISION,
        }
        assert model.supported_modalities == {"text", "image"}

    def test_unregistered_vision_model_keeps_mechanical_evidence(self) -> None:
        """
        A vision model with no Local Curated Override still gets the
        raw Provider Metadata evidence, unmodified - Semantic
        Enrichment never removes anything except via an explicit
        override.
        """

        model = build_provider_model(
            "some-other-vision-model:latest",
            tags_entry={"details": {}},
            show_payload={"capabilities": ["completion", "vision"]},
        )

        assert model.specializations == {"general_chat"}
