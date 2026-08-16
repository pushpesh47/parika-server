"""
PARIKA Knowledge Source Status

Defines the lifecycle states of a KnowledgeSource.

The source status describes the operational availability of a knowledge
source. It is intentionally independent from indexing, parsing, and search
state, which are managed separately by the KnowledgeEngine.

Lifecycle
---------
REGISTERED
    ↓
AVAILABLE
    ↕
DISABLED
    ↓
REMOVED

Notes
-----
KnowledgeSourceStatus intentionally does NOT represent:

- Indexing progress
- Search availability
- Parsing state
- Processing failures

Those belong to the processing lifecycle rather than the source lifecycle.
"""

from __future__ import annotations

from enum import StrEnum


class KnowledgeSourceStatus(StrEnum):
    """
    Lifecycle status of a KnowledgeSource.
    """

    REGISTERED = "registered"
    """The source is registered but has not yet been made available."""

    AVAILABLE = "available"
    """The source is active and available for knowledge extraction and search."""

    DISABLED = "disabled"
    """The source is temporarily unavailable but remains registered."""

    REMOVED = "removed"
    """The source has been permanently removed from the KnowledgeManager."""