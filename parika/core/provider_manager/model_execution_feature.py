"""
PARIKA Core - ProviderManager Component

Defines the execution features supported by a ProviderModel.

A ModelExecutionFeature represents *how* a model can execute requests.
These features describe execution mechanics and interaction capabilities
rather than the intrinsic intelligence of the model.

Examples:
    - STREAMING
    - TOOL_CALLING
    - STRUCTURED_OUTPUT

Intrinsic AI capabilities such as reasoning, coding, and vision are
represented separately by ModelCapability.
"""

from __future__ import annotations

from enum import StrEnum


class ModelExecutionFeature(StrEnum):
    """
    Execution features supported by a ProviderModel.

    These features describe how a model can be interacted with or how
    it executes requests. They are independent of the model's intrinsic
    AI capabilities.

    Notes:
        - Provider execution features are derived from the union of the
          execution features of all registered ProviderModel instances.
        - Execution features are transport and interaction capabilities,
          not AI competencies.
    """

    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    JSON_OUTPUT = "json_output"
    MULTIMODAL_INPUT = "multimodal_input"
    MULTIMODAL_OUTPUT = "multimodal_output"