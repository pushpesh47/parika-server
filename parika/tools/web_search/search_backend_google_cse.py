"""
PARIKA Web Search Tool - Google Custom Search (CSE) Backend

A `SearchBackend` implementation backed by Google's official,
JSON-based Custom Search API (https://developers.google.com/custom-search).

Unlike every other provider this Tool ships, this one requires
configuration - an API key and a Search Engine ID (`cx`) - and is
therefore the **only** provider PARIKA implements that requires a
mandatory API key at all (see `provider_registry.py`'s module
docstring for why every other provider deliberately does not).
Because it is Google's own supported, stable API rather than an HTML
scrape, it is not subject to the CAPTCHA/anti-bot concerns
`search_backend_google.py` documents.

`provider_registry.py` treats this provider as unavailable - skipping
it entirely, before ever constructing this class - whenever
`[web_search.google_cse].api_key` or `.search_engine_id` is empty, so
a request that is guaranteed to fail (HTTP 400/403 from Google) is
never attempted. See `WebSearchProviderUnavailableError`'s docstring
for this class's own defensive fallback should it somehow be invoked
without credentials anyway.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from time import sleep as time_sleep
from urllib.parse import quote_plus

from .backend_support import (
    decode_body,
    fetch_with_retry,
    validate_search_arguments,
)
from .exceptions import WebSearchNetworkError, WebSearchProviderUnavailableError
from .search_result import SearchResult
from .transport import HttpTransport

GOOGLE_CSE_ENDPOINT = (
    "https://www.googleapis.com/customsearch/v1"
    "?key={api_key}&cx={search_engine_id}&q={query}&num={max_results}"
)

_MAX_NUM_PER_REQUEST = 10
"""
Google Custom Search's own documented maximum for the `num` parameter
per request.
"""


class GoogleCseSearchBackend:
    """
    SearchBackend implementation using Google's Custom Search JSON
    API.

    Requires an API key and a Search Engine ID (`cx`); see this
    module's docstring.
    """

    def __init__(
        self,
        transport: HttpTransport,
        *,
        api_key: str,
        search_engine_id: str,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time_sleep,
    ) -> None:
        """
        Initialize the search backend.

        Args:
            transport:
                HttpTransport used to issue the search request.

            api_key:
                Google Custom Search API key. See this module's
                docstring for how an empty value is handled.

            search_engine_id:
                Google Custom Search Engine ID (`cx`).

            timeout_seconds:
                Maximum time, in seconds, to wait for the request to
                complete.

            max_attempts:
                Maximum number of attempts, including the first.

            backoff_seconds:
                Base delay, in seconds, between retry attempts.

            sleep:
                Sleep function used between retry attempts.
        """

        self._transport = transport
        self._api_key = api_key
        self._search_engine_id = search_engine_id
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """
        Perform a web search using Google's Custom Search JSON API.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchProviderUnavailableError:
                If invoked without an `api_key` or `search_engine_id`
                (see this module's docstring - `provider_registry.py`
                prevents this under normal operation).

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason,
                Google responds with an HTTP error status, or the
                response body is not the expected JSON shape.
        """

        validate_search_arguments(query, max_results)

        if not self._api_key or not self._search_engine_id:
            raise WebSearchProviderUnavailableError(
                "Google Custom Search requires both an api_key and a "
                "search_engine_id; configure "
                "[web_search.google_cse] or omit 'google_cse' from "
                "[web_search].provider_order."
            )

        url = GOOGLE_CSE_ENDPOINT.format(
            api_key=quote_plus(self._api_key),
            search_engine_id=quote_plus(self._search_engine_id),
            query=quote_plus(query),
            max_results=min(max_results, _MAX_NUM_PER_REQUEST),
        )

        response = fetch_with_retry(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
        )

        body_text = decode_body(response)

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as ex:
            raise WebSearchNetworkError(
                "Google Custom Search returned a malformed (non-JSON) "
                "response."
            ) from ex

        if response.status_code >= 400:
            message = _extract_error_message(payload) or (
                f"HTTP {response.status_code}"
            )
            raise WebSearchNetworkError(
                f"Google Custom Search returned an error: {message}"
            )

        if not isinstance(payload, dict):
            raise WebSearchNetworkError(
                "Google Custom Search returned a malformed response "
                "(expected a JSON object)."
            )

        items = payload.get("items")

        if not isinstance(items, list):
            return ()

        results: list[SearchResult] = []

        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            link = item.get("link")

            if not isinstance(title, str) or not isinstance(link, str):
                continue

            snippet = item.get("snippet")

            results.append(
                SearchResult(
                    title=title,
                    url=link,
                    snippet=snippet if isinstance(snippet, str) else None,
                )
            )

        return tuple(results)


def _extract_error_message(payload: object) -> str | None:
    """
    Best-effort extraction of Google's own `{"error": {"message":
    ...}}` error shape, when present.
    """

    if not isinstance(payload, dict):
        return None

    error = payload.get("error")

    if not isinstance(error, dict):
        return None

    message = error.get("message")

    return message if isinstance(message, str) else None
