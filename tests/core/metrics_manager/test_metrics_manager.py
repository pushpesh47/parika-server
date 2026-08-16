"""
Unit tests for MetricsManager.
"""

from __future__ import annotations

import time

import pytest

from parika.core.metrics_manager.exceptions import (
    InvalidMetricNameError,
    InvalidMetricValueError,
)
from parika.core.metrics_manager.metrics_manager import MetricsManager


@pytest.fixture
def metrics_manager() -> MetricsManager:
    return MetricsManager()


# ---------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------


class TestCounters:
    def test_increment_defaults_to_one(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("tasks.executed")

        assert metrics_manager.get_counter("tasks.executed") == 1.0

    def test_increment_accumulates(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("tasks.executed", 3)
        metrics_manager.increment("tasks.executed", 4)

        assert metrics_manager.get_counter("tasks.executed") == 7.0

    def test_increment_can_decrement(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("active.tasks", 2)
        metrics_manager.increment("active.tasks", -1)

        assert metrics_manager.get_counter("active.tasks") == 1.0

    def test_unknown_counter_defaults_to_zero(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        assert metrics_manager.get_counter("missing") == 0.0

    def test_rejects_empty_name(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with pytest.raises(InvalidMetricNameError):
            metrics_manager.increment("")

    def test_get_all_counters_snapshot(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("a")
        metrics_manager.increment("b", 5)

        counters = metrics_manager.get_all_counters()

        assert dict(counters) == {"a": 1.0, "b": 5.0}

        with pytest.raises(TypeError):
            counters["c"] = 1.0  # type: ignore[index]


# ---------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------


class TestGauges:
    def test_set_and_get_gauge(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.set_gauge("memory.usage_mb", 512.0)

        assert metrics_manager.get_gauge("memory.usage_mb") == 512.0

    def test_set_gauge_overwrites_previous_value(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.set_gauge("queue.depth", 3.0)
        metrics_manager.set_gauge("queue.depth", 7.0)

        assert metrics_manager.get_gauge("queue.depth") == 7.0

    def test_unknown_gauge_returns_none(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        assert metrics_manager.get_gauge("missing") is None

    def test_rejects_empty_name(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with pytest.raises(InvalidMetricNameError):
            metrics_manager.set_gauge("", 1.0)

    def test_get_all_gauges_snapshot(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.set_gauge("a", 1.0)

        gauges = metrics_manager.get_all_gauges()

        with pytest.raises(TypeError):
            gauges["b"] = 2.0  # type: ignore[index]


# ---------------------------------------------------------------------
# Timings
# ---------------------------------------------------------------------


class TestTimings:
    def test_record_timing_aggregates_statistics(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.record_timing("capability.execute", 0.1)
        metrics_manager.record_timing("capability.execute", 0.3)
        metrics_manager.record_timing("capability.execute", 0.2)

        stats = metrics_manager.get_timing_stats("capability.execute")

        assert stats is not None
        assert stats.count == 3
        assert stats.min_seconds == pytest.approx(0.1)
        assert stats.max_seconds == pytest.approx(0.3)
        assert stats.total_seconds == pytest.approx(0.6)
        assert stats.average_seconds == pytest.approx(0.2)

    def test_unknown_timing_returns_none(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        assert metrics_manager.get_timing_stats("missing") is None

    def test_average_seconds_is_zero_for_empty_series(self) -> None:
        from parika.core.metrics_manager.timing_stats import TimingStats

        stats = TimingStats(
            count=0,
            total_seconds=0.0,
            min_seconds=0.0,
            max_seconds=0.0,
        )

        assert stats.average_seconds == 0.0

    def test_rejects_negative_duration(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with pytest.raises(InvalidMetricValueError):
            metrics_manager.record_timing("capability.execute", -0.1)

    def test_rejects_empty_name(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with pytest.raises(InvalidMetricNameError):
            metrics_manager.record_timing("", 0.1)

    def test_timer_context_manager_records_duration(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with metrics_manager.timer("block.duration"):
            time.sleep(0.01)

        stats = metrics_manager.get_timing_stats("block.duration")

        assert stats is not None
        assert stats.count == 1
        assert stats.min_seconds > 0.0

    def test_timer_records_duration_even_on_exception(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        with pytest.raises(RuntimeError):
            with metrics_manager.timer("block.duration"):
                raise RuntimeError("boom")

        stats = metrics_manager.get_timing_stats("block.duration")

        assert stats is not None
        assert stats.count == 1

    def test_get_all_timings_snapshot(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.record_timing("a", 0.1)

        timings = metrics_manager.get_all_timings()

        assert "a" in timings

        with pytest.raises(TypeError):
            timings["b"] = None  # type: ignore[index]


# ---------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------


class TestReset:
    def test_reset_clears_everything(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("a")
        metrics_manager.set_gauge("b", 1.0)
        metrics_manager.record_timing("c", 0.1)

        metrics_manager.reset()

        assert metrics_manager.get_counter("a") == 0.0
        assert metrics_manager.get_gauge("b") is None
        assert metrics_manager.get_timing_stats("c") is None

    def test_reset_single_name_only_clears_that_name(
        self,
        metrics_manager: MetricsManager,
    ) -> None:
        metrics_manager.increment("a")
        metrics_manager.increment("b")

        metrics_manager.reset("a")

        assert metrics_manager.get_counter("a") == 0.0
        assert metrics_manager.get_counter("b") == 1.0
