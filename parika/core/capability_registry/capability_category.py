"""
Capability categories supported by PARIKA.
"""

from enum import StrEnum


class CapabilityCategory(StrEnum):
    """
    Standard capability categories used to classify capabilities.
    """

    LLM = "llm"
    EMBEDDING = "embedding"

    VISION = "vision"
    OCR = "ocr"
    SPEECH = "speech"
    TRANSLATION = "translation"

    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    TEXT_TO_SPEECH = "text_to_speech"

    MEMORY = "memory"
    KNOWLEDGE = "knowledge"

    TOOL = "tool"

    AUTOMATION = "automation"
    WORKFLOW = "workflow"

    REASONING = "reasoning"
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    COMMUNICATION = "communication"

    FILESYSTEM = "filesystem"
    NETWORK = "network"
    SYSTEM = "system"

    CUSTOM = "custom"