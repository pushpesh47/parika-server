"""
PARIKA Timing Statistics

Defines the immutable aggregated timing statistics returned by
MetricsManager for a named timing metric.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TimingStats:
    """
    Immutable aggregated statistics for a named timing metric.

    TimingStats summarizes every duration recorded under a single
    metric name without retaining individual samples.
    """

    count: int
    """
    Number of durations recorded.
    """

    total_seconds: float
    """
    Sum of every recorded duration, in seconds.
    """

    min_seconds: float
    """
    Smallest recorded duration, in seconds.
    """

    max_seconds: float
    """
    Largest recorded duration, in seconds.
    """

    @property
    def average_seconds(self) -> float:
        """
        Average recorded duration, in seconds.

        Returns 0.0 when no durations have been recorded.
        """

        if self.count == 0:
            return 0.0

        return self.total_seconds / self.count
