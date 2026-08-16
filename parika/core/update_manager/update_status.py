"""
PARIKA Update Status

Defines the update states of a registered UpdateManager target.

The update status describes the current state of a single update
target during its runtime lifecycle. It is descriptive only and does
not define or enforce update behavior.
"""

from __future__ import annotations

from enum import StrEnum


class UpdateStatus(StrEnum):
    """
    Current update state of a registered target.
    """

    UNKNOWN = "unknown"
    """No update check has been performed yet."""

    UP_TO_DATE = "up_to_date"
    """The most recent check found no available update."""

    UPDATE_AVAILABLE = "update_available"
    """The most recent check found an available update."""

    UPDATING = "updating"
    """An update is currently being applied."""

    UPDATED = "updated"
    """The most recent update was applied successfully."""

    FAILED = "failed"
    """The most recent update attempt failed."""
