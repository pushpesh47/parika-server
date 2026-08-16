"""
PARIKA Core - ProviderManager Component

Defines the intrinsic artificial intelligence capabilities that a
ProviderModel can support.

A ModelCapability represents *what* a model is capable of doing from an
AI perspective. It does not represent execution mechanics, transport
features, runtime state, or provider-specific functionality.

Examples:
    - TEXT_GENERATION
    - REASONING
    - CODING
    - VISION
    - EMBEDDING

Execution mechanics such as streaming, tool calling, and structured
output are represented separately by ModelExecutionFeature.
"""

from __future__ import annotations

from enum import StrEnum


class ModelCapability(StrEnum):
    """
    Intrinsic AI capabilities supported by a ProviderModel.

    These capabilities describe *what* intelligence a model possesses,
    independent of any provider-specific implementation.

    Notes:
        - Provider capabilities are derived from the union of the
          capabilities of all registered ProviderModel instances.
        - Execution features are intentionally excluded and represented
          separately by ModelExecutionFeature.
    """

    TEXT_GENERATION = "text_generation"
    REASONING = "reasoning"
    CODING = "coding"
    VISION = "vision"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    EMBEDDING = "embedding"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    TRANSLATION = "translation"
    RERANKING = "reranking"
    MODERATION = "moderation"