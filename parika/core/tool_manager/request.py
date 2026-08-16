"""
PARIKA Tool request.

This module defines the immutable ToolRequest model used by ToolManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """
    Immutable execution request passed to a ToolDriver.
    """

    arguments: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Tool-specific input arguments.
    """

    parameters: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Optional execution parameters.

    Examples:
        timeout
        encoding
        recursive
    """

    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Optional caller metadata.

    ToolManager does not interpret the contents of this mapping.
    """

    def __post_init__(self) -> None:
        """
        Guarantee immutability.
        """

        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(dict(self.arguments)),
        )

        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )