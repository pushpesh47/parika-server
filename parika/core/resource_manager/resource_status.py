from __future__ import annotations

from enum import Enum


class ResourceStatus(Enum):
    """Represents the availability of resource information."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"