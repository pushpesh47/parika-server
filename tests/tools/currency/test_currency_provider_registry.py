"""
Unit tests for `parika.tools.currency.provider_registry`.
"""

from __future__ import annotations

import pytest

from parika.tools.currency.backend_failover import FailoverRateBackend
from parika.tools.currency.backend_frankfurter import FrankfurterRateBackend
from parika.tools.currency.backend_open_er_api import OpenErApiRateBackend
from parika.tools.currency.config import CurrencyToolConfig
from parika.tools.currency.provider_registry import build_rate_backend


class _FakeTransport:
    def get(self, url: str, *, timeout: float):  # noqa: ANN201
        raise AssertionError("not used in these tests")


class TestBuildRateBackend:
    def test_single_provider_returns_unwrapped_backend(self) -> None:
        config = CurrencyToolConfig(
            default_provider="frankfurter", provider_order=["frankfurter"]
        )

        backend = build_rate_backend(config, _FakeTransport())

        assert isinstance(backend, FrankfurterRateBackend)

    def test_multiple_providers_build_failover(self) -> None:
        config = CurrencyToolConfig(
            default_provider="frankfurter",
            provider_order=["frankfurter", "open_er_api"],
        )

        backend = build_rate_backend(config, _FakeTransport())

        assert isinstance(backend, FailoverRateBackend)

    def test_unrecognized_provider_is_skipped(self) -> None:
        config = CurrencyToolConfig(
            default_provider="mystery", provider_order=["mystery", "open_er_api"]
        )

        backend = build_rate_backend(config, _FakeTransport())

        assert isinstance(backend, OpenErApiRateBackend)

    def test_no_recognized_provider_raises(self) -> None:
        config = CurrencyToolConfig(
            default_provider="mystery", provider_order=["mystery"]
        )

        with pytest.raises(ValueError):
            build_rate_backend(config, _FakeTransport())
