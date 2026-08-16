"""
Immutable capability resolution request.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityRequest:
    """
    Immutable request to resolve a capability.

    A capability request represents the planner's intent to use a
    specific capability. It contains only information required for
    capability resolution and remains independent of providers,
    models, resources, policies, and execution.
    """

    capability_id: str

    metadata: MappingProxyType[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        """
        Guarantee immutability of the metadata mapping.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )