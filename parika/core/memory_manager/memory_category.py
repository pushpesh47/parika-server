"""
PARIKA Memory Category

Defines the supported content-domain categories for persistent
memories managed by the MemoryManager.

`MemoryCategory` is orthogonal to `MemoryKind`: `MemoryKind` describes
a memory's temporal/lifecycle nature (short-term, long-term, episodic,
semantic, conversation, summary, ...), while `MemoryCategory`
describes *what domain of information about the user* a memory
represents (profile, preference, relationship, goal, ...), independent
of its lifecycle. Every permanent memory belongs to exactly one
category.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryCategory(StrEnum):
    """Content-domain classification of a persistent memory."""

    PROFILE = "profile"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    GOAL = "goal"
    PROJECT = "project"
    SKILL = "skill"
    FACT = "fact"
    REMINDER_REFERENCE = "reminder_reference"
    CUSTOM = "custom"
