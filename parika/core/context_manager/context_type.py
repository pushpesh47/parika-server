"""
PARIKA Context Types

Defines the supported classifications for runtime contexts managed by
the ContextManager.

This module contains only the ContextType enumeration. The enumeration
provides a stable, strongly typed classification for Context instances
and carries no behavior or business logic.
"""

from __future__ import annotations

from enum import StrEnum


class ContextType(StrEnum):
    """
    Classification of runtime context.

    The context type identifies the origin or purpose of a Context.
    It is descriptive only and does not influence lifecycle,
    execution, routing, or business logic.
    """

    INTERACTION = "interaction"
    MODULE = "module"
    SCHEDULED = "scheduled"
    SYSTEM = "system"
    TASK = "task"
    TOOL = "tool"
    WORKFLOW = "workflow"