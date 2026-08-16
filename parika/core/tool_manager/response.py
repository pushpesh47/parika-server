"""
PARIKA Tool response.

This module defines the immutable ToolResponse model returned by ToolDriver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ToolResponse:
    """
    Immutable execution response returned by a ToolDriver.
    """

    result: object | None = None
    """
    Tool execution result.
    """

    attributes: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Optional execution attributes.

    Examples:
        bytes_read
        row_count
        mime_type
        encoding
    """

    def __post_init__(self) -> None:
        """
        Guarantee immutability.
        """

        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )