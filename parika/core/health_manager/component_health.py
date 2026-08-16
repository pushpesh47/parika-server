"""
PARIKA Component Health

Defines the mutable runtime health record maintained by HealthManager
for a single registered component.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .health_check_result import HealthCheckResult
from .health_status import HealthStatus


@dataclass(slots=True, kw_only=True)
class ComponentHealth:
    """
    Mutable runtime health record for a registered component.

    A ComponentHealth tracks the most recently observed status of a
    single component together with heartbeat and failure bookkeeping
    required for failure detection. It is created, managed, and
    destroyed exclusively by HealthManager and contains no business
    logic.
    """

    component_id: str
    """
    Identifier of the monitored component.
    """

    status: HealthStatus = HealthStatus.UNKNOWN
    """
    Most recently observed health status.
    """

    last_result: HealthCheckResult | None = None
    """
    Most recent HealthCheckResult produced by a health check, if any.
    """

    last_heartbeat_at: datetime | None = None
    """
    Timestamp of the most recently received heartbeat, if any.
    """

    consecutive_failures: int = 0
    """
    Number of consecutive non-healthy observations.
    """

    metadata: MutableMapping[str, Any] = field(
        default_factory=dict,
    )
    """
    Mutable implementation-neutral runtime metadata.

    HealthManager does not assign semantics to these values.
    """
