"""
PARIKA Memory Scope

Defines the supported scoping levels for persistent memories managed by
the MemoryManager.

This module contains only the MemoryScope enumeration. The enumeration
provides a stable, strongly typed scope classification for Memory
instances and carries no behavior, retrieval, or business logic.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryScope(StrEnum):
    """
    Scope of a persistent memory.

    The memory scope identifies how broadly a Memory applies. It is used
    by MemoryManager to filter and retrieve memories by scope, and does
    not itself influence storage or persistence mechanics.
    """

    SESSION = "session"
    USER = "user"
    WORKSPACE = "workspace"
    GLOBAL = "global"
