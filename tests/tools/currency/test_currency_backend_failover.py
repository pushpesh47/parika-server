"""
Unit tests for FailoverRateBackend.
"""

from __future__ import annotations

import pytest

from parika.tools.currency.backend_failover import FailoverRateBackend
from parika.tools.currency.exceptions import (
    CurrencyAllProvidersFailedError,
    CurrencyNetworkError,
    InvalidCurrencyArgumentError,
)


class _FakeBackend:
    def __init__(self, *, rate: float | None = None, error: Exception | None = None) -> None:
        self._rate = rate
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def get_rate(self, base: str, quote: str) -> float:
        self.calls.append((base, quote))

        if self._error is not None:
            raise self._error

        assert self._rate is not None
        return self._rate


class TestFailoverRateBackend:
    def test_returns_first_successful_backend(self) -> None:
        first = _FakeBackend(rate=1.5)
        second = _FakeBackend(rate=2.0)

        backend = FailoverRateBackend([("a", first), ("b", second)])
        rate = backend.get_rate("USD", "EUR")

        assert rate == 1.5
        assert second.calls == []

    def test_falls_over_to_next_backend_on_failure(self) -> None:
        first = _FakeBackend(error=CurrencyNetworkError("boom"))
        second = _FakeBackend(rate=2.0)

        backend = FailoverRateBackend([("a", first), ("b", second)])
        rate = backend.get_rate("USD", "EUR")

        assert rate == 2.0

    def test_all_providers_failing_raises(self) -> None:
        first = _FakeBackend(error=CurrencyNetworkError("boom1"))
        second = _FakeBackend(error=CurrencyNetworkError("boom2"))

        backend = FailoverRateBackend([("a", first), ("b", second)])

        with pytest.raises(CurrencyAllProvidersFailedError):
            backend.get_rate("USD", "EUR")

    def test_validation_error_propagates_immediately_without_trying_others(
        self,
    ) -> None:
        first = _FakeBackend(error=InvalidCurrencyArgumentError("bad"))
        second = _FakeBackend(rate=2.0)

        backend = FailoverRateBackend([("a", first), ("b", second)])

        with pytest.raises(InvalidCurrencyArgumentError):
            backend.get_rate("US", "EUR")

        assert second.calls == []

    def test_requires_at_least_one_backend(self) -> None:
        with pytest.raises(ValueError):
            FailoverRateBackend([])
