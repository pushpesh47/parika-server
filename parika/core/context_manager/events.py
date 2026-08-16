"""
PARIKA Context Events

Immutable event models published by the ContextManager.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextRegistered:
    """
    Published after a Context has been successfully registered.
    """

    context_id: str

    def __post_init__(self) -> None:
        if not self.context_id or not self.context_id.strip():
            raise ValueError("Context ID cannot be empty.")


@dataclass(frozen=True, slots=True)
class ContextUpdated:
    """
    Published after a Context has been successfully updated.
    """

    context_id: str

    def __post_init__(self) -> None:
        if not self.context_id or not self.context_id.strip():
            raise ValueError("Context ID cannot be empty.")


@dataclass(frozen=True, slots=True)
class ContextRemoved:
    """
    Published after a Context has been successfully removed.
    """

    context_id: str

    def __post_init__(self) -> None:
        if not self.context_id or not self.context_id.strip():
            raise ValueError("Context ID cannot be empty.")