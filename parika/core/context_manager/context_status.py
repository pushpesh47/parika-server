"""
PARIKA Context Status

Defines the lifecycle states for runtime contexts managed by the
ContextManager.

This module contains only the ContextStatus enumeration. The enumeration
represents the current lifecycle state of a Context and contains no
transition logic or business behavior.
"""

from __future__ import annotations

from enum import StrEnum


class ContextStatus(StrEnum):
    """
    Lifecycle status of a runtime context.

    The status represents the current lifecycle state of a Context.
    It is descriptive only and does not define or enforce state
    transitions.
    """

    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"