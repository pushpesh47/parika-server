"""
Unit tests for CurrencyToolDriver.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.currency.driver import CurrencyToolDriver
from parika.tools.currency.exceptions import InvalidCurrencyArgumentError
from parika.tools.currency.manifest import CurrencyMode


class _FakeRateBackend:
    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.calls: list[tuple[str, str]] = []

    def get_rate(self, base: str, quote: str) -> float:
        self.calls.append((base, quote))
        return self.rate


class TestExchangeRate:
    def test_returns_rate(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.EXCHANGE_RATE, rate_backend=backend)

        response = driver.execute(
            ToolRequest(arguments={"base": "usd", "quote": "eur"})
        )

        assert response.result == {"base": "USD", "quote": "EUR", "rate": 0.9}
        assert backend.calls == [("USD", "EUR")]

    def test_rejects_invalid_code(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.EXCHANGE_RATE, rate_backend=backend)

        with pytest.raises(InvalidCurrencyArgumentError):
            driver.execute(ToolRequest(arguments={"base": "US", "quote": "EUR"}))


class TestConvert:
    def test_converts_amount(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.CONVERT, rate_backend=backend)

        response = driver.execute(
            ToolRequest(arguments={"base": "USD", "quote": "EUR", "amount": 100})
        )

        assert response.result["converted"] == 90.0

    def test_defaults_amount_to_one(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.CONVERT, rate_backend=backend)

        response = driver.execute(
            ToolRequest(arguments={"base": "USD", "quote": "EUR"})
        )

        assert response.result["amount"] == 1.0
        assert response.result["converted"] == 0.9

    def test_rejects_negative_amount(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.CONVERT, rate_backend=backend)

        with pytest.raises(InvalidCurrencyArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"base": "USD", "quote": "EUR", "amount": -5}
                )
            )

    def test_rejects_non_numeric_amount(self) -> None:
        backend = _FakeRateBackend(0.9)
        driver = CurrencyToolDriver(CurrencyMode.CONVERT, rate_backend=backend)

        with pytest.raises(InvalidCurrencyArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"base": "USD", "quote": "EUR", "amount": "abc"}
                )
            )
