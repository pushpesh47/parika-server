"""
PARIKA Update Manager Events

Defines the immutable events published by UpdateManager.

Events are immutable data containers and carry no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .update_info import UpdateInfo


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetRegisteredEvent:
    """Published after an update target has been registered."""

    target_id: str
    """Identifier of the registered target."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetUnregisteredEvent:
    """Published after an update target has been unregistered."""

    target_id: str
    """Identifier of the unregistered target."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateAvailableEvent:
    """Published when a check finds an available update."""

    target_id: str
    """Identifier of the target."""

    info: UpdateInfo
    """Description of the available update."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateUpToDateEvent:
    """Published when a check finds no available update."""

    target_id: str
    """Identifier of the target."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateAppliedEvent:
    """Published after an update has been applied successfully."""

    target_id: str
    """Identifier of the target."""

    info: UpdateInfo
    """Description of the applied update."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateFailedEvent:
    """Published when applying an update fails."""

    target_id: str
    """Identifier of the target."""

    reason: str
    """Description of the failure."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationAppliedEvent:
    """Published after a configuration migration has been applied."""

    version: str
    """Version identifier of the applied migration."""
