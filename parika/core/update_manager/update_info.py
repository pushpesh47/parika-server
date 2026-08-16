"""
PARIKA Update Info

Defines the immutable UpdateInfo describing an available update,
produced by a target's registered check callable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class UpdateInfo:
    """
    Immutable description of an available update.

    An UpdateInfo is produced by a target's check callable and
    consumed, unmodified, by that target's apply callable.
    UpdateManager never interprets its contents.
    """

    current_version: str
    """
    Version currently installed for the target.
    """

    available_version: str
    """
    Version available to update to.
    """

    notes: str | None = None
    """
    Optional human-readable release notes or summary.
    """
