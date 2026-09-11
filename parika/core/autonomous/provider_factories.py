"""
PARIKA Autonomous Execution - Provider Request Factory

Reconstructs ProviderRequest objects from durable autonomous task data.
This is a factory module, not a registry - it constructs requests from
durable task data + resolved runtime model/resolution.

Supported provider request types:
- vision (ChatRequest with images)
- video (ChatRequest with frames)
- ocr (ChatRequest with images)
- generation (GenerationRequest)
- speech (SpeechRequest for STT/TTS)
- document (ChatRequest with text content)

Explicitly unsupported for autonomous execution:
- chat (ChatRequest with conversation history/tools/streaming)
- coding (ChatRequest with conversation history)
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parika.core.capability_resolver.capability_resolution import CapabilityResolution
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.generation_request import GenerationRequest, GenerationOperation
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.speech_request import SpeechOperation, SpeechRequest


class AutonomousProviderError(Exception):
    """Raised when autonomous provider request reconstruction fails."""
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderRequestContext:
    """Context passed to factory functions containing resolved runtime info."""
    resolution: CapabilityResolution
    model: ProviderModel
    task_inputs: MappingProxyType[str, Any]
    task_metadata: MappingProxyType[str, Any]


def build_provider_request(
    capability_id: str,
    inputs: MappingProxyType[str, Any],
    metadata: MappingProxyType[str, Any],
    resolution: CapabilityResolution,
    model: ProviderModel,
) -> ProviderRequest:
    """
    Main factory entry point - reconstructs ProviderRequest from durable task data.
    
    Args:
        capability_id: The capability identifier (e.g., "vision.provider_describe_image")
        inputs: Durable task inputs from AutonomousTask.inputs
        metadata: Durable task metadata from AutonomousTask.metadata
        resolution: CapabilityResolution from CapabilityResolver
        model: Selected ProviderModel from Planner
        
    Returns:
        Appropriate ProviderRequest subclass for the capability
        
    Raises:
        AutonomousProviderError: If capability_id is not supported for autonomous execution
    """
    provider_type = metadata.get("provider_request_type")
    
    if provider_type is None:
        # Try to infer from capability_id pattern
        provider_type = _infer_provider_type(capability_id)
    
    context = ProviderRequestContext(
        resolution=resolution,
        model=model,
        task_inputs=inputs,
        task_metadata=metadata,
    )
    
    factory = _PROVIDER_FACTORIES.get(provider_type)
    if factory is None:
        supported = ", ".join(sorted(_PROVIDER_FACTORIES.keys()))
        raise AutonomousProviderError(
            f"Provider request type '{provider_type}' not supported for autonomous execution. "
            f"Supported types: {supported}. "
            f"Unsupported types (require interactive runtime): 'chat', 'coding'."
        )
    
    return factory(context)


def _infer_provider_type(capability_id: str) -> str:
    """Infer provider request type from capability_id pattern."""
    if capability_id.startswith("vision.provider_") or capability_id.startswith("video.provider_"):
        return "vision"
    elif capability_id.startswith("ocr.provider_"):
        return "ocr"
    elif capability_id.startswith("image.provider_") or capability_id.startswith("video.provider_generate"):
        return "generation"
    elif capability_id.startswith("speech.provider_") or capability_id.startswith("voice.provider_"):
        return "speech"
    elif capability_id.startswith("document.provider_"):
        return "document"
    elif capability_id == "chat.respond":
        return "chat"
    elif capability_id == "coding.plan_change":
        return "coding"
    else:
        # Default to vision for unknown provider capabilities that might be ChatRequest-based
        return "vision"


# ========================================================================
# Factory Functions
# ========================================================================

def _build_vision_request(context: ProviderRequestContext) -> ChatRequest:
    """Build ChatRequest for vision/video provider capabilities."""
    instruction = context.task_inputs.get("instruction", "")
    images_base64 = context.task_inputs.get("images_base64") or context.task_inputs.get("frames_base64") or ()
    
    # Ensure images_base64 is a tuple
    if isinstance(images_base64, str):
        images_base64 = (images_base64,)
    elif not isinstance(images_base64, (tuple, list)):
        images_base64 = ()
    
    return ChatRequest(
        messages=(
            ChatMessage(
                role="user",
                content=instruction,
                images=tuple(images_base64),
            ),
        ),
    )


def _build_generation_request(context: ProviderRequestContext) -> GenerationRequest:
    """Build GenerationRequest for image/video generation capabilities."""
    inputs = context.task_inputs
    metadata = context.task_metadata
    
    # Determine operation from inputs or metadata
    operation_str = inputs.get("operation") or metadata.get("generation_operation")
    if not operation_str:
        # Infer from capability_id pattern
        cap_id = context.resolution.definition.id
        if "video" in cap_id:
            if "image" in inputs:
                operation_str = "video_generate_from_image"
            else:
                operation_str = "video_generate"
        else:
            operation_str = "image_generate"
    
    try:
        operation = GenerationOperation(operation_str)
    except ValueError:
        # Default fallback
        operation = GenerationOperation.IMAGE_GENERATE
    
    return GenerationRequest(
        operation=operation,
        prompt=inputs.get("prompt", ""),
        negative_prompt=inputs.get("negative_prompt", ""),
        input_images=tuple(inputs.get("input_images", ())),
        width=inputs.get("width"),
        height=inputs.get("height"),
        duration_seconds=inputs.get("duration_seconds"),
        fps=inputs.get("fps"),
        seed=inputs.get("seed"),
    )


def _build_ocr_request(context: ProviderRequestContext) -> ChatRequest:
    """Build ChatRequest for OCR provider capabilities."""
    instruction = context.task_inputs.get("instruction", "Extract every piece of text visible in this image, verbatim.")
    image_base64 = context.task_inputs.get("image_base64", "")
    
    return ChatRequest(
        messages=(
            ChatMessage(
                role="user",
                content=instruction,
                images=(image_base64,) if image_base64 else (),
            ),
        ),
    )


def _build_speech_request(context: ProviderRequestContext) -> SpeechRequest:
    """Build SpeechRequest for speech-to-text or text-to-speech."""
    inputs = context.task_inputs
    metadata = context.task_metadata
    
    # Determine operation from inputs or metadata
    operation_str = inputs.get("operation") or metadata.get("speech_operation")
    if not operation_str:
        cap_id = context.resolution.definition.id
        if "text_to_speech" in cap_id or "tts" in cap_id:
            operation_str = "text_to_speech"
        else:
            operation_str = "speech_to_text"
    
    try:
        operation = SpeechOperation(operation_str)
    except ValueError:
        operation = SpeechOperation.SPEECH_TO_TEXT
    
    if operation == SpeechOperation.SPEECH_TO_TEXT:
        return SpeechRequest(
            operation=operation,
            audio_base64=inputs.get("audio_base64", ""),
            audio_mime_type=inputs.get("audio_mime_type"),
            language=inputs.get("language"),
        )
    else:  # TEXT_TO_SPEECH
        return SpeechRequest(
            operation=operation,
            text=inputs.get("text", ""),
            voice=inputs.get("voice"),
            language=inputs.get("language"),
        )


def _build_document_request(context: ProviderRequestContext) -> ChatRequest:
    """Build ChatRequest for document analysis."""
    instruction = context.task_inputs.get("instruction", "")
    content = context.task_inputs.get("content", "")
    
    return ChatRequest(
        messages=(
            ChatMessage(
                role="user",
                content=f"{instruction}\n\n---\n\n{content}" if content else instruction,
            ),
        ),
    )


# ========================================================================
# Factory Registry (not a registry in the architectural sense - just a
# simple dict mapping string keys to factory functions)
# ========================================================================

_PROVIDER_FACTORIES: dict[str, callable] = {
    "vision": _build_vision_request,
    "ocr": _build_ocr_request,
    "generation": _build_generation_request,
    "speech": _build_speech_request,
    "document": _build_document_request,
}


# Explicitly unsupported - these require interactive/runtime context
_UNSUPPORTED_AUTONOMOUS_TYPES = frozenset({
    "chat",
    "coding",
})


def is_supported_autonomous_provider(provider_request_type: str) -> bool:
    """Check if a provider request type is supported for autonomous execution."""
    return provider_request_type in _PROVIDER_FACTORIES


def get_supported_provider_types() -> frozenset[str]:
    """Get the set of supported provider request types for autonomous execution."""
    return frozenset(_PROVIDER_FACTORIES.keys())


def get_unsupported_provider_types() -> frozenset[str]:
    """Get the set of explicitly unsupported provider request types."""
    return _UNSUPPORTED_AUTONOMOUS_TYPES