"""
PARIKA Tool driver.

This module defines the ToolDriver protocol implemented by all
deterministic tool implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .request import ToolRequest
from .response import ToolResponse


@runtime_checkable
class ToolDriver(Protocol):
    """
    Protocol implemented by every deterministic tool.

    A ToolDriver encapsulates the executable logic of a single Tool.
    """

    def execute(
        self,
        request: ToolRequest,
    ) -> ToolResponse:
        """
        Execute the tool.

        Args:
            request:
                Immutable execution request.

        Returns:
            Immutable execution response.

        Raises:
            ToolExecutionError:
                If execution fails.
        """
        ...