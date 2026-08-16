"""
Unit tests for the Frankfurter and open.er-api.com rate backends.
"""

from __future__ import annotations

import json

import pytest

from parika.tools.currency.backend_frankfurter import FrankfurterRateBackend
from parika.tools.currency.backend_open_er_api import OpenErApiRateBackend
from parika.tools.currency.exceptions import (
    CurrencyNetworkError,
    InvalidCurrencyArgumentError,
    UnsupportedCurrencyPairError,
)
from parika.tools.currency.transport import HttpResponse


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, body: bytes, status_code: int = 200) -> None:
        self._responses.append(
            HttpResponse(status_code=status_code, url="", headers={}, body=body)
        )

    def queue_error(self, error: Exception) -> None:
        self._responses.append(error)

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)
        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


class TestFrankfurterRateBackend:
    def test_returns_rate(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            json.dumps(
                {"amount": 1.0, "base": "USD", "date": "2026-07-30", "rates": {"EUR": 0.93}}
            ).encode()
        )

        backend = FrankfurterRateBackend(transport, sleep=lambda s: None)
        rate = backend.get_rate("usd", "eur")

        assert rate == 0.93
        assert "base=USD" in transport.calls[0]

    def test_rejects_invalid_currency_code(self) -> None:
        backend = FrankfurterRateBackend(_FakeTransport())

        with pytest.raises(InvalidCurrencyArgumentError):
            backend.get_rate("US", "EUR")

    def test_missing_rate_raises_unsupported_pair(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            json.dumps({"amount": 1.0, "base": "USD", "rates": {}}).encode()
        )

        backend = FrankfurterRateBackend(transport, sleep=lambda s: None)

        with pytest.raises(UnsupportedCurrencyPairError):
            backend.get_rate("USD", "XYZ")

    def test_http_error_raises_network_error(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(b"error", status_code=500)

        backend = FrankfurterRateBackend(
            transport, max_attempts=1, sleep=lambda s: None
        )

        with pytest.raises(CurrencyNetworkError):
            backend.get_rate("USD", "EUR")


class TestOpenErApiRateBackend:
    def test_returns_rate(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            json.dumps({"result": "success", "rates": {"EUR": 0.95}}).encode()
        )

        backend = OpenErApiRateBackend(transport, sleep=lambda s: None)
        rate = backend.get_rate("USD", "EUR")

        assert rate == 0.95

    def test_unsuccessful_result_raises_network_error(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            json.dumps({"result": "error", "error-type": "invalid-key"}).encode()
        )

        backend = OpenErApiRateBackend(transport, sleep=lambda s: None)

        with pytest.raises(CurrencyNetworkError):
            backend.get_rate("USD", "EUR")

    def test_missing_rate_raises_unsupported_pair(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            json.dumps({"result": "success", "rates": {}}).encode()
        )

        backend = OpenErApiRateBackend(transport, sleep=lambda s: None)

        with pytest.raises(UnsupportedCurrencyPairError):
            backend.get_rate("USD", "XYZ")
