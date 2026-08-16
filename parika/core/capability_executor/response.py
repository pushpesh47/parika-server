"""
PARIKA Capability Execution Response

Defines the immutable execution response returned by
CapabilityExecutor.

A CapabilityExecutionResponse encapsulates the normalized execution
result returned by CapabilityExecutor. It contains the backend-specific
response produced by the selected execution backend together with
implementation-neutral execution metadata and the reported execution
duration.

This response is an immutable value object and carries no runtime state
or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from parika.core.provider_manager import ProviderResponse
from parika.core.tool_manager.response import ToolResponse


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class CapabilityExecutionResponse:
    """
    Immutable capability execution response.

    A CapabilityExecutionResponse represents the execution result
    returned by CapabilityExecutor. It wraps the backend-specific
    response returned by ToolManager or ProviderManager together with
    implementation-neutral execution metadata.
    """

    backend_response: ToolResponse | ProviderResponse
    """
    Backend-specific execution response.

    This is the immutable response returned by the selected execution
    backend. CapabilityExecutor forwards this response without
    interpreting or modifying its contents.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Optional implementation-neutral execution metadata.

    CapabilityExecutor does not interpret or modify these values.
    """

    duration_seconds: float | None = None
    """
    Backend-reported execution duration in seconds.

    This value represents only the execution duration reported by the
    selected execution backend and is independent of Task lifecycle
    timestamps maintained by TaskManager.
    """

    def __post_init__(self) -> None:
        """
        Convert mutable mappings into immutable mapping proxies.

        Defensive copies are created to ensure
        CapabilityExecutionResponse remains deeply immutable even if
        mutable dictionaries are supplied by callers.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )