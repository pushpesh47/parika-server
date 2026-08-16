"""
PARIKA Core - ProviderManager Component

Defines the immutable health information of a provider.

ProviderHealth represents the current operational health reported by a
ProviderDriver. It contains normalized health information that is
provider-independent and can be safely consumed by the rest of the
PARIKA Core.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """
    Immutable health information for a provider.

    Attributes:
        available:
            Indicates whether the provider is currently available to
            accept requests.

        latency_ms:
            Measured round-trip latency in milliseconds.
            None indicates that latency is unknown or was not measured.

        message:
            Optional human-readable health message describing the current
            provider status.
    """

    available: bool
    latency_ms: float | None = None
    message: str | None = None