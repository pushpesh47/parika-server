"""
Unit tests for `parika.providers.ollama.latency_estimation`.
"""

from __future__ import annotations

import pytest

from parika.providers.ollama.latency_estimation import (
    estimate_baseline_metrics,
    parse_parameter_count,
)


class TestParseParameterCount:
    def test_parses_billions(self) -> None:
        assert parse_parameter_count("8.2B") == pytest.approx(8.2e9)

    def test_parses_millions(self) -> None:
        assert parse_parameter_count("70M") == 70e6

    def test_returns_none_for_missing_value(self) -> None:
        assert parse_parameter_count(None) is None

    def test_returns_none_for_unparsable_value(self) -> None:
        assert parse_parameter_count("unknown") is None


class TestEstimateBaselineMetrics:
    def test_returns_empty_dict_without_parameter_size(self) -> None:
        assert estimate_baseline_metrics({}) == {}

    def test_larger_models_get_higher_latency_estimate(self) -> None:
        small = estimate_baseline_metrics({"parameter_size": "1B"})
        large = estimate_baseline_metrics({"parameter_size": "70B"})

        assert (
            large["estimated_latency_ms"] > small["estimated_latency_ms"]
        )

    def test_reasoning_models_get_higher_latency_estimate(self) -> None:
        without_reasoning = estimate_baseline_metrics(
            {"parameter_size": "8B"}, supports_reasoning=False
        )
        with_reasoning = estimate_baseline_metrics(
            {"parameter_size": "8B"}, supports_reasoning=True
        )

        assert (
            with_reasoning["estimated_latency_ms"]
            > without_reasoning["estimated_latency_ms"]
        )
        assert (
            with_reasoning["estimated_throughput_tps"]
            < without_reasoning["estimated_throughput_tps"]
        )
