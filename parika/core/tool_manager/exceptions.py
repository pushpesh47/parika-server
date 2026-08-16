"""
PARIKA ToolManager exceptions.

This module defines the exception hierarchy used by the ToolManager component.
"""

from __future__ import annotations


class ToolError(Exception):
    """
    Base exception for all ToolManager-related errors.
    """


class ToolRegistrationError(ToolError):
    """
    Raised when a tool cannot be registered.
    """


class ToolAlreadyRegisteredError(ToolRegistrationError):
    """
    Raised when attempting to register a tool that already exists.
    """


class ToolNotFoundError(ToolError):
    """
    Raised when a requested tool cannot be found.
    """


class ToolDisabledError(ToolError):
    """
    Raised when attempting to execute a disabled tool.
    """


class ToolExecutionError(ToolError):
    """
    Raised when tool execution fails.
    """


class InvalidToolRequestError(ToolError):
    """
    Raised when a ToolRequest is invalid.
    """


class InvalidToolError(ToolError):
    """
    Raised when a Tool definition is invalid.
    """