"""
PARIKA Metrics Manager

Provides the core component responsible for collecting runtime
metrics for monitoring and optimization.

MetricsManager maintains in-memory counters, gauges, and aggregated
timing statistics. It performs only numeric bookkeeping and assigns
no semantic meaning to metric names or values.

MetricsManager does not write application logs (owned by Logger) and
does not monitor component health (owned by HealthManager).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from types import MappingProxyType

from .exceptions import InvalidMetricNameError, InvalidMetricValueError
from .timing_stats import TimingStats


@dataclass(slots=True)
class _TimingAccumulator:
    """
    Mutable internal accumulator backing a single TimingStats series.
    """

    count: int = 0
    total_seconds: float = 0.0
    min_seconds: float = 0.0
    max_seconds: float = 0.0

    def record(self, duration_seconds: float) -> None:
        if self.count == 0:
            self.min_seconds = duration_seconds
            self.max_seconds = duration_seconds
        else:
            self.min_seconds = min(self.min_seconds, duration_seconds)
            self.max_seconds = max(self.max_seconds, duration_seconds)

        self.count += 1
        self.total_seconds += duration_seconds

    def snapshot(self) -> TimingStats:
        return TimingStats(
            count=self.count,
            total_seconds=self.total_seconds,
            min_seconds=self.min_seconds,
            max_seconds=self.max_seconds,
        )


class MetricsManager:
    """
    Collects runtime metrics for monitoring and optimization.

    MetricsManager owns in-memory counters, gauges, and aggregated
    timing statistics. It performs only numeric bookkeeping and does
    not interpret the meaning of the metrics it stores.

    MetricsManager intentionally does not:

    - Write application logs. That belongs to Logger.
    - Monitor component health. That belongs to HealthManager.
    """

    def __init__(self) -> None:
        """
        Initialize the MetricsManager.
        """

        self._lock = RLock()

        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._timings: dict[str, _TimingAccumulator] = {}

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def increment(self, name: str, value: float = 1.0) -> float:
        """
        Increment a named counter.

        Args:
            name:
                Counter name.

            value:
                Amount to add to the counter. May be negative to
                decrement.

        Returns:
            The counter's new cumulative value.

        Raises:
            InvalidMetricNameError:
                If `name` is empty.
        """

        self._validate_name(name)

        with self._lock:
            updated = self._counters.get(name, 0.0) + value
            self._counters[name] = updated
            return updated

    def get_counter(self, name: str) -> float:
        """
        Return the current value of a counter.

        Returns 0.0 if the counter has never been incremented.
        """

        with self._lock:
            return self._counters.get(name, 0.0)

    def get_all_counters(self) -> Mapping[str, float]:
        """
        Return every counter and its current value.
        """

        with self._lock:
            return MappingProxyType(dict(self._counters))

    # ------------------------------------------------------------------
    # Gauges
    # ------------------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        """
        Set a named gauge to an absolute value.

        Args:
            name:
                Gauge name.

            value:
                New gauge value.

        Raises:
            InvalidMetricNameError:
                If `name` is empty.
        """

        self._validate_name(name)

        with self._lock:
            self._gauges[name] = value

    def get_gauge(self, name: str) -> float | None:
        """
        Return the current value of a gauge, or None if unset.
        """

        with self._lock:
            return self._gauges.get(name)

    def get_all_gauges(self) -> Mapping[str, float]:
        """
        Return every gauge and its current value.
        """

        with self._lock:
            return MappingProxyType(dict(self._gauges))

    # ------------------------------------------------------------------
    # Timings
    # ------------------------------------------------------------------

    def record_timing(self, name: str, duration_seconds: float) -> None:
        """
        Record a single duration observation for a named timing
        metric.

        Args:
            name:
                Timing metric name.

            duration_seconds:
                Observed duration, in seconds. Must not be negative.

        Raises:
            InvalidMetricNameError:
                If `name` is empty.

            InvalidMetricValueError:
                If `duration_seconds` is negative.
        """

        self._validate_name(name)

        if duration_seconds < 0:
            raise InvalidMetricValueError(
                "duration_seconds must not be negative."
            )

        with self._lock:
            accumulator = self._timings.setdefault(
                name,
                _TimingAccumulator(),
            )
            accumulator.record(duration_seconds)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """
        Context manager that records the elapsed wall-clock time of
        the wrapped block as a timing observation.

        The duration is recorded even if the wrapped block raises.

        Args:
            name:
                Timing metric name.
        """

        started_at = perf_counter()

        try:
            yield

        finally:
            self.record_timing(name, perf_counter() - started_at)

    def get_timing_stats(self, name: str) -> TimingStats | None:
        """
        Return aggregated statistics for a timing metric, or None if
        no durations have been recorded under that name.
        """

        with self._lock:
            accumulator = self._timings.get(name)

            if accumulator is None:
                return None

            return accumulator.snapshot()

    def get_all_timings(self) -> Mapping[str, TimingStats]:
        """
        Return aggregated statistics for every timing metric.
        """

        with self._lock:
            return MappingProxyType(
                {
                    name: accumulator.snapshot()
                    for name, accumulator in self._timings.items()
                }
            )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def reset(self, name: str | None = None) -> None:
        """
        Clear recorded metrics.

        Args:
            name:
                If supplied, clears only the counter, gauge, and
                timing metric registered under this name. Otherwise
                clears every recorded metric.
        """

        with self._lock:
            if name is None:
                self._counters.clear()
                self._gauges.clear()
                self._timings.clear()
                return

            self._counters.pop(name, None)
            self._gauges.pop(name, None)
            self._timings.pop(name, None)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _validate_name(self, name: str) -> None:
        """
        Validate a metric name.

        Raises:
            InvalidMetricNameError:
                If `name` is empty or not a string.
        """

        if not isinstance(name, str) or not name:
            raise InvalidMetricNameError(
                "Metric name must be a non-empty string."
            )
