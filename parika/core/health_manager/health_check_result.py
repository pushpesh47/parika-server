"""
PARIKA Health Check Result

Defines the immutable result produced by a health check callable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .health_status import HealthStatus


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class HealthCheckResult:
    """
    Immutable outcome of a single health check invocation.

    A HealthCheckResult is produced by a registered health check
    callable and reports the observed status of a component at a
    single point in time.
    """

    status: HealthStatus
    """
    Observed health status.
    """

    message: str | None = None
    """
    Optional human-readable description of the observed status.
    """

    checked_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the check was performed.
    """
