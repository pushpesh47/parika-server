"""
PARIKA Tool definition.

This module defines the immutable Tool model used by ToolManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .exceptions import InvalidToolError


@dataclass(frozen=True, slots=True)
class Tool:
    """
    Immutable metadata describing a deterministic executable tool.

    A Tool contains only descriptive information about a tool.
    It does not contain executable logic.
    """

    id: str
    """
    Unique tool identifier.

    Examples:
        filesystem.read
        pdf.extract_text
        git.commit
    """

    name: str
    """
    Human-readable tool name.
    """

    version: str
    """
    Tool version.
    """

    description: str
    """
    Human-readable description.
    """

    capabilities: tuple[str, ...] = field(default_factory=tuple)
    """
    Capability identifiers implemented by this tool.
    """

    enabled: bool = True
    """
    Indicates whether this tool is enabled.
    """

    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Optional implementation-specific metadata.

    ToolManager does not interpret the contents of this mapping.
    """

    def __post_init__(self) -> None:
        """
        Validate tool invariants and guarantee immutability.
        """

        if not self.id.strip():
            raise InvalidToolError("Tool id cannot be empty.")

        if not self.name.strip():
            raise InvalidToolError("Tool name cannot be empty.")

        if not self.version.strip():
            raise InvalidToolError("Tool version cannot be empty.")

        if not self.description.strip():
            raise InvalidToolError("Tool description cannot be empty.")

        # Ensure capabilities are immutable.
        capabilities = tuple(self.capabilities)
        object.__setattr__(self, "capabilities", capabilities)

        # Validate capability identifiers.
        for capability in capabilities:
            if not capability.strip():
                raise InvalidToolError(
                    "Capability identifiers cannot be empty."
                )

        # Ensure capability identifiers are unique.
        if len(capabilities) != len(set(capabilities)):
            raise InvalidToolError(
                "Duplicate capability identifiers are not allowed."
            )

        # Create an immutable copy of metadata.
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )