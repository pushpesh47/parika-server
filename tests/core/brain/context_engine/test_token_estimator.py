"""Unit tests for HeuristicTokenEstimator."""

from __future__ import annotations

from parika.core.brain.context_engine.token_estimator import HeuristicTokenEstimator


class TestHeuristicTokenEstimator:
    def test_empty_text_is_zero(self) -> None:
        assert HeuristicTokenEstimator().estimate("") == 0

    def test_short_text_is_at_least_one(self) -> None:
        assert HeuristicTokenEstimator().estimate("hi") == 1

    def test_scales_with_length(self) -> None:
        estimator = HeuristicTokenEstimator()

        short = estimator.estimate("a" * 40)
        long = estimator.estimate("a" * 400)

        assert long > short
        assert short == 10
        assert long == 100
