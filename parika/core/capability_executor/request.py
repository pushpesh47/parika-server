"""
PARIKA Capability Execution Request

Defines the immutable execution plan consumed by
CapabilityExecutor.

A CapabilityExecutionRequest represents a fully planned execution
prepared by Planner. It combines the resolved capability together with
the selected execution target and the backend-specific request required
to execute the capability.

CapabilityExecutor performs no routing or planning. It executes the
prepared request exactly as provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from parika.core.capability_resolver import CapabilityResolution
from parika.core.provider_manager import ProviderRequest
from parika.core.tool_manager.request import ToolRequest

from .execution_target import ExecutionTarget


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class CapabilityExecutionRequest:
    """
    Immutable execution plan for CapabilityExecutor.

    A CapabilityExecutionRequest represents the finalized execution plan
    produced by Planner. It contains the resolved capability, selected
    execution target, and the backend-specific request required for
    execution.
    """

    resolution: CapabilityResolution
    """
    Resolved capability produced by CapabilityResolver.
    """

    target: ExecutionTarget
    """
    Selected execution target.
    """

    backend_request: ToolRequest | ProviderRequest
    """
    Prepared backend-specific execution request.

    Planner constructs this request before execution begins.
    CapabilityExecutor forwards it unchanged to the selected execution
    backend.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Optional implementation-neutral execution metadata.

    CapabilityExecutor does not interpret or modify these values.
    """

    def __post_init__(self) -> None:
        """
        Convert mutable mappings into immutable mapping proxies.

        Defensive copies are created to ensure
        CapabilityExecutionRequest remains deeply immutable even if
        mutable dictionaries are supplied by callers.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )