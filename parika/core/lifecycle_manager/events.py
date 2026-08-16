"""
PARIKA Lifecycle Events

Defines the immutable lifecycle events published by LifecycleManager.

These events notify the EventBus whenever the PARIKA application
transitions between initialization, startup, shutdown, restart, or
reload phases. Events are immutable data containers and carry no
business logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleInitializedEvent:
    """Published after application initialization completes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleStartedEvent:
    """Published after the application has started."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleStartFailedEvent:
    """Published when application startup fails."""

    reason: str
    """Description of the startup failure."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleStoppedEvent:
    """Published after the application has stopped."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleReloadedEvent:
    """Published after a reload completes successfully."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleReloadFailedEvent:
    """Published when a reload fails."""

    reason: str
    """Description of the reload failure."""
