"""
PARIKA Currency Tool - Open Exchange Rates (open.er-api.com) Backend

A `RateBackend` implementation backed by the ExchangeRate-API open
access endpoint (https://open.er-api.com) - keyless, updated once
daily, with wider currency coverage than Frankfurter's ECB-anchored
set. Used only as a configured failover provider (see
`config.DEFAULT_PROVIDER_ORDER`), never as the primary provider: it is
a closed-source commercial service's free tier, with a stated
soft-rate-limit fair-use policy, rather than an open-source,
self-hostable project.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as time_sleep

from .backend_support import fetch_json, validate_currency_code
from .exceptions import CurrencyNetworkError, UnsupportedCurrencyPairError
from .transport import HttpTransport

OPEN_ER_API_ENDPOINT = "https://open.er-api.com/v6/latest"


class OpenErApiRateBackend:
    """
    RateBackend implementation using the open.er-api.com endpoint.
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
                If open.er-api.com has no rate for this pair.

            CurrencyTimeoutError, CurrencyNetworkError:
                On network failure or a malformed response.
        """

        base_code = validate_currency_code(base, argument_name="base")
        quote_code = validate_currency_code(quote, argument_name="quote")

        url = f"{OPEN_ER_API_ENDPOINT}/{base_code}"

        payload = fetch_json(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            provider_name="open.er-api.com",
        )

        if payload.get("result") != "success":
            raise CurrencyNetworkError(
                "open.er-api.com reported an unsuccessful result: "
                f"{payload.get('error-type', 'unknown error')}."
            )

        rates = payload.get("rates")

        if not isinstance(rates, dict) or quote_code not in rates:
            raise UnsupportedCurrencyPairError(
                f"open.er-api.com has no rate for "
                f"{base_code}->{quote_code}."
            )

        try:
            return float(rates[quote_code])
        except (TypeError, ValueError) as ex:
            raise CurrencyNetworkError(
                "open.er-api.com returned a non-numeric rate."
            ) from ex
