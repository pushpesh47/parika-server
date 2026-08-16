"""
PARIKA Web Search Tool - Shared Backend Support

Small, provider-agnostic helpers reused by every HTML-scraping
`search_backend_<provider>.py` implementation, so common concerns -
input validation, retrying a fetch, and recognizing that a provider
blocked the request (an anti-bot challenge, a CAPTCHA, or an outright
HTTP error) - are implemented exactly once rather than duplicated
across providers.

Not itself a search provider, and deliberately does not follow the
`search_backend_<provider>.py` naming convention reserved for actual
provider implementations (see `provider_registry.py`'s module
docstring).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import sleep as time_sleep

from .exceptions import (
    InvalidSearchQueryError,
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from .retry import retry_with_backoff
from .transport import HttpResponse, HttpTransport

RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    WebSearchTimeoutError,
    WebSearchNetworkError,
)


def validate_search_arguments(query: str, max_results: int) -> None:
    """
    Validate a search request's `query` and `max_results`, identically
    across every provider.

    Raises:
        InvalidSearchQueryError:
            If `query` is empty, or `max_results` is not positive.
    """

    if not isinstance(query, str) or not query.strip():
        raise InvalidSearchQueryError("query must be a non-empty string.")

    if max_results < 1:
        raise InvalidSearchQueryError("max_results must be at least 1.")


def fetch_with_retry(
    transport: HttpTransport,
    url: str,
    *,
    timeout_seconds: float,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Callable[[float], None] = time_sleep,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    """
    Issue an HTTP GET through `transport`, retrying on
    `WebSearchTimeoutError`/`WebSearchNetworkError` with linear
    backoff - the exact retry policy every HTML-scraping provider
    shares.
    """

    if method.upper() == "POST":
        request = lambda: transport.post(
            url,
            data=data,
            timeout=timeout_seconds,
            headers=headers or {},
        )
    else:
        request = lambda: transport.get(url, timeout=timeout_seconds)

    return retry_with_backoff(
        request,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        retryable_exceptions=RETRYABLE_EXCEPTIONS,
        sleep=sleep,
    )


def decode_body(response: HttpResponse) -> str:
    """
    Decode an `HttpResponse`'s raw body as UTF-8 text, replacing any
    invalid byte sequences rather than raising - a scraped results
    page is never worth failing a search over a single bad byte.
    """

    return response.body.decode("utf-8", errors="replace")


def raise_if_blocked(
    body_text: str,
    *,
    provider_name: str,
    indicators: tuple[str, ...],
) -> None:
    """
    Raise `WebSearchNetworkError` when `body_text` matches a known
    anti-bot-challenge or CAPTCHA indicator for this provider, instead
    of silently returning zero results - which would otherwise look
    identical to a genuine "no results" outcome.

    Args:
        body_text:
            The provider's decoded response body.

        provider_name:
            Human-readable provider name, for the error message.

        indicators:
            Substrings known to appear on this provider's
            challenge/CAPTCHA page. Each provider supplies its own -
            this function has no built-in knowledge of any provider.
    """

    lowered = body_text.lower()

    if any(indicator.lower() in lowered for indicator in indicators):
        raise WebSearchNetworkError(
            f"{provider_name} returned an anti-bot challenge or "
            "CAPTCHA page instead of search results. This commonly "
            "occurs when requests originate from a datacenter or "
            "shared IP address. Configure a different provider (see "
            "`[web_search].provider_order`) for environments affected "
            "by this."
        )


def raise_if_http_error(
    response: HttpResponse,
    *,
    provider_name: str,
) -> None:
    """
    Raise `WebSearchNetworkError` when `response.status_code` is not
    a success status, instead of attempting to parse what is likely
    an error page as if it were search results.
    """

    if response.status_code >= 400:
        raise WebSearchNetworkError(
            f"{provider_name} returned HTTP {response.status_code}."
        )
