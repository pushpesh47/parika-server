"""
Tests for Provider Request Factory.
"""

from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from parika.core.autonomous import (
    build_provider_request,
    is_supported_autonomous_provider,
    get_supported_provider_types,
    AutonomousProviderError,
)
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.generation_request import GenerationRequest, GenerationOperation
from parika.core.provider_manager.speech_request import SpeechRequest, SpeechOperation
from parika.core.capability_resolver.capability_resolution import CapabilityResolution
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.provider_manager.provider_model import ProviderModel


class TestProviderFactory:
    """Tests for provider request factory."""

    def _make_context(
        self,
        capability_id: str,
        category: CapabilityCategory = CapabilityCategory.VISION,
        inputs: dict | None = None,
        metadata: dict | None = None,
    ):
        """Create a mock context for testing."""
        definition = CapabilityDefinition(
            id=capability_id,
            name="Test",
            description="Test",
            category=category,
            provider="test",
            source="test",
            enabled=True,
        )
        resolution = CapabilityResolution(
            request=Mock(capability_id=capability_id),
            definition=definition,
            resolved_at=datetime.now(UTC),
        )
        model = ProviderModel(
            id="test-model",
            name="Test Model",
            capabilities=[],
            supported_modalities=[],
            specializations=[],
            execution_features=[],
        )
        return resolution, model, MappingProxyType(inputs or {}), MappingProxyType(metadata or {})

    def test_vision_request(self):
        """Test building vision request."""
        resolution, model, inputs, metadata = self._make_context(
            "vision.provider_describe_image",
            CapabilityCategory.VISION,
            {"instruction": "Describe this", "images_base64": ["abc123"]},
            {"provider_request_type": "vision"},
        )

        request = build_provider_request(
            "vision.provider_describe_image", inputs, metadata, resolution, model
        )

        assert isinstance(request, ChatRequest)
        assert len(request.messages) == 1
        msg = request.messages[0]
        assert msg.role == "user"
        assert msg.content == "Describe this"
        assert msg.images == ("abc123",)

    def test_vision_request_single_image_string(self):
        """Test vision request with single image as string."""
        resolution, model, inputs, metadata = self._make_context(
            "vision.provider_describe_image",
            CapabilityCategory.VISION,
            {"instruction": "Describe", "images_base64": "single_image"},
            {"provider_request_type": "vision"},
        )

        request = build_provider_request(
            "vision.provider_describe_image", inputs, metadata, resolution, model
        )

        assert isinstance(request, ChatRequest)
        assert request.messages[0].images == ("single_image",)

    def test_ocr_request(self):
        """Test building OCR request."""
        resolution, model, inputs, metadata = self._make_context(
            "ocr.provider_extract_text",
            CapabilityCategory.OCR,
            {"instruction": "Extract text", "image_base64": "img123"},
            {"provider_request_type": "ocr"},
        )

        request = build_provider_request(
            "ocr.provider_extract_text", inputs, metadata, resolution, model
        )

        assert isinstance(request, ChatRequest)
        assert len(request.messages) == 1
        msg = request.messages[0]
        assert msg.role == "user"
        assert msg.content == "Extract text"
        assert msg.images == ("img123",)

    def test_generation_request_image(self):
        """Test building image generation request."""
        resolution, model, inputs, metadata = self._make_context(
            "image.provider_generate",
            CapabilityCategory.IMAGE_GENERATION,
            {
                "operation": "image_generate",
                "prompt": "A beautiful sunset",
                "width": 1024,
                "height": 768,
            },
            {"provider_request_type": "generation"},
        )

        request = build_provider_request(
            "image.provider_generate", inputs, metadata, resolution, model
        )

        assert isinstance(request, GenerationRequest)
        assert request.operation == GenerationOperation.IMAGE_GENERATE
        assert request.prompt == "A beautiful sunset"
        assert request.width == 1024
        assert request.height == 768

    def test_generation_request_video(self):
        """Test building video generation request."""
        resolution, model, inputs, metadata = self._make_context(
            "video.provider_generate",
            CapabilityCategory.VIDEO_GENERATION,
            {
                "operation": "video_generate",
                "prompt": "A moving sunset",
                "duration_seconds": 5,
                "fps": 30,
            },
            {"provider_request_type": "generation"},
        )

        request = build_provider_request(
            "video.provider_generate", inputs, metadata, resolution, model
        )

        assert isinstance(request, GenerationRequest)
        assert request.operation == GenerationOperation.VIDEO_GENERATE
        assert request.duration_seconds == 5
        assert request.fps == 30

    def test_speech_to_text_request(self):
        """Test building speech-to-text request."""
        resolution, model, inputs, metadata = self._make_context(
            "speech.provider_stt",
            CapabilityCategory.SPEECH,
            {
                "operation": "speech_to_text",
                "audio_base64": "audio_data",
                "audio_mime_type": "audio/wav",
                "language": "en",
            },
            {"provider_request_type": "speech"},
        )

        request = build_provider_request(
            "speech.provider_stt", inputs, metadata, resolution, model
        )

        assert isinstance(request, SpeechRequest)
        assert request.operation == SpeechOperation.SPEECH_TO_TEXT
        assert request.audio_base64 == "audio_data"
        assert request.audio_mime_type == "audio/wav"
        assert request.language == "en"

    def test_text_to_speech_request(self):
        """Test building text-to-speech request."""
        resolution, model, inputs, metadata = self._make_context(
            "speech.provider_tts",
            CapabilityCategory.TEXT_TO_SPEECH,
            {
                "operation": "text_to_speech",
                "text": "Hello world",
                "voice": "alloy",
                "language": "en",
            },
            {"provider_request_type": "speech"},
        )

        request = build_provider_request(
            "speech.provider_tts", inputs, metadata, resolution, model
        )

        assert isinstance(request, SpeechRequest)
        assert request.operation == SpeechOperation.TEXT_TO_SPEECH
        assert request.text == "Hello world"
        assert request.voice == "alloy"
        assert request.language == "en"

    def test_document_request(self):
        """Test building document analysis request."""
        resolution, model, inputs, metadata = self._make_context(
            "document.provider_analyze_content",
            CapabilityCategory.LLM,
            {
                "instruction": "Summarize this",
                "content": "Long document content...",
            },
            {"provider_request_type": "document"},
        )

        request = build_provider_request(
            "document.provider_analyze_content", inputs, metadata, resolution, model
        )

        assert isinstance(request, ChatRequest)
        assert len(request.messages) == 1
        msg = request.messages[0]
        assert msg.role == "user"
        assert "Summarize this" in msg.content
        assert "Long document content" in msg.content

    def test_unsupported_chat_rejected(self):
        """Test that chat.respond is rejected."""
        resolution, model, inputs, metadata = self._make_context(
            "chat.respond",
            CapabilityCategory.LLM,
            {"message": "Hello"},
            {"provider_request_type": "chat"},
        )

        with pytest.raises(AutonomousProviderError) as exc_info:
            build_provider_request("chat.respond", inputs, metadata, resolution, model)

        assert "not supported" in str(exc_info.value)
        assert "chat" in str(exc_info.value)

    def test_unsupported_coding_rejected(self):
        """Test that coding.plan_change is rejected."""
        resolution, model, inputs, metadata = self._make_context(
            "coding.plan_change",
            CapabilityCategory.REASONING,
            {"task": "Plan this"},
            {"provider_request_type": "coding"},
        )

        with pytest.raises(AutonomousProviderError) as exc_info:
            build_provider_request("coding.plan_change", inputs, metadata, resolution, model)

        assert "not supported" in str(exc_info.value)
        assert "coding" in str(exc_info.value)

    def test_supported_types_list(self):
        """Test getting supported provider types."""
        supported = get_supported_provider_types()
        assert "vision" in supported
        assert "ocr" in supported
        assert "generation" in supported
        assert "speech" in supported
        assert "document" in supported
        assert "chat" not in supported
        assert "coding" not in supported

    def test_is_supported(self):
        """Test is_supported_autonomous_provider."""
        assert is_supported_autonomous_provider("vision")
        assert is_supported_autonomous_provider("ocr")
        assert is_supported_autonomous_provider("generation")
        assert is_supported_autonomous_provider("speech")
        assert is_supported_autonomous_provider("document")
        assert not is_supported_autonomous_provider("chat")
        assert not is_supported_autonomous_provider("coding")
        assert not is_supported_autonomous_provider("unknown")

    def test_infers_type_from_capability_id(self):
        """Test that provider type can be inferred from capability_id."""
        resolution, model, inputs, metadata = self._make_context(
            "vision.provider_describe_image",
            CapabilityCategory.VISION,
            {"instruction": "Describe", "images_base64": ["img"]},
            {},  # No explicit provider_request_type
        )

        # Should infer "vision" from capability_id
        request = build_provider_request(
            "vision.provider_describe_image", inputs, MappingProxyType({}), resolution, Mock()
        )
        assert isinstance(request, ChatRequest)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])