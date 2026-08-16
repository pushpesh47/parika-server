"""
PARIKA Health Status

Defines the health states used to describe the operational health of
a registered component.

The health status is descriptive only and does not define or enforce
recovery behavior. Recovery coordination is performed by
HealthManager.
"""

from __future__ import annotations

from enum import StrEnum


class HealthStatus(StrEnum):
    """
    Operational health state of a component.
    """

    UNKNOWN = "unknown"
    """No health check or heartbeat has been recorded yet."""

    HEALTHY = "healthy"
    """The component is operating normally."""

    DEGRADED = "degraded"
    """The component is operating with reduced capability."""

    UNHEALTHY = "unhealthy"
    """The component has failed its health check or heartbeat."""
