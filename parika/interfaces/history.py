"""
PARIKA Interfaces - History

Defines the immutable `HistoryEntry` recorded by an `InterfaceSession`
for every user input, assistant response, slash command, and error
that occurs during a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class HistoryRole(StrEnum):
    """
    Origin of a single recorded history entry.
    """

    USER = "user"
    ASSISTANT = "assistant"
    COMMAND = "command"
    ERROR = "error"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoryEntry:
    """
    Immutable record of a single session interaction.
    """

    role: HistoryRole
    """
    Origin of this entry.
    """

    text: str
    """
    Recorded text.
    """

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when this entry was recorded.
    """
