"""
PARIKA Web Search Tool - DuckDuckGo Search Backend

A `SearchBackend` implementation backed by DuckDuckGo's public,
no-API-key HTML results endpoint. Requires no configuration and is
always considered available (see `provider_registry.py`).

Parses the returned HTML using only the Python standard library.
"""

from __future__ import annotations
import logging
from collections.abc import Callable
from html.parser import HTMLParser
from time import sleep as time_sleep
from urllib.parse import parse_qs, quote_plus, urlparse

from .backend_support import (
    decode_body,
    fetch_with_retry,
    raise_if_blocked,
    raise_if_http_error,
    validate_search_arguments,
)
from .search_result import SearchResult
from .transport import HttpTransport

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/?q={query}"

_BLOCKED_INDICATORS = ("anomaly-modal",)
"""
DuckDuckGo occasionally serves an interactive anti-bot challenge page
instead of search results, most commonly for requests originating
from datacenter or shared IP addresses.
"""


class _DuckDuckGoResultParser(HTMLParser):
    """
    Extracts search results from a DuckDuckGo HTML results page.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.results: list[dict[str, str]] = []

        self._in_result_title = False
        self._in_result_snippet = False
        self._pending_url: str | None = None
        self._pending_title_chunks: list[str] = []
        self._pending_snippet_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        if tag != "a":
            return

        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        if "result__a" in classes:
            self._flush_pending()
            self._in_result_title = True
            self._pending_url = _unwrap_ddg_redirect(
                attributes.get("href") or ""
            )
            return

        if "result__snippet" in classes:
            self._in_result_snippet = True

    def handle_endtag(self, tag: str) -> None:

        if tag != "a":
            return

        if self._in_result_title:
            self._in_result_title = False

        if self._in_result_snippet:
            self._in_result_snippet = False

    def handle_data(self, data: str) -> None:

        if self._in_result_title:
            self._pending_title_chunks.append(data)

        elif self._in_result_snippet:
            self._pending_snippet_chunks.append(data)

    def close(self) -> None:
        self._flush_pending()
        super().close()

    def _flush_pending(self) -> None:

        title = "".join(self._pending_title_chunks).strip()

        if title and self._pending_url:
            self.results.append(
                {
                    "title": title,
                    "url": self._pending_url,
                    "snippet": "".join(
                        self._pending_snippet_chunks
                    ).strip(),
                }
            )

        self._pending_url = None
        self._pending_title_chunks = []
        self._pending_snippet_chunks = []


def _unwrap_ddg_redirect(href: str) -> str:
    """
    Resolve a DuckDuckGo redirect URL into the real target URL.

    DuckDuckGo's HTML results serve links through a `/l/?uddg=<url>`
    redirect. When `href` does not match that pattern, it is returned
    unchanged.
    """

    if not href:
        return href

    normalized = href if href.startswith("http") else f"https:{href}"

    parsed = urlparse(normalized)

    if parsed.path != "/l/":
        return normalized

    query = parse_qs(parsed.query)
    target = query.get("uddg")

    if not target:
        return normalized

    return target[0]


class DuckDuckGoHtmlSearchBackend:
    """
    SearchBackend implementation using DuckDuckGo's HTML results
    endpoint.

    This endpoint requires no API key. Results are parsed directly
    from the returned HTML using only the Python standard library.
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
        """
        Initialize the search backend.

        Args:
            transport:
                HttpTransport used to issue the search request.

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
        Perform a web search using DuckDuckGo's HTML endpoint.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason, an
                anti-bot challenge page is served, or Duckduckgo
                responds with an HTTP error status.
        """

        validate_search_arguments(query, max_results)

        url = DUCKDUCKGO_HTML_ENDPOINT.format(query=quote_plus(query))

        response = fetch_with_retry(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
        )
        raise_if_http_error(response, provider_name="DuckDuckGo")

        body_text = decode_body(response)
        logger.debug("First 5000 characters of DuckDuckGo response:")
        logger.debug(body_text[:5000])
        raise_if_blocked(
            body_text,
            provider_name="DuckDuckGo",
            indicators=_BLOCKED_INDICATORS,
        )

        parser = _DuckDuckGoResultParser()
        parser.feed(body_text)
        parser.close()

        logger.debug("========== DUCKDUCKGO SEARCH PARSER ==========")
        logger.debug("Query: %s", query)
        logger.debug("URL: %s", url)
        logger.debug("HTML Size: %d bytes", len(body_text))
        logger.debug("Parsed Results: %d", len(parser.results))

        for index, result in enumerate(parser.results, start=1):
            logger.debug(
                "[%d] Title=%r | URL=%r | Snippet=%r",
                index,
                result["title"],
                result["url"],
                result["snippet"],
            )

        logger.debug("========================================")

        return tuple(
            SearchResult(
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"] or None,
            )
            for result in parser.results[:max_results]
        )
