"""
PARIKA Health Manager Events

Defines the immutable lifecycle events published by HealthManager.

Events notify the EventBus whenever a component is registered or
unregistered, whenever its observed health status changes, and
whenever recovery is coordinated for an unhealthy component. Events
are immutable data containers and carry no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .health_status import HealthStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentRegisteredEvent:
    """Published after a component has been registered."""

    component_id: str
    """Identifier of the registered component."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentUnregisteredEvent:
    """Published after a component has been unregistered."""

    component_id: str
    """Identifier of the unregistered component."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentHealthChangedEvent:
    """Published when a component's observed health status changes."""

    component_id: str
    """Identifier of the component."""

    previous_status: HealthStatus
    """Status observed prior to this change."""

    current_status: HealthStatus
    """Newly observed status."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentRecoveryTriggeredEvent:
    """Published when recovery coordination is triggered for a
    component."""

    component_id: str
    """Identifier of the unhealthy component."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentRecoveryFailedEvent:
    """Published when a recovery hook raises an unhandled
    exception."""

    component_id: str
    """Identifier of the component."""
