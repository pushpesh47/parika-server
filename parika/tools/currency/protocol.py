"""
PARIKA Currency Tool - Rate Backend Protocol

Defines the `RateBackend` contract every currency rate provider
implementation (`backend_<provider>.py`) satisfies. Mirrors
`parika/tools/web_search/protocol.py`'s `SearchBackend` pattern
exactly: isolating the rate source behind a small protocol allows
`CurrencyToolDriver` to be exercised deterministically in tests
without depending on a live provider, while every concrete
implementation remains a genuine, working client for production use.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RateBackend(Protocol):
    """
    Protocol implemented by every currency rate provider usable by
    the Currency Tool.
    """

    def get_rate(self, base: str, quote: str) -> float:
        """
        Return the exchange rate from `base` to `quote`: how many
        units of `quote` one unit of `base` is worth.

        Args:
            base:
                ISO 4217 base currency code (e.g. `"USD"`).

            quote:
                ISO 4217 quote currency code (e.g. `"EUR"`).

        Returns:
            The exchange rate.

        Raises:
            UnsupportedCurrencyPairError:
                If this provider has no rate for the requested pair.

            CurrencyTimeoutError:
                If the request times out on every attempt.

            CurrencyNetworkError:
                If the request fails for another network reason on
                every attempt, or the response is malformed.
        """
        ...
