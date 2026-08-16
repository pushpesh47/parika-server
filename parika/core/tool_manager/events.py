"""
PARIKA ToolManager events.

This module defines immutable event payloads published by ToolManager.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import ToolExecutionError
from .request import ToolRequest
from .response import ToolResponse


@dataclass(frozen=True, slots=True)
class ToolRegistered:
    """
    Published after a tool has been successfully registered.
    """

    tool_id: str


@dataclass(frozen=True, slots=True)
class ToolUnregistered:
    """
    Published after a tool has been successfully unregistered.
    """

    tool_id: str


@dataclass(frozen=True, slots=True)
class ToolExecuted:
    """
    Published after a tool has executed successfully.
    """

    tool_id: str
    request: ToolRequest
    response: ToolResponse


@dataclass(frozen=True, slots=True)
class ToolExecutionFailed:
    """
    Published after a tool execution fails.
    """

    tool_id: str
    request: ToolRequest
    exception: ToolExecutionError