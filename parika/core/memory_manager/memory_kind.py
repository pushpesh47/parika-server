"""
PARIKA Memory Kinds

Defines the supported classifications for persistent memories managed by
the MemoryManager.

This module contains only the MemoryKind enumeration. The enumeration
provides a stable, strongly typed classification for Memory instances and
carries no behavior, lifecycle, retrieval, or business logic.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryKind(StrEnum):
    """
    Classification of persistent memory.

    The memory kind identifies the general nature of a retained Memory.
    It is descriptive only and does not influence storage, retrieval,
    persistence, lifecycle, or business behavior.
    """

    FACT = "fact"
    PREFERENCE = "preference"

    # Retained only for backward compatibility with pre-existing Memory
    # rows. New execution-outcome data must be written through the
    # Experience Module's ExperienceStore (see
    # docs/architecture/Intelligence_Foundation_Design.md, section 6A),
    # never through MemoryManager with this kind.
    EXPERIENCE = "experience"

    DECISION = "decision"
    OBSERVATION = "observation"
    SUMMARY = "summary"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    CONVERSATION = "conversation"