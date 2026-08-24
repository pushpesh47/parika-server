"""
PARIKA Currency Tool - Driver

Implements the `ToolDriver` contract for the `currency.exchange_rate`
and `currency.convert` Capabilities.

A single `CurrencyToolDriver` instance is bound to exactly one
`CurrencyMode` at construction time (see `manifest.py`'s module
docstring). The Currency Module constructs two instances - one per
Capability - and registers each as its own Tool.

Both Capabilities are backed by the same `RateBackend` (a
`FailoverRateBackend` over Frankfurter and open.er-api.com by
default; see `provider_registry.py`) - `currency.convert` simply
multiplies the looked-up rate by the requested amount.
"""

from __future__ import annotations

from typing import Any

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .backend_support import validate_currency_code
from .exceptions import InvalidCurrencyArgumentError
from .manifest import CurrencyMode
from .protocol import RateBackend

import logging

_logger = logging.getLogger(__name__)

class CurrencyToolDriver:
    """
    ToolDriver implementing one Currency Tool Capability.
    """

    def __init__(
        self,
        mode: CurrencyMode,
        *,
        rate_backend: RateBackend,
    ) -> None:
        """
        Initialize the driver for one Capability.

        Args:
            mode:
                Whether this instance implements
                `currency.exchange_rate` or `currency.convert`.

            rate_backend:
                Backend used to look up exchange rates.
        """

        self._mode = mode
        self._rate_backend = rate_backend

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound Capability.

        Expected `request.arguments`:
            base (str):
                Required 3-letter ISO 4217 base currency code (e.g.
                `"USD"`).

            quote (str):
                Required 3-letter ISO 4217 quote currency code (e.g.
                `"EUR"`).

            amount (float):
                Required for `currency.convert` only: the amount, in
                `base`, to convert. Defaults to `1` when omitted.

        Raises:
            InvalidCurrencyArgumentError:
                If `base`/`quote` is not a 3-letter currency code, or
                `amount` is not a positive number.

            UnsupportedCurrencyPairError:
                If no configured provider has a rate for this pair.

            CurrencyTimeoutError, CurrencyNetworkError:
                On network failure or a malformed provider response.

            CurrencyAllProvidersFailedError:
                If every configured provider failed.
        """
        _logger.debug(
            "CurrencyToolDriver.execute-check-: mode=%s arguments=%r",
            self._mode,
            request.arguments,
        )
        base = request.arguments.get("base") or request.arguments.get("from")
        base = validate_currency_code(base, argument_name="base")

        quote = request.arguments.get("quote") or request.arguments.get("to")
        quote = validate_currency_code(quote, argument_name="quote")

        rate = self._rate_backend.get_rate(base, quote)

        if self._mode is CurrencyMode.EXCHANGE_RATE:
            result = {
                "base": base,
                "quote": quote,
                "rate": rate,
            }

            return ToolResponse(
                result=result, attributes={"base": base, "quote": quote}
            )

        raw_amount: Any = request.arguments.get("amount", 1)

        try:
            amount = float(raw_amount)
        except (TypeError, ValueError) as ex:
            raise InvalidCurrencyArgumentError(
                "request.arguments['amount'] must be a number."
            ) from ex

        if amount < 0:
            raise InvalidCurrencyArgumentError(
                "request.arguments['amount'] must not be negative."
            )

        converted = amount * rate

        result = {
            "base": base,
            "quote": quote,
            "amount": amount,
            "rate": rate,
            "converted": converted,
        }

        return ToolResponse(
            result=result, attributes={"base": base, "quote": quote}
        )
