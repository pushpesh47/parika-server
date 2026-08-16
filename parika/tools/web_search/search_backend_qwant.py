"""
PARIKA Web Search Tool - Qwant Search Backend (HTML)

A `SearchBackend` implementation backed by Qwant Lite's public,
server-rendered HTML results page - a lightweight variant of Qwant's
search results intended for low-bandwidth/non-JS clients, which makes
it far more amenable to stdlib HTML parsing than Qwant's default,
heavily JavaScript-rendered site. Requires no configuration and is
always considered available (see `provider_registry.py`).

Like the other HTML-scraping backends, this requires no API key and
parses the returned HTML using only the Python standard library. See
`search_backend_google.py`'s module docstring for the general caveat
that any HTML-scraping backend may need updates if a provider changes
its markup.
"""

from __future__ import annotations

from collections.abc import Callable
from html.parser import HTMLParser
from time import sleep as time_sleep
from urllib.parse import quote_plus

from .backend_support import (
    decode_body,
    fetch_with_retry,
    raise_if_http_error,
    validate_search_arguments,
)
from .search_result import SearchResult
from .transport import HttpTransport

QWANT_LITE_HTML_ENDPOINT = "https://lite.qwant.com/?q={query}"


class _QwantResultParser(HTMLParser):
    """
    Extracts search results from a Qwant Lite HTML results page.

    Qwant Lite's organic results are `<div class="result">` blocks
    containing a title anchor tagged `class="result--title"` and a
    snippet element tagged `class="result--desc"`.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.results: list[dict[str, str]] = []

        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._title_captured = False
        self._pending_url: str | None = None
        self._pending_title_chunks: list[str] = []
        self._pending_snippet_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        if tag == "div" and "result" in classes:
            self._flush_pending()
            self._in_result = True
            return

        if not self._in_result:
            return

        if (
            tag == "a"
            and "result--title" in classes
            and not self._title_captured
        ):
            href = attributes.get("href")

            if href:
                self._pending_url = href
                self._in_title = True

            return

        if "result--desc" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:

        if tag == "a" and self._in_title:
            self._in_title = False
            self._title_captured = True

        elif self._in_snippet and tag in ("p", "div", "span"):
            self._in_snippet = False

    def handle_data(self, data: str) -> None:

        if self._in_title:
            self._pending_title_chunks.append(data)

        elif self._in_snippet:
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

        self._in_title = False
        self._in_snippet = False
        self._title_captured = False
        self._pending_url = None
        self._pending_title_chunks = []
        self._pending_snippet_chunks = []


class QwantHtmlSearchBackend:
    """
    SearchBackend implementation using Qwant Lite's HTML results
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
        Perform a web search using Qwant Lite's HTML endpoint.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason, or
                Qwant responds with an HTTP error status.
        """

        validate_search_arguments(query, max_results)

        url = QWANT_LITE_HTML_ENDPOINT.format(query=quote_plus(query))

        response = fetch_with_retry(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
        )
        raise_if_http_error(response, provider_name="Qwant")

        body_text = decode_body(response)

        parser = _QwantResultParser()
        parser.feed(body_text)
        parser.close()

        return tuple(
            SearchResult(
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"] or None,
            )
            for result in parser.results[:max_results]
        )
