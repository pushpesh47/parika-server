"""
Memory manager events.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory import Memory


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRegisteredEvent:
    """
    Published after a memory has been successfully registered.
    """

    memory: Memory


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryUpdatedEvent:
    """
    Published after a memory has been successfully updated.
    """

    memory: Memory


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRemovedEvent:
    """
    Published after a memory has been successfully removed.
    """

    memory: Memory