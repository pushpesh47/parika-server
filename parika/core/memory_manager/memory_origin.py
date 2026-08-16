"""
PARIKA Memory Origins

Defines the supported origins for persistent memories managed by the
MemoryManager.

This module contains only the MemoryOrigin enumeration. The enumeration
describes how a Memory entered the persistent memory system and carries
no behavior, lifecycle, persistence, or business logic.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryOrigin(StrEnum):
    """
    Origin of persistent memory.

    The memory origin identifies how a Memory was created or entered
    the persistent memory repository. It is descriptive only and does
    not influence storage, retrieval, lifecycle, or business behavior.
    """

    USER_EXPLICIT = "user_explicit"
    SYSTEM_LEARNED = "system_learned"
    MODULE_CREATED = "module_created"
    IMPORTED = "imported"