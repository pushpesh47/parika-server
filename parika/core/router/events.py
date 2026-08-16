"""
PARIKA Router Events

Defines the immutable events published by Router.

Events are immutable data containers and carry no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class RouteRegisteredEvent:
    """Published after a route has been registered."""

    route_id: str
    """Identifier of the registered route."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RouteUnregisteredEvent:
    """Published after a route has been unregistered."""

    route_id: str
    """Identifier of the unregistered route."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchStartedEvent:
    """Published when dispatch to a selected route begins."""

    route_id: str
    """Identifier of the selected route."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchCompletedEvent:
    """Published after a route's handler completes successfully."""

    route_id: str
    """Identifier of the dispatched route."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchFailedEvent:
    """Published when a route's handler raises an exception."""

    route_id: str
    """Identifier of the dispatched route."""

    reason: str
    """Description of the failure."""
