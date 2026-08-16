"""
PARIKA Currency Tool - Shared Backend Support

Small, provider-agnostic helpers reused by every
`backend_<provider>.py` implementation, so common concerns - currency
code validation, retrying a fetch, and decoding a JSON response - are
implemented exactly once rather than duplicated across providers.
Mirrors `parika/tools/web_search/backend_support.py`'s role for
search backends.
"""

from __future__ import annotations

import json
import re

from .exceptions import (
    CurrencyNetworkError,
    CurrencyTimeoutError,
    InvalidCurrencyArgumentError,
)
from .retry import retry_with_backoff
from .transport import HttpResponse, HttpTransport

_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Za-z]{3}$")

_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    CurrencyNetworkError,
    CurrencyTimeoutError,
)


def validate_currency_code(code: object, *, argument_name: str) -> str:
    """
    Validate and normalize an ISO 4217-shaped currency code.

    Raises:
        InvalidCurrencyArgumentError:
            If `code` is not a 3-letter alphabetic string.
    """

    if not isinstance(code, str) or not _CURRENCY_CODE_PATTERN.match(code):
        raise InvalidCurrencyArgumentError(
            f"request.arguments['{argument_name}'] must be a "
            "3-letter ISO 4217 currency code (e.g. 'USD')."
        )

    return code.upper()


def fetch_json(
    transport: HttpTransport,
    url: str,
    *,
    timeout_seconds: float,
    max_attempts: int,
    backoff_seconds: float,
    provider_name: str,
) -> dict:
    """
    Fetch `url` with retry, and decode it as JSON.

    Raises:
        CurrencyTimeoutError:
            If every attempt times out.

        CurrencyNetworkError:
            If every attempt fails for another network reason, the
            provider returns an HTTP error status, or the response
            body is not valid JSON.
    """

    def _get() -> HttpResponse:
        response = transport.get(url, timeout=timeout_seconds)

        if response.status_code >= 400:
            raise CurrencyNetworkError(
                f"{provider_name} returned HTTP {response.status_code}."
            )

        return response

    response = retry_with_backoff(
        _get,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        retryable_exceptions=_RETRYABLE_EXCEPTIONS,
    )

    try:
        return json.loads(response.body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as ex:
        raise CurrencyNetworkError(
            f"{provider_name} returned a malformed JSON response."
        ) from ex
