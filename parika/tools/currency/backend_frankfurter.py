"""
PARIKA Currency Tool - Frankfurter Rate Backend

A `RateBackend` implementation backed by Frankfurter
(https://api.frankfurter.dev) - an open-source (MIT), keyless
currency exchange rate API sourcing daily reference rates from the
European Central Bank and 80+ other central banks. No API key or
account is required, and there is no request quota (only anti-abuse
rate limiting).

Frankfurter's currency coverage (as of its v1 API) is anchored to
ECB-tracked currencies; a pair outside that coverage raises
`UnsupportedCurrencyPairError` rather than an ambiguous KeyError, so
`FailoverRateBackend` can fall over to a wider-coverage provider (see
`backend_open_er_api.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as time_sleep
from urllib.parse import urlencode

from .backend_support import fetch_json, validate_currency_code
from .exceptions import CurrencyNetworkError, UnsupportedCurrencyPairError
from .transport import HttpTransport

FRANKFURTER_ENDPOINT = "https://api.frankfurter.dev/v1/latest"


class FrankfurterRateBackend:
    """
    RateBackend implementation using the Frankfurter API.
    """

    def __init__(
        self,
        transport: HttpTransport,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time_sleep,
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def get_rate(self, base: str, quote: str) -> float:
        """
        Return the exchange rate from `base` to `quote`.

        Raises:
            InvalidCurrencyArgumentError:
                If `base`/`quote` is not a 3-letter currency code.

            UnsupportedCurrencyPairError:
                If Frankfurter has no rate for this pair.

            CurrencyTimeoutError, CurrencyNetworkError:
                On network failure or a malformed response.
        """

        base_code = validate_currency_code(base, argument_name="base")
        quote_code = validate_currency_code(quote, argument_name="quote")

        query = urlencode({"base": base_code, "symbols": quote_code})
        url = f"{FRANKFURTER_ENDPOINT}?{query}"

        payload = fetch_json(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            provider_name="Frankfurter",
        )

        rates = payload.get("rates")

        if not isinstance(rates, dict) or quote_code not in rates:
            raise UnsupportedCurrencyPairError(
                f"Frankfurter has no rate for {base_code}->{quote_code}."
            )

        try:
            return float(rates[quote_code])
        except (TypeError, ValueError) as ex:
            raise CurrencyNetworkError(
                "Frankfurter returned a non-numeric rate."
            ) from ex
